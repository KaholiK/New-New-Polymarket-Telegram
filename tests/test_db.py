"""Tests for SQLite storage layer."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest


@pytest.mark.asyncio
async def test_schema_created(temp_db):
    async with temp_db.conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ) as cur:
        tables = {r["name"] for r in await cur.fetchall()}
    assert "trades" in tables
    assert "elo_ratings" in tables
    assert "game_results" in tables
    assert "forecasts" in tables


@pytest.mark.asyncio
async def test_insert_and_fetch_trade(temp_db):
    now = datetime.now(UTC).isoformat()
    await temp_db.insert_trade(
        {
            "id": "trade_1",
            "signal_id": "sig_1",
            "market_id": "mkt_1",
            "event_id": "evt_1",
            "strategy": "fair_value",
            "side": "YES",
            "size_usd": 1.0,
            "entry_price": 0.48,
            "filled_qty": 0.0,
            "filled_price": 0.0,
            "status": "open",
            "pnl": 0.0,
            "closing_price": None,
            "clv": None,
            "dry_run": 1,
            "created_at": now,
            "updated_at": now,
            "resolved_at": None,
        }
    )
    trades = await temp_db.get_open_trades()
    assert len(trades) == 1
    assert trades[0]["id"] == "trade_1"


@pytest.mark.asyncio
async def test_upsert_elo_and_load(temp_db):
    await temp_db.upsert_elo("NBA", "Lakers", 1550.0)
    await temp_db.upsert_elo("NBA", "Celtics", 1520.0)
    await temp_db.upsert_elo("NBA", "Lakers", 1560.0)  # update
    elos = await temp_db.load_elo("NBA")
    assert elos["Lakers"] == 1560.0
    assert elos["Celtics"] == 1520.0


@pytest.mark.asyncio
async def test_record_result(temp_db):
    now = datetime.now(UTC).isoformat()
    await temp_db.record_result(
        {
            "event_id": "e1",
            "sport": "NBA",
            "league": "NBA",
            "home_team": "Lakers",
            "away_team": "Celtics",
            "home_score": 110,
            "away_score": 108,
            "winner": "Lakers",
            "completed_at": now,
        }
    )
    r = await temp_db.get_result("e1")
    assert r is not None
    assert r["winner"] == "Lakers"


@pytest.mark.asyncio
async def test_record_bankroll(temp_db):
    await temp_db.record_bankroll(20.0, 0.0)
    await temp_db.record_bankroll(21.5, 1.5)
    rows = await temp_db.recent_bankroll(n=2)
    assert len(rows) == 2


@pytest.mark.asyncio
async def test_calibration_roundtrip(temp_db):
    await temp_db.upsert_calibration_bucket("elo", "NBA", 5, 10, 6)
    await temp_db.upsert_calibration_bucket("elo", "NBA", 5, 20, 12)  # update
    buckets = await temp_db.get_calibration_buckets("elo", "NBA")
    assert len(buckets) == 1
    assert buckets[0]["predicted_count"] == 20


@pytest.mark.asyncio
async def test_news_dedup(temp_db):
    assert not await temp_db.is_news_seen("hash1")
    await temp_db.mark_news_seen("hash1", "Lakers sign MVP")
    assert await temp_db.is_news_seen("hash1")


@pytest.mark.asyncio
async def test_strategy_health_roundtrip(temp_db):
    await temp_db.update_strategy_health("sharp_follow", rolling_clv=0.5, trade_count=10)
    h = await temp_db.get_strategy_health("sharp_follow")
    assert h is not None
    assert h["rolling_clv"] == 0.5
