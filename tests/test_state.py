"""Tests for BotState: bankroll, positions, kill flag, mode."""

from __future__ import annotations

import pytest

from apex.core.models import Position, Side
from apex.core.state import BotState


@pytest.mark.asyncio
async def test_debit_reduces_bankroll():
    s = BotState(starting_bankroll=20.0)
    ok = await s.debit(5.0, reason="test")
    assert ok
    assert s.bankroll == pytest.approx(15.0)


@pytest.mark.asyncio
async def test_debit_overdraft_triggers_kill():
    s = BotState(starting_bankroll=20.0)
    ok = await s.debit(25.0, reason="test")
    assert ok is False
    assert s.killed is True
    assert "overdraft" in s.kill_reason


@pytest.mark.asyncio
async def test_debit_negative_rejected():
    s = BotState(starting_bankroll=20.0)
    ok = await s.debit(-5.0)
    assert ok is False
    assert s.bankroll == 20.0


@pytest.mark.asyncio
async def test_credit_updates_peak():
    s = BotState(starting_bankroll=20.0)
    await s.credit(10.0, reason="win")
    assert s.bankroll == pytest.approx(30.0)
    assert s.peak_bankroll == pytest.approx(30.0)


@pytest.mark.asyncio
async def test_position_lifecycle():
    s = BotState()
    pos = Position(
        market_id="m1",
        token_id="t1",
        side=Side.YES,
        contracts=10.0,
        avg_entry_price=0.48,
        cost_basis_usd=4.80,
    )
    await s.upsert_position(pos)
    got = await s.get_position("m1", Side.YES)
    assert got is not None
    assert got.contracts == 10.0
    removed = await s.remove_position("m1", Side.YES)
    assert removed is not None
    assert await s.get_position("m1", Side.YES) is None


@pytest.mark.asyncio
async def test_kill_pause_resume():
    s = BotState()
    assert s.is_trading_allowed
    await s.pause("manual")
    assert not s.is_trading_allowed
    await s.resume()
    assert s.is_trading_allowed
    await s.kill("critical error")
    assert not s.is_trading_allowed


@pytest.mark.asyncio
async def test_drawdown_from_peak():
    s = BotState(starting_bankroll=100.0)
    await s.credit(50.0)  # 150 peak
    await s.debit(30.0)  # bankroll 120
    assert s.drawdown_from_peak == pytest.approx(0.2, abs=1e-3)


@pytest.mark.asyncio
async def test_consecutive_losses_reset_on_win():
    s = BotState()
    await s.apply_realized_pnl(-1.0, won=False)
    await s.apply_realized_pnl(-1.0, won=False)
    assert s.consecutive_losses == 2
    await s.apply_realized_pnl(1.0, won=True)
    assert s.consecutive_losses == 0
    assert s.total_wins == 1
    assert s.total_losses == 2


def test_snapshot_keys():
    s = BotState()
    snap = s.snapshot()
    for key in ("bankroll", "killed", "paused", "wins", "losses"):
        assert key in snap
