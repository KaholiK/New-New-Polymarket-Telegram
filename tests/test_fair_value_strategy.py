"""Tests for fair value strategy."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from apex.core.models import (
    Confidence,
    Forecast,
    Market,
    MarketType,
    Side,
    Sport,
)
from apex.strategies.base import DataContext
from apex.strategies.fair_value import FairValueStrategy


def _market() -> Market:
    return Market(
        condition_id="c1",
        question="Lakers vs Celtics",
        sport=Sport.NBA,
        market_type=MarketType.MONEYLINE,
        home_team="Lakers",
        away_team="Celtics",
        yes_token_id="y",
        no_token_id="n",
        yes_price=0.48,
        no_price=0.52,
        volume=50000,
        liquidity=1000,
        end_date=datetime.now(UTC) + timedelta(hours=4),
    )


def _forecast(edge_z: float = 2.0, conf=Confidence.MEDIUM, raw_edge: float = 0.05) -> Forecast:
    return Forecast(
        event_id="e1",
        market_id="c1",
        sport=Sport.NBA,
        market_type=MarketType.MONEYLINE,
        home_team="Lakers",
        away_team="Celtics",
        side=Side.YES,
        ensemble_prob=0.53,
        ensemble_std=0.03,
        confidence=conf,
        market_price=0.48,
        market_implied_prob=0.48,
        raw_edge=raw_edge,
        edge_zscore=edge_z,
        edge_after_costs=raw_edge - 0.02,
        kelly_fraction=0.05,
        key_factors=["Elo edge"],
    )


@pytest.mark.asyncio
async def test_generates_signal_when_strong_edge():
    strat = FairValueStrategy()
    ctx = DataContext(
        forecast=_forecast(),
        source_ages={"polymarket": 30, "odds": 60},
    )
    sig = await strat.signal(_market(), ctx)
    assert sig is not None
    assert sig.side == Side.YES


@pytest.mark.asyncio
async def test_rejects_below_z_threshold():
    strat = FairValueStrategy()
    ctx = DataContext(
        forecast=_forecast(edge_z=0.5),
        source_ages={"polymarket": 30, "odds": 60},
    )
    sig = await strat.signal(_market(), ctx)
    assert sig is None


@pytest.mark.asyncio
async def test_rejects_no_opinion():
    strat = FairValueStrategy()
    ctx = DataContext(
        forecast=_forecast(conf=Confidence.NO_OPINION),
        source_ages={"polymarket": 30, "odds": 60},
    )
    sig = await strat.signal(_market(), ctx)
    assert sig is None


@pytest.mark.asyncio
async def test_rejects_stale_data():
    strat = FairValueStrategy()
    ctx = DataContext(
        forecast=_forecast(),
        source_ages={"polymarket": 10000, "odds": 60},  # stale polymarket
    )
    sig = await strat.signal(_market(), ctx)
    assert sig is None


@pytest.mark.asyncio
async def test_rejects_missing_forecast():
    strat = FairValueStrategy()
    ctx = DataContext(forecast=None)
    sig = await strat.signal(_market(), ctx)
    assert sig is None


@pytest.mark.asyncio
async def test_rejects_missing_source_in_freshness():
    strat = FairValueStrategy()
    ctx = DataContext(
        forecast=_forecast(),
        source_ages={"polymarket": 30},  # odds missing
    )
    sig = await strat.signal(_market(), ctx)
    assert sig is None


@pytest.mark.asyncio
async def test_rejects_edge_after_costs_tiny():
    strat = FairValueStrategy()
    ctx = DataContext(
        forecast=_forecast(raw_edge=0.025),
        source_ages={"polymarket": 30, "odds": 60},
    )
    sig = await strat.signal(_market(), ctx)
    # edge_after_costs = 0.025 - 0.02 = 0.005, below MIN_EDGE_AFTER_COSTS
    assert sig is None
