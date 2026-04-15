"""Tests for resolution monitor."""

from __future__ import annotations

import pytest

from apex.core.models import Side, Trade, TradeStatus
from apex.core.state import BotState
from apex.execution.resolution_monitor import ResolutionMonitor, parse_resolution


class _FakeClient:
    def __init__(self, data_by_id: dict[str, dict]) -> None:
        self._data = data_by_id

    async def get_market(self, market_id: str):
        return self._data.get(market_id)


def test_parse_yes_win():
    raw = {"conditionId": "m1", "closed": True, "outcomePrices": '["1.00", "0.00"]'}
    out = parse_resolution(raw)
    assert out is not None
    assert out.resolution == "YES"


def test_parse_no_win():
    raw = {"conditionId": "m1", "closed": True, "outcomePrices": '["0.00", "1.00"]'}
    out = parse_resolution(raw)
    assert out is not None
    assert out.resolution == "NO"


def test_parse_invalid():
    raw = {"conditionId": "m1", "closed": True, "outcomePrices": '["0.50", "0.50"]'}
    out = parse_resolution(raw)
    assert out is not None
    assert out.resolution == "INVALID"


def test_parse_unresolved():
    raw = {"conditionId": "m1", "closed": True, "outcomePrices": '["0.60", "0.40"]'}
    # Not >0.95 → not resolved
    assert parse_resolution(raw) is None


def test_parse_not_closed():
    raw = {"conditionId": "m1", "closed": False, "outcomePrices": '["1.00", "0.00"]'}
    assert parse_resolution(raw) is None


def test_parse_missing_condition_id():
    raw = {"closed": True, "outcomePrices": '["1.00", "0.00"]'}
    assert parse_resolution(raw) is None


def test_parse_bad_prices():
    raw = {"conditionId": "m1", "closed": True, "outcomePrices": "not json"}
    assert parse_resolution(raw) is None


@pytest.mark.asyncio
async def test_settle_yes_win_increases_bankroll(temp_db):
    state = BotState(starting_bankroll=20.0)
    # Entry: bought 10 YES contracts at 0.48, paid $4.80
    trade = Trade(
        id="t1",
        market_id="m1",
        event_id="e1",
        side=Side.YES,
        size_usd=4.80,
        entry_price=0.48,
        filled_qty=10.0,
        filled_price=0.48,
        status=TradeStatus.OPEN,
    )
    # Insert into DB so update_trade works
    now = "2026-04-15T22:00:00+00:00"
    await temp_db.insert_trade(
        {**trade.model_dump(), "created_at": now, "updated_at": now, "resolved_at": None, "dry_run": 1, "strategy": "", "signal_id": "", "filled_qty": 10.0}
    )
    fake = _FakeClient({"m1": {"conditionId": "m1", "closed": True, "outcomePrices": '["1.00","0.00"]'}})
    mon = ResolutionMonitor(fake, temp_db, state)  # type: ignore[arg-type]
    results = await mon.check_and_settle([trade])
    assert len(results) == 1
    # 10 winning contracts → $10 payout → P&L = 10 - 4.80 = 5.20
    assert trade.status == TradeStatus.RESOLVED_WIN
    assert abs(trade.pnl - 5.20) < 1e-3


@pytest.mark.asyncio
async def test_settle_loss_bankroll_unchanged(temp_db):
    state = BotState(starting_bankroll=20.0)
    trade = Trade(
        id="t2",
        market_id="m2",
        side=Side.YES,
        size_usd=4.80,
        entry_price=0.48,
        filled_qty=10.0,
    )
    now = "2026-04-15T22:00:00+00:00"
    await temp_db.insert_trade(
        {**trade.model_dump(), "created_at": now, "updated_at": now, "resolved_at": None, "dry_run": 1, "strategy": "", "signal_id": "", "event_id": ""}
    )
    fake = _FakeClient({"m2": {"conditionId": "m2", "closed": True, "outcomePrices": '["0.00","1.00"]'}})
    mon = ResolutionMonitor(fake, temp_db, state)  # type: ignore[arg-type]
    await mon.check_and_settle([trade])
    assert trade.status == TradeStatus.RESOLVED_LOSS


@pytest.mark.asyncio
async def test_dedup_resolved(temp_db):
    state = BotState()
    trade = Trade(id="t1", market_id="m1", side=Side.YES, size_usd=1.0, entry_price=0.5, filled_qty=1.0)
    now = "2026-04-15T22:00:00+00:00"
    await temp_db.insert_trade(
        {**trade.model_dump(), "created_at": now, "updated_at": now, "resolved_at": None, "dry_run": 1, "strategy": "", "signal_id": "", "event_id": ""}
    )
    fake = _FakeClient({"m1": {"conditionId": "m1", "closed": True, "outcomePrices": '["1.00","0.00"]'}})
    mon = ResolutionMonitor(fake, temp_db, state)  # type: ignore[arg-type]
    r1 = await mon.check_and_settle([trade])
    # Second call should dedup
    r2 = await mon.check_and_settle([trade])
    assert len(r1) == 1
    assert len(r2) == 0
