"""User-scoped persistent features: price alerts, portfolio, watchlist.

All tables are namespaced by ``user_id`` (the Telegram user ID) so multiple
authorized users can maintain independent alerts/portfolios. Schema is created
lazily via ``ensure_schema()`` once the DB connection is healthy.

Tables
------
* ``price_alerts``   — pending / triggered user price alerts
* ``user_portfolio`` — hypothetical coin holdings (virtual)
* ``user_watchlist`` — per-user watchlist of tickers

All queries are gated on ``db._conn`` being available; DB-down callers should
skip gracefully (see ``ApexEngine.check_price_alerts``).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from apex.utils.logger import get_logger

if TYPE_CHECKING:
    from apex.core.crypto_state import CryptoState
    from apex.storage.db import Database

logger = get_logger(__name__)

MAX_ALERTS_PER_USER = 10


SCHEMA_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS price_alerts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        coin TEXT NOT NULL,
        direction TEXT NOT NULL,
        target_price REAL NOT NULL,
        active INTEGER DEFAULT 1,
        triggered_at TEXT,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_price_alerts_user_active
    ON price_alerts(user_id, active)
    """,
    """
    CREATE TABLE IF NOT EXISTS user_portfolio (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        coin TEXT NOT NULL,
        amount REAL NOT NULL,
        entry_price REAL NOT NULL,
        created_at TEXT NOT NULL,
        UNIQUE(user_id, coin)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS user_watchlist (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        coin TEXT NOT NULL,
        created_at TEXT NOT NULL,
        UNIQUE(user_id, coin)
    )
    """,
]


class UserFeatures:
    def __init__(self, db: Database) -> None:
        self.db = db
        self._schema_ready = False

    async def ensure_schema(self) -> None:
        if self._schema_ready:
            return
        if self.db is None or not getattr(self.db, "healthy", False):
            return
        for stmt in SCHEMA_STATEMENTS:
            await self.db.conn.execute(stmt)
        await self.db.conn.commit()
        self._schema_ready = True

    def _require_db(self) -> bool:
        if self.db is None or not getattr(self.db, "healthy", False):
            return False
        return True

    # ------------------------------------------------------------ #
    # Alerts                                                        #
    # ------------------------------------------------------------ #

    async def add_alert(
        self, user_id: int, coin: str, direction: str, target_price: float
    ) -> tuple[bool, str]:
        if not self._require_db():
            return False, "Database unavailable."
        await self.ensure_schema()
        direction = direction.lower().strip()
        if direction not in ("above", "below"):
            return False, "Direction must be 'above' or 'below'."
        if target_price <= 0:
            return False, "Target price must be positive."
        async with self.db.conn.execute(
            "SELECT COUNT(*) AS n FROM price_alerts WHERE user_id = ? AND active = 1",
            (user_id,),
        ) as cur:
            row = await cur.fetchone()
            if row and row["n"] >= MAX_ALERTS_PER_USER:
                return False, f"Max {MAX_ALERTS_PER_USER} active alerts per user."
        await self.db.conn.execute(
            """
            INSERT INTO price_alerts
              (user_id, coin, direction, target_price, active, created_at)
            VALUES (?, ?, ?, ?, 1, ?)
            """,
            (user_id, coin.lower(), direction, float(target_price), datetime.now(UTC).isoformat()),
        )
        await self.db.conn.commit()
        return True, f"Alert set: {coin.upper()} {direction} ${target_price:,.2f}"

    async def list_alerts(self, user_id: int) -> list[dict[str, Any]]:
        if not self._require_db():
            return []
        await self.ensure_schema()
        async with self.db.conn.execute(
            """
            SELECT id, coin, direction, target_price, created_at
            FROM price_alerts
            WHERE user_id = ? AND active = 1
            ORDER BY id
            """,
            (user_id,),
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]

    async def clear_alerts(self, user_id: int) -> int:
        if not self._require_db():
            return 0
        await self.ensure_schema()
        cur = await self.db.conn.execute(
            "UPDATE price_alerts SET active = 0 WHERE user_id = ? AND active = 1",
            (user_id,),
        )
        await self.db.conn.commit()
        return cur.rowcount or 0

    async def check_alerts(self, crypto_state: CryptoState) -> list[dict[str, Any]]:
        """Scan all active alerts and fire any that have triggered.

        Returns a list of fired-alert dicts with at least
        ``user_id, coin, direction, target_price, current_price``.
        Each fired alert is marked inactive in the DB before being returned.
        """
        if not self._require_db():
            return []
        await self.ensure_schema()
        async with self.db.conn.execute(
            """
            SELECT id, user_id, coin, direction, target_price
            FROM price_alerts
            WHERE active = 1
            """,
        ) as cur:
            alerts = [dict(r) for r in await cur.fetchall()]
        fired: list[dict[str, Any]] = []
        for a in alerts:
            snap = crypto_state.get_price(a["coin"])
            if snap is None:
                continue
            price = snap.price_usd
            triggered = (
                (a["direction"] == "above" and price >= a["target_price"])
                or (a["direction"] == "below" and price <= a["target_price"])
            )
            if not triggered:
                continue
            # Deactivate atomically so we don't re-fire on the next tick.
            await self.db.conn.execute(
                "UPDATE price_alerts SET active = 0, triggered_at = ? WHERE id = ?",
                (datetime.now(UTC).isoformat(), a["id"]),
            )
            fired.append({
                **a,
                "current_price": price,
            })
        if fired:
            await self.db.conn.commit()
        return fired

    # ------------------------------------------------------------ #
    # Portfolio                                                     #
    # ------------------------------------------------------------ #

    async def upsert_holding(
        self, user_id: int, coin: str, amount: float, entry_price: float
    ) -> None:
        if not self._require_db():
            return
        await self.ensure_schema()
        await self.db.conn.execute(
            """
            INSERT INTO user_portfolio (user_id, coin, amount, entry_price, created_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(user_id, coin) DO UPDATE SET
              amount = excluded.amount,
              entry_price = excluded.entry_price,
              created_at = excluded.created_at
            """,
            (user_id, coin.lower(), float(amount), float(entry_price), datetime.now(UTC).isoformat()),
        )
        await self.db.conn.commit()

    async def remove_holding(self, user_id: int, coin: str) -> int:
        if not self._require_db():
            return 0
        await self.ensure_schema()
        cur = await self.db.conn.execute(
            "DELETE FROM user_portfolio WHERE user_id = ? AND coin = ?",
            (user_id, coin.lower()),
        )
        await self.db.conn.commit()
        return cur.rowcount or 0

    async def list_portfolio(self, user_id: int) -> list[dict[str, Any]]:
        if not self._require_db():
            return []
        await self.ensure_schema()
        async with self.db.conn.execute(
            """
            SELECT coin, amount, entry_price, created_at
            FROM user_portfolio
            WHERE user_id = ?
            ORDER BY coin
            """,
            (user_id,),
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]

    # ------------------------------------------------------------ #
    # Watchlist                                                     #
    # ------------------------------------------------------------ #

    async def watchlist_add(self, user_id: int, coin: str) -> bool:
        if not self._require_db():
            return False
        await self.ensure_schema()
        try:
            await self.db.conn.execute(
                "INSERT INTO user_watchlist (user_id, coin, created_at) VALUES (?, ?, ?)",
                (user_id, coin.lower(), datetime.now(UTC).isoformat()),
            )
            await self.db.conn.commit()
            return True
        except Exception as exc:  # noqa: BLE001
            # UNIQUE constraint → already in watchlist
            logger.debug("watchlist_add noop for %s %s: %s", user_id, coin, exc)
            return False

    async def watchlist_remove(self, user_id: int, coin: str) -> int:
        if not self._require_db():
            return 0
        await self.ensure_schema()
        cur = await self.db.conn.execute(
            "DELETE FROM user_watchlist WHERE user_id = ? AND coin = ?",
            (user_id, coin.lower()),
        )
        await self.db.conn.commit()
        return cur.rowcount or 0

    async def watchlist_list(self, user_id: int) -> list[str]:
        if not self._require_db():
            return []
        await self.ensure_schema()
        async with self.db.conn.execute(
            "SELECT coin FROM user_watchlist WHERE user_id = ? ORDER BY coin",
            (user_id,),
        ) as cur:
            return [r["coin"] for r in await cur.fetchall()]
