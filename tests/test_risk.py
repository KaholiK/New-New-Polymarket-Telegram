"""Tests for risk engine: Kelly, drawdown, exposure, kill switch."""

from __future__ import annotations

import pytest

from apex.core.models import Position, Side, Sport
from apex.core.state import BotState
from apex.risk.consecutive_loss_guard import check_and_pause
from apex.risk.drawdown import check_drawdowns
from apex.risk.exposure import check_exposure, event_exposure, sport_exposure
from apex.risk.kelly import kelly_size, shrunk_edge
from apex.risk.kill_switch import KillSwitch

# Kelly ---------------------------------------------------------------


def test_shrunk_edge_positive():
    assert shrunk_edge(0.05, 0.02) == pytest.approx(0.03, abs=1e-6)


def test_shrunk_edge_floor():
    assert shrunk_edge(0.01, 0.05) == 0.0


def test_kelly_size_positive():
    k_frac, k_usd = kelly_size(true_prob=0.55, yes_price=0.48, edge_std=0.02, bankroll=20.0)
    assert k_frac > 0
    assert k_usd > 0


def test_kelly_size_zero_for_no_edge():
    k_frac, _ = kelly_size(true_prob=0.45, yes_price=0.50, edge_std=0.0, bankroll=20.0)
    assert k_frac == 0.0


def test_kelly_size_zero_bankroll():
    k_frac, _ = kelly_size(0.55, 0.48, 0.02, 0.0)
    assert k_frac == 0.0


def test_kelly_size_invalid_price():
    k_frac, _ = kelly_size(0.55, 1.0, 0.02, 20.0)
    assert k_frac == 0.0


def test_kelly_small_bankroll_fraction():
    # Small bankroll should use 0.33 fraction (> standard 0.25)
    k_small, _ = kelly_size(0.55, 0.48, 0.0, bankroll=20.0)
    k_big, _ = kelly_size(0.55, 0.48, 0.0, bankroll=5000.0)
    # same underlying Kelly, fraction differs
    assert k_small / 0.33 == pytest.approx(k_big / 0.25, abs=1e-3)


# Drawdown ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_drawdown_daily_triggers():
    s = BotState(starting_bankroll=100.0)
    await s.debit(25.0)  # 25% daily drawdown
    status = check_drawdowns(s)
    assert status.daily_exceeded


@pytest.mark.asyncio
async def test_drawdown_rolling_triggers():
    s = BotState(starting_bankroll=100.0)
    await s.credit(50.0)  # peak 150
    await s.debit(60.0)  # bankroll 90, 40% from peak
    status = check_drawdowns(s)
    assert status.rolling_exceeded


def test_drawdown_clean_state():
    s = BotState(starting_bankroll=100.0)
    status = check_drawdowns(s)
    assert not status.daily_exceeded and not status.rolling_exceeded


# Exposure ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_sport_exposure_sums_positions():
    s = BotState(starting_bankroll=100.0)
    await s.upsert_position(Position(
        market_id="m1", token_id="t1", side=Side.YES,
        contracts=10, avg_entry_price=0.5, cost_basis_usd=5.0,
    ))
    await s.upsert_position(Position(
        market_id="m2", token_id="t2", side=Side.YES,
        contracts=20, avg_entry_price=0.4, cost_basis_usd=8.0,
    ))
    map_ = {"m1": Sport.NBA, "m2": Sport.NBA}
    assert sport_exposure(s, Sport.NBA, map_) == pytest.approx(13.0)


@pytest.mark.asyncio
async def test_event_exposure_sums_matching():
    s = BotState()
    await s.upsert_position(Position(
        market_id="m1", token_id="t1", side=Side.YES,
        contracts=1, avg_entry_price=0.5, cost_basis_usd=3.0,
    ))
    assert event_exposure(s, "e1", {"m1": "e1"}) == 3.0
    assert event_exposure(s, "e2", {"m1": "e1"}) == 0.0


@pytest.mark.asyncio
async def test_exposure_check_ok():
    s = BotState(starting_bankroll=100.0)
    ex = check_exposure(s, proposed_usd=1.0, sport=Sport.NBA, event_id="e1")
    assert ex.ok


@pytest.mark.asyncio
async def test_exposure_check_sport_cap_hit():
    s = BotState(starting_bankroll=10.0)
    await s.upsert_position(Position(
        market_id="m1", token_id="t1", side=Side.YES,
        contracts=1, avg_entry_price=0.5, cost_basis_usd=4.0,
    ))
    ex = check_exposure(
        s, proposed_usd=3.0, sport=Sport.NBA, event_id="e1",
        market_sport_map={"m1": Sport.NBA},
    )
    # Sport cap is 40% of $10 = $4. Already $4. Proposed $3 → exceeds.
    assert not ex.ok


# Kill switch ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_kill_switch_activates():
    s = BotState()
    k = KillSwitch(s)
    await k.trigger("test")
    assert k.is_active


@pytest.mark.asyncio
async def test_kill_switch_resume():
    s = BotState()
    k = KillSwitch(s)
    await k.trigger("test")
    await k.resume()
    assert not k.is_active


# Consecutive loss ---------------------------------------------------------


@pytest.mark.asyncio
async def test_consecutive_loss_pauses_after_limit():
    s = BotState()
    for _ in range(5):
        await s.apply_realized_pnl(-1.0, won=False)
    paused = await check_and_pause(s)
    assert paused
    assert s.paused


@pytest.mark.asyncio
async def test_consecutive_loss_below_limit():
    s = BotState()
    for _ in range(3):
        await s.apply_realized_pnl(-1.0, won=False)
    paused = await check_and_pause(s)
    assert not paused
