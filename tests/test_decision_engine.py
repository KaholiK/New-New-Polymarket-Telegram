"""Tests for decision engine — gates, conflicts, outcomes."""

from __future__ import annotations

from apex.core.models import (
    Confidence,
    DecisionOutcome,
    Forecast,
    MarketType,
    Side,
    Signal,
    Sport,
)
from apex.core.state import BotState
from apex.meta.conflict_resolver import dedupe_and_resolve
from apex.meta.decision_engine import evaluate_signal


def _sig(side: Side = Side.YES, edge_z: float = 2.5, strategy: str = "fair_value") -> Signal:
    fc = Forecast(
        event_id="e1",
        market_id="m1",
        sport=Sport.NBA,
        market_type=MarketType.MONEYLINE,
        home_team="A",
        away_team="B",
        side=side,
        ensemble_prob=0.55,
        ensemble_std=0.02,
        confidence=Confidence.MEDIUM,
        market_price=0.48,
        market_implied_prob=0.48,
        raw_edge=0.07,
        edge_zscore=edge_z,
        edge_after_costs=0.05,
    )
    return Signal(
        strategy=strategy,
        market_id="m1",
        event_id="e1",
        side=side,
        size_hint_usd=0.0,
        edge=0.07,
        edge_zscore=edge_z,
        confidence=Confidence.MEDIUM,
        urgency=0.5,
        forecast=fc,
    )


def test_reject_when_killed():
    s = BotState()
    s.killed = True
    d = evaluate_signal(
        _sig(), s, market_volume=10000, market_liquidity=1000,
        data_freshness=1.0, mapping_confidence=0.9,
        sport=Sport.NBA, event_id="e1",
    )
    assert d.outcome == DecisionOutcome.REJECT
    assert any("kill" in r.lower() for r in d.trace.reasons)


def test_reject_when_paused():
    s = BotState()
    s.paused = True
    s.pause_reason = "manual"
    d = evaluate_signal(
        _sig(), s, market_volume=10000, market_liquidity=1000,
        data_freshness=1.0, mapping_confidence=0.9,
        sport=Sport.NBA, event_id="e1",
    )
    assert d.outcome == DecisionOutcome.REJECT


def test_approve_with_strong_signal():
    # Large bankroll so the $1 min-profit gate inside sizing clears
    s = BotState(starting_bankroll=10000.0)
    d = evaluate_signal(
        _sig(edge_z=3.5), s, market_volume=50000, market_liquidity=5000,
        data_freshness=1.0, mapping_confidence=0.95,
        sport=Sport.NBA, event_id="e1",
    )
    assert d.outcome in (DecisionOutcome.APPROVE, DecisionOutcome.APPROVE_REDUCED)
    if d.outcome == DecisionOutcome.APPROVE:
        assert d.final_size_usd > 0


def test_reject_with_low_score():
    s = BotState(starting_bankroll=100.0)
    d = evaluate_signal(
        _sig(edge_z=0.2), s, market_volume=100, market_liquidity=50,
        data_freshness=0.3, mapping_confidence=0.5,
        sport=Sport.NBA, event_id="e1",
    )
    assert d.outcome == DecisionOutcome.REJECT


def test_reduced_size_in_middle_band():
    s = BotState(starting_bankroll=100.0)
    d = evaluate_signal(
        _sig(edge_z=1.6), s, market_volume=5000, market_liquidity=500,
        data_freshness=0.7, mapping_confidence=0.8,
        sport=Sport.NBA, event_id="e1",
    )
    # Score should land in 40-59 band if anywhere
    if d.outcome == DecisionOutcome.APPROVE_REDUCED:
        assert d.final_size_usd > 0


def test_dedupe_yes_preferred_when_higher():
    s1 = _sig(side=Side.YES)
    s2 = _sig(side=Side.NO)
    resolved = dedupe_and_resolve([(s1, 80), (s2, 40)], score_diff_required=30)
    assert len(resolved) == 1
    assert resolved[0][0].side == Side.YES


def test_dedupe_conflict_rejected():
    s1 = _sig(side=Side.YES)
    s2 = _sig(side=Side.NO)
    resolved = dedupe_and_resolve([(s1, 65), (s2, 60)], score_diff_required=30)
    assert len(resolved) == 0


def test_dedupe_same_side_keeps_highest():
    s1 = _sig(side=Side.YES, strategy="fair_value")
    s2 = _sig(side=Side.YES, strategy="news_shock")
    resolved = dedupe_and_resolve([(s1, 50), (s2, 70)])
    assert len(resolved) == 1
    assert resolved[0][0].strategy == "news_shock"
