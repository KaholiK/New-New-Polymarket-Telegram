"""Tests for news shock strategy."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from apex.core.models import (
    Confidence,
    Forecast,
    Market,
    MarketType,
    NewsItem,
    Side,
    Sport,
)
from apex.strategies.base import DataContext
from apex.strategies.news_shock import NewsShockStrategy


def _forecast() -> Forecast:
    return Forecast(
        event_id="e1",
        market_id="m1",
        sport=Sport.NBA,
        market_type=MarketType.MONEYLINE,
        home_team="Los Angeles Lakers",
        away_team="Boston Celtics",
        side=Side.YES,
        ensemble_prob=0.5,
        ensemble_std=0.05,
        confidence=Confidence.MEDIUM,
        market_price=0.5,
        market_implied_prob=0.5,
    )


def _market() -> Market:
    return Market(
        condition_id="m1",
        question="Lakers vs Celtics",
        sport=Sport.NBA,
        yes_token_id="y",
        no_token_id="n",
        end_date=datetime.now(UTC) + timedelta(hours=3),
    )


@pytest.mark.asyncio
async def test_no_news_rejects():
    strat = NewsShockStrategy()
    ctx = DataContext(forecast=_forecast(), source_ages={"polymarket": 30, "news": 60})
    sig = await strat.signal(_market(), ctx)
    assert sig is None


@pytest.mark.asyncio
async def test_irrelevant_news_rejects():
    strat = NewsShockStrategy()
    item = NewsItem(
        fingerprint="fp1",
        headline="Weather forecast calls for rain",
        sport=Sport.NBA,
        published_at=datetime.now(UTC),
    )
    ctx = DataContext(
        forecast=_forecast(),
        fresh_news=[item],
        source_ages={"polymarket": 30, "news": 60},
    )
    sig = await strat.signal(_market(), ctx)
    assert sig is None


@pytest.mark.asyncio
async def test_stale_news_rejects():
    strat = NewsShockStrategy()
    item = NewsItem(
        fingerprint="fp1",
        headline="LeBron James out tonight",
        teams=["Los Angeles Lakers"],
        sport=Sport.NBA,
        published_at=datetime.now(UTC) - timedelta(hours=2),
    )
    ctx = DataContext(
        forecast=_forecast(),
        fresh_news=[item],
        source_ages={"polymarket": 30, "news": 60},
    )
    sig = await strat.signal(_market(), ctx)
    assert sig is None  # news too old


@pytest.mark.asyncio
async def test_freshness_gate_blocks():
    strat = NewsShockStrategy()
    item = NewsItem(
        fingerprint="fp1",
        headline="LeBron James out tonight",
        teams=["Los Angeles Lakers"],
        sport=Sport.NBA,
        published_at=datetime.now(UTC),
    )
    ctx = DataContext(
        forecast=_forecast(),
        fresh_news=[item],
        source_ages={"polymarket": 99999},  # stale
    )
    sig = await strat.signal(_market(), ctx)
    assert sig is None
