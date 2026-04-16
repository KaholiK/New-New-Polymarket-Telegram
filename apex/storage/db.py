"""aiosqlite persistence: schemas, CRUD, migrations.

A single long-lived connection is fine for this workload (single process, low QPS).
Tables use plain columns, not ORMs — schema is small and explicit.

Connection lifecycle
--------------------
``Database.connect()`` retries with exponential backoff (1s, 2s, 4s, 8s, 16s,
capped at ``max_delay``) before giving up. ``is_healthy()`` checks the current
connection with a cheap ``SELECT 1`` so background jobs can skip work when the
DB is unreachable instead of spamming ``RuntimeError("Database not connected")``.
``ensure_connected()`` transparently re-establishes a broken connection.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

import aiosqlite

from apex.utils.logger import get_logger

logger = get_logger(__name__)


SCHEMA_STATEMENTS: list[str] = [
    # Trades
    """
    CREATE TABLE IF NOT EXISTS trades (
        id TEXT PRIMARY KEY,
        signal_id TEXT,
        market_id TEXT NOT NULL,
        event_id TEXT,
        strategy TEXT,
        side TEXT NOT NULL,
        size_usd REAL NOT NULL,
        entry_price REAL NOT NULL,
        filled_qty REAL DEFAULT 0,
        filled_price REAL DEFAULT 0,
        status TEXT NOT NULL,
        pnl REAL DEFAULT 0,
        closing_price REAL,
        clv REAL,
        dry_run INTEGER DEFAULT 1,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        resolved_at TEXT
    )
    """,
    # Bankroll snapshots
    """
    CREATE TABLE IF NOT EXISTS bankroll_snapshots (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        bankroll REAL NOT NULL,
        unrealized_pnl REAL DEFAULT 0,
        ts TEXT NOT NULL
    )
    """,
    # Game results for Elo/calibration
    """
    CREATE TABLE IF NOT EXISTS game_results (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        event_id TEXT UNIQUE,
        sport TEXT,
        league TEXT,
        home_team TEXT,
        away_team TEXT,
        home_score INTEGER,
        away_score INTEGER,
        winner TEXT,
        completed_at TEXT
    )
    """,
    # Elo ratings
    """
    CREATE TABLE IF NOT EXISTS elo_ratings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sport TEXT NOT NULL,
        league TEXT,
        team TEXT NOT NULL,
        elo REAL NOT NULL,
        updated_at TEXT NOT NULL,
        UNIQUE(sport, team)
    )
    """,
    # Odds snapshots for CLV and backtesting
    """
    CREATE TABLE IF NOT EXISTS odds_snapshots (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        event_id TEXT,
        source TEXT,
        home_odds REAL,
        away_odds REAL,
        home_implied_prob REAL,
        away_implied_prob REAL,
        fetched_at TEXT
    )
    """,
    # Forecasts (persist for calibration)
    """
    CREATE TABLE IF NOT EXISTS forecasts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        event_id TEXT,
        market_id TEXT,
        model_name TEXT,
        sport TEXT,
        predicted_prob REAL,
        market_price REAL,
        edge REAL,
        confidence TEXT,
        actual_outcome INTEGER,
        brier_score REAL,
        created_at TEXT,
        resolved_at TEXT
    )
    """,
    # Calibration buckets
    """
    CREATE TABLE IF NOT EXISTS calibration_state (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        model_name TEXT,
        sport TEXT,
        bucket INTEGER,
        predicted_count INTEGER DEFAULT 0,
        actual_wins INTEGER DEFAULT 0,
        updated_at TEXT,
        UNIQUE(model_name, sport, bucket)
    )
    """,
    # Market catalog
    """
    CREATE TABLE IF NOT EXISTS market_catalog (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        condition_id TEXT UNIQUE,
        title TEXT,
        sport TEXT,
        league TEXT,
        home_team TEXT,
        away_team TEXT,
        yes_token_id TEXT,
        no_token_id TEXT,
        mapping_confidence REAL,
        end_date TEXT,
        discovered_at TEXT
    )
    """,
    # CLV tracking
    """
    CREATE TABLE IF NOT EXISTS clv_records (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        trade_id TEXT,
        market_id TEXT,
        side TEXT,
        entry_price REAL,
        closing_price REAL,
        clv REAL,
        strategy TEXT,
        sport TEXT,
        recorded_at TEXT
    )
    """,
    # News dedup fingerprints
    """
    CREATE TABLE IF NOT EXISTS news_fingerprints (
        fingerprint TEXT PRIMARY KEY,
        headline TEXT,
        seen_at TEXT
    )
    """,
    # Strategy health (auto-disable sharp_follow etc.)
    """
    CREATE TABLE IF NOT EXISTS strategy_health (
        strategy TEXT PRIMARY KEY,
        enabled INTEGER DEFAULT 1,
        rolling_clv REAL DEFAULT 0,
        trade_count INTEGER DEFAULT 0,
        updated_at TEXT
    )
    """,
    # Anthropic API cost ledger (one row per call)
    """
    CREATE TABLE IF NOT EXISTS anthropic_costs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts TEXT NOT NULL,
        day_bucket TEXT NOT NULL,
        model TEXT,
        input_tokens INTEGER DEFAULT 0,
        output_tokens INTEGER DEFAULT 0,
        cost_usd REAL DEFAULT 0,
        market_id TEXT,
        ok INTEGER DEFAULT 1
    )
    """,
]


class Database:
    def __init__(self, path: str = "apex.db") -> None:
        self.path = path
        self._conn: aiosqlite.Connection | None = None
        self._connect_lock = asyncio.Lock()
        self._last_error: str = ""
        self._healthy: bool = False

    async def connect(
        self,
        attempts: int = 5,
        base_delay: float = 1.0,
        max_delay: float = 30.0,
    ) -> None:
        """Open the connection with exponential backoff.

        Raises the final exception if every attempt fails; callers are expected
        to catch and put the DB-dependent jobs in degraded mode.
        """
        async with self._connect_lock:
            if self._conn is not None:
                return
            last_exc: Exception | None = None
            for i in range(attempts):
                try:
                    conn = await aiosqlite.connect(self.path)
                    conn.row_factory = aiosqlite.Row
                    await conn.execute("PRAGMA journal_mode=WAL")
                    await conn.execute("PRAGMA foreign_keys=ON")
                    # busy_timeout helps during Railway Postgres-style restarts
                    # (sqlite rarely hits this but 5s is cheap insurance).
                    await conn.execute("PRAGMA busy_timeout=5000")
                    self._conn = conn
                    self._healthy = True
                    self._last_error = ""
                    await self.init_schema()
                    logger.info(
                        "db: connected (%s) on attempt %d/%d",
                        self.path, i + 1, attempts,
                    )
                    return
                except Exception as exc:  # noqa: BLE001
                    last_exc = exc
                    self._last_error = str(exc)
                    self._healthy = False
                    if i == attempts - 1:
                        break
                    delay = min(base_delay * (2**i), max_delay)
                    logger.warning(
                        "db: connect attempt %d/%d failed: %s (sleep %.1fs)",
                        i + 1, attempts, exc, delay,
                    )
                    await asyncio.sleep(delay)
            assert last_exc is not None
            logger.error("db: connect failed after %d attempts: %s", attempts, last_exc)
            raise last_exc

    async def close(self) -> None:
        if self._conn is not None:
            try:
                await self._conn.close()
            except Exception as exc:  # noqa: BLE001
                logger.warning("db: close error: %s", exc)
            self._conn = None
        self._healthy = False

    async def ensure_connected(self) -> bool:
        """Re-open the connection if it was dropped. Returns True if usable."""
        if self._conn is not None and self._healthy:
            return True
        try:
            await self.connect()
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning("db: ensure_connected failed: %s", exc)
            return False

    async def is_healthy(self) -> bool:
        """Cheap liveness probe — SELECT 1. Marks the DB unhealthy on failure."""
        if self._conn is None:
            self._healthy = False
            return False
        try:
            async with self._conn.execute("SELECT 1") as cur:
                await cur.fetchone()
            self._healthy = True
            return True
        except Exception as exc:  # noqa: BLE001
            self._healthy = False
            self._last_error = str(exc)
            logger.warning("db: health probe failed: %s", exc)
            # Drop the broken handle so the next ensure_connected() re-opens it.
            try:
                await self._conn.close()
            except Exception:  # noqa: BLE001
                pass
            self._conn = None
            return False

    @property
    def healthy(self) -> bool:
        """Last-known health state (set by connect/is_healthy). No I/O."""
        return self._healthy and self._conn is not None

    @property
    def last_error(self) -> str:
        return self._last_error

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("Database not connected")
        return self._conn

    async def init_schema(self) -> None:
        for stmt in SCHEMA_STATEMENTS:
            await self.conn.execute(stmt)
        await self.conn.commit()

    # --- Trades ---

    async def insert_trade(self, t: dict[str, Any]) -> None:
        await self.conn.execute(
            """
            INSERT OR REPLACE INTO trades
            (id, signal_id, market_id, event_id, strategy, side, size_usd, entry_price,
             filled_qty, filled_price, status, pnl, closing_price, clv, dry_run,
             created_at, updated_at, resolved_at)
            VALUES (:id, :signal_id, :market_id, :event_id, :strategy, :side, :size_usd,
                    :entry_price, :filled_qty, :filled_price, :status, :pnl, :closing_price,
                    :clv, :dry_run, :created_at, :updated_at, :resolved_at)
            """,
            t,
        )
        await self.conn.commit()

    async def update_trade(self, trade_id: str, **fields: Any) -> None:
        if not fields:
            return
        fields["updated_at"] = datetime.now(UTC).isoformat()
        sets = ", ".join(f"{k} = :{k}" for k in fields)
        fields["id"] = trade_id
        await self.conn.execute(f"UPDATE trades SET {sets} WHERE id = :id", fields)
        await self.conn.commit()

    async def get_open_trades(self) -> list[dict[str, Any]]:
        async with self.conn.execute(
            "SELECT * FROM trades WHERE status IN ('open', 'partial')"
        ) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]

    async def list_trades(self, limit: int = 100) -> list[dict[str, Any]]:
        async with self.conn.execute(
            "SELECT * FROM trades ORDER BY created_at DESC LIMIT ?", (limit,)
        ) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]

    # --- Bankroll ---

    async def record_bankroll(self, bankroll: float, unrealized_pnl: float = 0.0) -> None:
        await self.conn.execute(
            "INSERT INTO bankroll_snapshots (bankroll, unrealized_pnl, ts) VALUES (?, ?, ?)",
            (bankroll, unrealized_pnl, datetime.now(UTC).isoformat()),
        )
        await self.conn.commit()

    async def recent_bankroll(self, n: int = 7) -> list[dict[str, Any]]:
        async with self.conn.execute(
            "SELECT * FROM bankroll_snapshots ORDER BY ts DESC LIMIT ?", (n,)
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]

    # --- Elo ---

    async def upsert_elo(self, sport: str, team: str, elo: float, league: str = "") -> None:
        await self.conn.execute(
            """
            INSERT INTO elo_ratings (sport, league, team, elo, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(sport, team) DO UPDATE SET elo = excluded.elo, updated_at = excluded.updated_at
            """,
            (sport, league, team, elo, datetime.now(UTC).isoformat()),
        )
        await self.conn.commit()

    async def load_elo(self, sport: str) -> dict[str, float]:
        async with self.conn.execute(
            "SELECT team, elo FROM elo_ratings WHERE sport = ?", (sport,)
        ) as cur:
            return {row["team"]: row["elo"] for row in await cur.fetchall()}

    # --- Game results ---

    async def record_result(self, result: dict[str, Any]) -> None:
        await self.conn.execute(
            """
            INSERT OR REPLACE INTO game_results
            (event_id, sport, league, home_team, away_team, home_score, away_score, winner, completed_at)
            VALUES (:event_id, :sport, :league, :home_team, :away_team, :home_score, :away_score,
                    :winner, :completed_at)
            """,
            result,
        )
        await self.conn.commit()

    async def get_result(self, event_id: str) -> dict[str, Any] | None:
        async with self.conn.execute(
            "SELECT * FROM game_results WHERE event_id = ?", (event_id,)
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None

    # --- Odds snapshots ---

    async def record_odds(self, snap: dict[str, Any]) -> None:
        await self.conn.execute(
            """
            INSERT INTO odds_snapshots
            (event_id, source, home_odds, away_odds, home_implied_prob, away_implied_prob, fetched_at)
            VALUES (:event_id, :source, :home_odds, :away_odds, :home_implied_prob,
                    :away_implied_prob, :fetched_at)
            """,
            snap,
        )
        await self.conn.commit()

    # --- Forecasts / calibration ---

    async def record_forecast(self, f: dict[str, Any]) -> int:
        cur = await self.conn.execute(
            """
            INSERT INTO forecasts
            (event_id, market_id, model_name, sport, predicted_prob, market_price, edge,
             confidence, actual_outcome, brier_score, created_at, resolved_at)
            VALUES (:event_id, :market_id, :model_name, :sport, :predicted_prob, :market_price,
                    :edge, :confidence, :actual_outcome, :brier_score, :created_at, :resolved_at)
            """,
            f,
        )
        await self.conn.commit()
        return cur.lastrowid or 0

    async def update_forecast_outcome(self, forecast_id: int, outcome: int, brier: float) -> None:
        await self.conn.execute(
            "UPDATE forecasts SET actual_outcome = ?, brier_score = ?, resolved_at = ? WHERE id = ?",
            (outcome, brier, datetime.now(UTC).isoformat(), forecast_id),
        )
        await self.conn.commit()

    async def unresolved_forecasts(self, model_name: str | None = None) -> list[dict[str, Any]]:
        sql = "SELECT * FROM forecasts WHERE actual_outcome IS NULL"
        params: tuple = ()
        if model_name:
            sql += " AND model_name = ?"
            params = (model_name,)
        async with self.conn.execute(sql, params) as cur:
            return [dict(r) for r in await cur.fetchall()]

    async def resolved_forecasts(
        self, model_name: str | None = None, sport: str | None = None, limit: int = 500
    ) -> list[dict[str, Any]]:
        sql = "SELECT * FROM forecasts WHERE actual_outcome IS NOT NULL"
        params: list[Any] = []
        if model_name:
            sql += " AND model_name = ?"
            params.append(model_name)
        if sport:
            sql += " AND sport = ?"
            params.append(sport)
        sql += " ORDER BY resolved_at DESC LIMIT ?"
        params.append(limit)
        async with self.conn.execute(sql, tuple(params)) as cur:
            return [dict(r) for r in await cur.fetchall()]

    async def upsert_calibration_bucket(
        self, model_name: str, sport: str, bucket: int, predicted_count: int, actual_wins: int
    ) -> None:
        await self.conn.execute(
            """
            INSERT INTO calibration_state
            (model_name, sport, bucket, predicted_count, actual_wins, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(model_name, sport, bucket) DO UPDATE SET
              predicted_count = excluded.predicted_count,
              actual_wins = excluded.actual_wins,
              updated_at = excluded.updated_at
            """,
            (
                model_name,
                sport,
                bucket,
                predicted_count,
                actual_wins,
                datetime.now(UTC).isoformat(),
            ),
        )
        await self.conn.commit()

    async def get_calibration_buckets(self, model_name: str, sport: str = "ALL") -> list[dict[str, Any]]:
        async with self.conn.execute(
            "SELECT * FROM calibration_state WHERE model_name = ? AND sport = ? ORDER BY bucket",
            (model_name, sport),
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]

    # --- Market catalog ---

    async def upsert_market(self, m: dict[str, Any]) -> None:
        await self.conn.execute(
            """
            INSERT INTO market_catalog
            (condition_id, title, sport, league, home_team, away_team, yes_token_id,
             no_token_id, mapping_confidence, end_date, discovered_at)
            VALUES (:condition_id, :title, :sport, :league, :home_team, :away_team,
                    :yes_token_id, :no_token_id, :mapping_confidence, :end_date, :discovered_at)
            ON CONFLICT(condition_id) DO UPDATE SET
              title = excluded.title,
              sport = excluded.sport,
              home_team = excluded.home_team,
              away_team = excluded.away_team,
              mapping_confidence = excluded.mapping_confidence,
              end_date = excluded.end_date
            """,
            m,
        )
        await self.conn.commit()

    # --- CLV ---

    async def record_clv(self, record: dict[str, Any]) -> None:
        await self.conn.execute(
            """
            INSERT INTO clv_records
            (trade_id, market_id, side, entry_price, closing_price, clv, strategy, sport, recorded_at)
            VALUES (:trade_id, :market_id, :side, :entry_price, :closing_price, :clv,
                    :strategy, :sport, :recorded_at)
            """,
            record,
        )
        await self.conn.commit()

    async def list_clv(self, strategy: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        if strategy:
            sql = "SELECT * FROM clv_records WHERE strategy = ? ORDER BY recorded_at DESC LIMIT ?"
            params: tuple = (strategy, limit)
        else:
            sql = "SELECT * FROM clv_records ORDER BY recorded_at DESC LIMIT ?"
            params = (limit,)
        async with self.conn.execute(sql, params) as cur:
            return [dict(r) for r in await cur.fetchall()]

    # --- News dedup ---

    async def is_news_seen(self, fingerprint: str) -> bool:
        async with self.conn.execute(
            "SELECT 1 FROM news_fingerprints WHERE fingerprint = ?", (fingerprint,)
        ) as cur:
            return await cur.fetchone() is not None

    async def mark_news_seen(self, fingerprint: str, headline: str) -> None:
        await self.conn.execute(
            "INSERT OR IGNORE INTO news_fingerprints (fingerprint, headline, seen_at) VALUES (?, ?, ?)",
            (fingerprint, headline, datetime.now(UTC).isoformat()),
        )
        await self.conn.commit()

    # --- Strategy health ---

    async def update_strategy_health(
        self, strategy: str, rolling_clv: float, trade_count: int, enabled: bool = True
    ) -> None:
        await self.conn.execute(
            """
            INSERT INTO strategy_health (strategy, enabled, rolling_clv, trade_count, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(strategy) DO UPDATE SET
              enabled = excluded.enabled,
              rolling_clv = excluded.rolling_clv,
              trade_count = excluded.trade_count,
              updated_at = excluded.updated_at
            """,
            (
                strategy,
                1 if enabled else 0,
                rolling_clv,
                trade_count,
                datetime.now(UTC).isoformat(),
            ),
        )
        await self.conn.commit()

    async def get_strategy_health(self, strategy: str) -> dict[str, Any] | None:
        async with self.conn.execute(
            "SELECT * FROM strategy_health WHERE strategy = ?", (strategy,)
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None

    # --- Anthropic cost ledger ---

    async def record_anthropic_cost(self, row: dict[str, Any]) -> None:
        await self.conn.execute(
            """
            INSERT INTO anthropic_costs
            (ts, day_bucket, model, input_tokens, output_tokens, cost_usd, market_id, ok)
            VALUES (:ts, :day_bucket, :model, :input_tokens, :output_tokens, :cost_usd,
                    :market_id, :ok)
            """,
            row,
        )
        await self.conn.commit()

    async def anthropic_cost_for_day(self, day_bucket: str) -> float:
        async with self.conn.execute(
            "SELECT COALESCE(SUM(cost_usd), 0) AS total FROM anthropic_costs WHERE day_bucket = ?",
            (day_bucket,),
        ) as cur:
            row = await cur.fetchone()
            return float(row["total"]) if row else 0.0

    async def anthropic_cost_last_n_days(self, n: int = 7) -> list[dict[str, Any]]:
        async with self.conn.execute(
            """
            SELECT day_bucket, COUNT(*) AS calls,
                   SUM(input_tokens) AS in_tok, SUM(output_tokens) AS out_tok,
                   SUM(cost_usd) AS cost
            FROM anthropic_costs
            GROUP BY day_bucket
            ORDER BY day_bucket DESC
            LIMIT ?
            """,
            (n,),
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]
