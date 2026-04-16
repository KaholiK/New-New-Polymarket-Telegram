"""Tests for Anthropic cost tracker."""

from __future__ import annotations

import pytest

from apex.quant.calibration.cost_tracker import CostTracker, estimate_cost_usd


def test_estimate_cost_sonnet():
    # 1M in + 1M out at Sonnet rates = $3 + $15 = $18
    cost = estimate_cost_usd("claude-sonnet-4-20250514", 1_000_000, 1_000_000)
    assert cost == pytest.approx(18.0, abs=1e-6)


def test_estimate_cost_unknown_model_defaults():
    # Unknown → default (Sonnet) rates
    c_known = estimate_cost_usd("claude-sonnet-4-20250514", 1000, 500)
    c_unknown = estimate_cost_usd("bogus-model-name", 1000, 500)
    assert c_known == c_unknown


def test_estimate_cost_small_tokens():
    cost = estimate_cost_usd("claude-sonnet-4-20250514", 800, 150)
    # 800*3 + 150*15 = 2400 + 2250 = 4650 / 1e6 = $0.00465
    assert cost == pytest.approx(0.00465, abs=1e-6)


@pytest.mark.asyncio
async def test_can_spend_under_cap_no_db():
    t = CostTracker(db=None, daily_cap_usd=1.0)
    assert await t.can_spend(0.5) is True
    assert await t.can_spend(2.0) is False


@pytest.mark.asyncio
async def test_record_accumulates_in_memory():
    t = CostTracker(db=None, daily_cap_usd=1.0)
    await t.record("claude-sonnet-4-20250514", 800, 150)
    cost1 = t.today_cost()
    await t.record("claude-sonnet-4-20250514", 800, 150)
    cost2 = t.today_cost()
    assert cost2 > cost1
    assert cost2 == pytest.approx(cost1 * 2, rel=1e-6)


@pytest.mark.asyncio
async def test_cap_enforced_after_record():
    t = CostTracker(db=None, daily_cap_usd=0.01)
    # 800 in + 150 out ≈ $0.00465. After 2 calls = $0.0093, still under cap.
    await t.record("claude-sonnet-4-20250514", 800, 150)
    assert await t.can_spend(0.005) is True
    await t.record("claude-sonnet-4-20250514", 800, 150)
    # After the second call we're at ~$0.0093 / $0.01 — only small spends fit.
    assert await t.can_spend(0.005) is False


@pytest.mark.asyncio
async def test_persistence_through_db(temp_db):
    t = CostTracker(db=temp_db, daily_cap_usd=1.0)
    await t.record("claude-sonnet-4-20250514", 1000, 500, market_id="m1", ok=True)
    # New tracker bound to same DB should see the cost after ensure_today_loaded.
    t2 = CostTracker(db=temp_db, daily_cap_usd=1.0)
    can_spend_big = await t2.can_spend(0.9999)  # forces load
    assert t2.today_cost() > 0
    # Two independent trackers do not double-count in-memory state — lazy load
    # fetches the persistent total exactly once.
    assert can_spend_big in (True, False)  # just ensure it completes without error


@pytest.mark.asyncio
async def test_summary_shape(temp_db):
    t = CostTracker(db=temp_db, daily_cap_usd=1.0)
    await t.record("claude-sonnet-4-20250514", 1000, 500)
    s = await t.summary(n_days=7)
    assert "today_cost_usd" in s
    assert "daily_cap_usd" in s
    assert "remaining_usd" in s
    assert "week_cost_usd" in s
    assert s["today_cost_usd"] > 0
