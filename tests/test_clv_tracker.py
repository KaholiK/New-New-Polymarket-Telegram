"""Tests for CLV tracker."""

from __future__ import annotations

import pytest

from apex.core.models import Side
from apex.execution.clv_tracker import CLVTracker


@pytest.mark.asyncio
async def test_record_yes_positive_clv():
    t = CLVTracker()
    # Entered at 0.48, market closed higher at 0.55 → positive CLV
    r = await t.record(
        trade_id="t1", market_id="m1", side=Side.YES,
        entry_price=0.48, closing_price=0.55, strategy="fair_value",
    )
    assert r.clv == pytest.approx(0.07, abs=1e-6)


@pytest.mark.asyncio
async def test_record_no_positive_clv():
    t = CLVTracker()
    # NO at 0.52, closing 0.40 → we got better than close, CLV = 0.52 - 0.40 = 0.12
    r = await t.record(
        trade_id="t1", market_id="m1", side=Side.NO,
        entry_price=0.52, closing_price=0.40, strategy="fair_value",
    )
    assert r.clv == pytest.approx(0.12, abs=1e-6)


@pytest.mark.asyncio
async def test_rolling_clv_by_strategy():
    t = CLVTracker()
    for i in range(5):
        await t.record(
            trade_id=f"t{i}", market_id=f"m{i}", side=Side.YES,
            entry_price=0.45, closing_price=0.50 + i * 0.01, strategy="fair_value",
        )
    roll = t.rolling_clv(strategy="fair_value", n=5)
    assert roll > 0


@pytest.mark.asyncio
async def test_rolling_clv_empty():
    t = CLVTracker()
    assert t.rolling_clv() == 0.0


@pytest.mark.asyncio
async def test_count_per_strategy():
    t = CLVTracker()
    await t.record("t1", "m1", Side.YES, 0.5, 0.6, strategy="a")
    await t.record("t2", "m2", Side.YES, 0.5, 0.6, strategy="b")
    assert t.count("a") == 1
    assert t.count("b") == 1


@pytest.mark.asyncio
async def test_summary_keys():
    t = CLVTracker()
    await t.record("t1", "m1", Side.YES, 0.45, 0.55, strategy="a")
    s = t.summary()
    assert s["count"] == 1
    assert s["avg_clv"] > 0
    assert "positive_rate" in s


@pytest.mark.asyncio
async def test_db_roundtrip(temp_db):
    t = CLVTracker(db=temp_db)
    await t.record("t1", "m1", Side.YES, 0.45, 0.55, strategy="fair_value", sport="NBA")
    rows = await temp_db.list_clv(strategy="fair_value")
    assert len(rows) == 1
    assert rows[0]["clv"] == pytest.approx(0.10, abs=1e-6)
