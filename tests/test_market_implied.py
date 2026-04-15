"""Tests for market-implied model."""

from __future__ import annotations

from apex.core.models import Market, Sport
from apex.data.consensus_builder import Consensus
from apex.quant.models.market_implied import (
    MarketImpliedModel,
    polymarket_implied_prob,
    remove_vig_market,
)


def _market(yes: float, no: float) -> Market:
    return Market(
        condition_id="c",
        question="q",
        sport=Sport.NBA,
        yes_token_id="y",
        no_token_id="n",
        yes_price=yes,
        no_price=no,
    )


def test_polymarket_implied_no_vig():
    # Yes=0.48, No=0.52 — sums to 1 already
    p = polymarket_implied_prob(_market(0.48, 0.52))
    assert abs(p - 0.48) < 1e-6


def test_polymarket_implied_normalizes():
    p = polymarket_implied_prob(_market(0.55, 0.55))
    assert abs(p - 0.5) < 1e-3


def test_polymarket_implied_zero_sum():
    p = polymarket_implied_prob(_market(0.0, 0.0))
    assert p == 0.5


def test_market_implied_predict_without_consensus():
    m = MarketImpliedModel()
    p = m.predict(_market(0.48, 0.52))
    assert abs(p - 0.48) < 1e-3


def test_market_implied_blends_with_consensus():
    m = MarketImpliedModel()
    cons = Consensus(
        event_id="e",
        home_team="A",
        away_team="B",
        home_prob=0.60,
        away_prob=0.40,
        book_count=2,
        weighted_book_count=4.0,
        fair_probs_by_book={},
    )
    p = m.predict(_market(0.48, 0.52), cons)
    # Should be between 0.48 and 0.60
    assert 0.48 <= p <= 0.60


def test_remove_vig_market_wrapper():
    a, b = remove_vig_market(0.55, 0.55)
    assert abs(a + b - 1.0) < 1e-6


def test_predict_estimate_has_factors():
    m = MarketImpliedModel()
    est = m.predict_estimate(_market(0.48, 0.52))
    assert est.model_name == "market_implied"
    assert len(est.factors) >= 1
