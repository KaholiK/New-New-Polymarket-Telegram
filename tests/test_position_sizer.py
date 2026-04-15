"""Tests for position sizer — approve/reject, caps, $1 profit gate."""

from __future__ import annotations

from apex.core.models import (
    Confidence,
    Forecast,
    MarketType,
    OrderBook,
    OrderBookLevel,
    Side,
    Sport,
)
from apex.core.state import BotState
from apex.risk.position_sizer import size_position


def _forecast(price: float = 0.48, prob: float = 0.55, side: Side = Side.YES) -> Forecast:
    market_price = price if side == Side.YES else 1.0 - price
    return Forecast(
        event_id="e1",
        market_id="m1",
        sport=Sport.NBA,
        market_type=MarketType.MONEYLINE,
        home_team="A",
        away_team="B",
        side=side,
        ensemble_prob=prob,
        ensemble_std=0.02,
        confidence=Confidence.MEDIUM,
        market_price=market_price,
        market_implied_prob=market_price,
        raw_edge=prob - market_price,
        edge_zscore=2.0,
        edge_after_costs=0.04,
        kelly_fraction=0.1,
    )


def test_approves_with_strong_edge():
    # Large bankroll so the $1 minimum profit gate is comfortably cleared.
    s = BotState(starting_bankroll=10000.0)
    r = size_position(_forecast(), s, sport=Sport.NBA, event_id="e1")
    assert r.approved
    assert r.size_usd > 0


def test_rejects_when_killed():
    s = BotState()
    s.killed = True
    r = size_position(_forecast(), s, sport=Sport.NBA, event_id="e1")
    assert not r.approved
    assert "killed" in r.reasons


def test_rejects_when_paused():
    s = BotState()
    s.paused = True
    r = size_position(_forecast(), s, sport=Sport.NBA, event_id="e1")
    assert not r.approved


def test_rejects_zero_bankroll():
    s = BotState(starting_bankroll=0.0)
    r = size_position(_forecast(), s, sport=Sport.NBA, event_id="e1")
    assert not r.approved


def test_rejects_non_positive_edge():
    s = BotState(starting_bankroll=100.0)
    fc = _forecast(price=0.55, prob=0.50)
    r = size_position(fc, s, sport=Sport.NBA, event_id="e1")
    assert not r.approved


def test_rejects_below_min_profit_gate_small_bankroll():
    s = BotState(starting_bankroll=5.0)
    # Small bankroll means Kelly size is tiny; $1 profit gate should reject
    r = size_position(_forecast(), s, sport=Sport.NBA, event_id="e1")
    assert not r.approved


def test_size_capped_by_max_position_pct():
    s = BotState(starting_bankroll=1000.0)
    # Even with huge edge, size ≤ 15% of bankroll = $150
    fc = _forecast(price=0.10, prob=0.95)  # massive edge
    r = size_position(fc, s, sport=Sport.NBA, event_id="e1")
    if r.approved:
        assert r.size_usd <= 1000.0 * 0.15 + 0.01


def test_depth_cap_applies():
    s = BotState(starting_bankroll=100.0)
    fc = _forecast()
    # Very shallow book: only 10 contracts at ask
    book = OrderBook(token_id="t", asks=[OrderBookLevel(price=0.48, size=10)])
    r = size_position(fc, s, book=book, sport=Sport.NBA, event_id="e1")
    if r.approved:
        # contracts <= 30% of 10 = 3.0
        assert r.contracts <= 3.0 + 0.01


def test_approved_sets_prices():
    s = BotState(starting_bankroll=100.0)
    r = size_position(_forecast(), s, sport=Sport.NBA, event_id="e1")
    if r.approved:
        assert r.limit_price > 0
        assert r.estimated_fill_price > 0


def test_rejects_on_daily_drawdown():

    async def runner():
        s = BotState(starting_bankroll=100.0)
        await s.debit(25.0)  # 25% daily drawdown
        r = size_position(_forecast(), s, sport=Sport.NBA, event_id="e1")
        assert not r.approved

    import asyncio

    asyncio.run(runner())
