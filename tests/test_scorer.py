"""Tests for meta scorer."""

from __future__ import annotations

from apex.core.models import Confidence, Side, Signal
from apex.meta.scorer import (
    correlation_penalty,
    mapping_penalty,
    score_confidence,
    score_edge_zscore,
    score_liquidity,
    score_priority,
    score_signal,
    stale_data_penalty,
)


def _sig(
    strategy: str = "fair_value",
    edge_z: float = 2.0,
    conf: Confidence = Confidence.MEDIUM,
    urgency: float = 0.5,
) -> Signal:
    return Signal(
        strategy=strategy,
        market_id="m1",
        event_id="e1",
        side=Side.YES,
        size_hint_usd=0.0,
        edge=0.05,
        edge_zscore=edge_z,
        confidence=conf,
        urgency=urgency,
    )


def test_edge_zscore_capped():
    assert score_edge_zscore(10.0) == score_edge_zscore(5.0)


def test_confidence_scores():
    assert score_confidence(Confidence.HIGH) > score_confidence(Confidence.MEDIUM)
    assert score_confidence(Confidence.MEDIUM) > score_confidence(Confidence.LOW)
    assert score_confidence(Confidence.NO_OPINION) == 0.0


def test_liquidity_zero():
    assert score_liquidity(0, 0) == 0.0


def test_liquidity_scales():
    assert score_liquidity(100_000, 0) > score_liquidity(100, 0)


def test_priority_known():
    assert score_priority("fair_value") == 10
    assert score_priority("unknown") == 5


def test_correlation_penalty_same_event_heavy():
    assert correlation_penalty(1, 0) < correlation_penalty(0, 0)
    assert correlation_penalty(1, 0) == -15.0


def test_correlation_penalty_no_existing():
    assert correlation_penalty(0, 0) == 0.0


def test_mapping_penalty_gated():
    assert mapping_penalty(0.95) == 0.0
    assert mapping_penalty(0.75) == -5.0
    assert mapping_penalty(0.5) == -15.0


def test_stale_penalty():
    assert stale_data_penalty(1.0) == 0.0
    assert stale_data_penalty(0.5) == -20.0


def test_score_signal_happy_path():
    sig = _sig(edge_z=2.5, conf=Confidence.HIGH, urgency=0.8)
    total, comps, pens = score_signal(
        sig,
        volume=50000,
        liquidity=5000,
        data_freshness=0.95,
        mapping_confidence=0.9,
    )
    assert total > 0
    assert comps["edge_zscore"] > 0
    assert pens["mapping"] == 0.0


def test_score_signal_penalized_for_stale():
    sig = _sig(edge_z=2.0)
    total, _, pens = score_signal(
        sig,
        volume=50000,
        liquidity=5000,
        data_freshness=0.3,
        mapping_confidence=0.9,
    )
    assert pens["stale_data"] < 0


def test_score_signal_correlation_penalty():
    sig = _sig()
    total, _, pens = score_signal(
        sig,
        volume=50000,
        liquidity=5000,
        data_freshness=1.0,
        mapping_confidence=1.0,
        existing_same_event=1,
    )
    assert pens["correlation"] == -15.0
