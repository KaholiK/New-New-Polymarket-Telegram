"""Alerts, portfolio, watchlist — DB-backed user features."""

from __future__ import annotations

import os
import tempfile
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio

from apex.core.crypto_state import CryptoState
from apex.core.user_features import UserFeatures
from apex.storage.db import Database


@pytest_asyncio.fixture
async def uf() -> AsyncIterator[UserFeatures]:
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        path = tmp.name
    db = Database(path=path)
    await db.connect()
    uf = UserFeatures(db)
    await uf.ensure_schema()
    try:
        yield uf
    finally:
        await db.close()
        os.remove(path)


@pytest.mark.asyncio
async def test_add_and_list_alert(uf: UserFeatures) -> None:
    ok, _ = await uf.add_alert(1, "btc", "above", 100_000)
    assert ok
    alerts = await uf.list_alerts(1)
    assert len(alerts) == 1
    assert alerts[0]["coin"] == "btc"
    assert alerts[0]["direction"] == "above"
    assert alerts[0]["target_price"] == 100_000


@pytest.mark.asyncio
async def test_alert_max_10(uf: UserFeatures) -> None:
    for i in range(10):
        ok, _ = await uf.add_alert(1, "btc", "above", 100_000 + i)
        assert ok
    # 11th rejected
    ok, msg = await uf.add_alert(1, "btc", "above", 200_000)
    assert ok is False
    assert "Max" in msg


@pytest.mark.asyncio
async def test_alert_bad_direction(uf: UserFeatures) -> None:
    ok, msg = await uf.add_alert(1, "btc", "sideways", 100_000)
    assert ok is False
    assert "above" in msg or "below" in msg


@pytest.mark.asyncio
async def test_check_alerts_fires_above(uf: UserFeatures) -> None:
    await uf.add_alert(1, "btc", "above", 50_000)
    await uf.add_alert(1, "btc", "below", 10_000)  # should not fire
    state = CryptoState()
    state.update_price("btc", {
        "asset": "bitcoin", "symbol": "btc",
        "price_usd": 51_000, "change_24h_pct": 1.0,
    })
    fired = await uf.check_alerts(state)
    assert len(fired) == 1
    assert fired[0]["direction"] == "above"
    # Fired alert is deactivated (no re-fire).
    again = await uf.check_alerts(state)
    assert again == []


@pytest.mark.asyncio
async def test_check_alerts_fires_below(uf: UserFeatures) -> None:
    await uf.add_alert(1, "eth", "below", 2_500)
    state = CryptoState()
    state.update_price("eth", {
        "asset": "ethereum", "symbol": "eth",
        "price_usd": 2_400, "change_24h_pct": -3.0,
    })
    fired = await uf.check_alerts(state)
    assert len(fired) == 1
    assert fired[0]["direction"] == "below"


@pytest.mark.asyncio
async def test_clear_alerts(uf: UserFeatures) -> None:
    await uf.add_alert(1, "btc", "above", 100_000)
    await uf.add_alert(1, "eth", "above", 5_000)
    n = await uf.clear_alerts(1)
    assert n == 2
    assert await uf.list_alerts(1) == []


@pytest.mark.asyncio
async def test_portfolio_crud(uf: UserFeatures) -> None:
    await uf.upsert_holding(1, "btc", 0.5, 40_000)
    await uf.upsert_holding(1, "eth", 5.0, 2_000)
    rows = await uf.list_portfolio(1)
    assert len(rows) == 2
    # Upsert same coin overwrites amount + entry.
    await uf.upsert_holding(1, "btc", 1.0, 50_000)
    rows = await uf.list_portfolio(1)
    btc = next(r for r in rows if r["coin"] == "btc")
    assert btc["amount"] == 1.0
    assert btc["entry_price"] == 50_000
    # Remove
    removed = await uf.remove_holding(1, "eth")
    assert removed == 1


@pytest.mark.asyncio
async def test_watchlist_crud(uf: UserFeatures) -> None:
    assert await uf.watchlist_add(1, "btc") is True
    assert await uf.watchlist_add(1, "btc") is False  # dup noop
    assert await uf.watchlist_add(1, "eth") is True
    coins = await uf.watchlist_list(1)
    assert set(coins) == {"btc", "eth"}
    removed = await uf.watchlist_remove(1, "btc")
    assert removed == 1
    assert set(await uf.watchlist_list(1)) == {"eth"}
