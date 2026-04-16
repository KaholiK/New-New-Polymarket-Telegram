"""Tests for ensemble — log-linear pooling, confidence classification."""

from __future__ import annotations

import pytest

from apex.core.models import Confidence, ModelEstimate
from apex.quant.models.ensemble import DEFAULT_WEIGHTS, classify_confidence, combine


def _est(name: str, prob: float, std: float = 0.05, factors: list[str] | None = None) -> ModelEstimate:
    return ModelEstimate(
        model_name=name,
        probability=prob,
        uncertainty=std,
        confidence=0.7,
        factors=factors or [f"{name} factor"],
    )


def test_combine_single_model_insufficient():
    res = combine({"elo": _est("elo", 0.55)})
    assert res.confidence == Confidence.NO_OPINION


def test_combine_two_models_same_prob():
    res = combine(
        {
            "elo": _est("elo", 0.6),
            "market_implied": _est("market_implied", 0.6),
        }
    )
    assert res.probability == pytest.approx(0.6, abs=0.01)


def test_combine_weighted():
    # Heavy market_implied weight + low elo weight → closer to market
    res = combine(
        {
            "market_implied": _est("market_implied", 0.55),
            "elo": _est("elo", 0.70),
        },
        weights={"market_implied": 0.8, "elo": 0.2},
    )
    # Should lean toward 0.55
    assert res.probability < 0.65


def test_combine_disagreement():
    res = combine(
        {
            "a": _est("a", 0.3),
            "b": _est("b", 0.7),
        }
    )
    assert res.disagreement > 0.15


def test_combine_skips_none():
    res = combine({"a": _est("a", 0.55), "b": None})  # type: ignore
    # Only 1 model → NO_OPINION
    assert res.confidence == Confidence.NO_OPINION


def test_confidence_high_thresholds():
    c = classify_confidence(n_models=3, disagreement=0.02, edge_zscore=2.5)
    assert c == Confidence.HIGH


def test_confidence_medium():
    c = classify_confidence(n_models=2, disagreement=0.04, edge_zscore=1.8)
    assert c == Confidence.MEDIUM


def test_confidence_low_disagreement():
    c = classify_confidence(n_models=3, disagreement=0.12, edge_zscore=0.5)
    assert c == Confidence.LOW


def test_confidence_no_opinion_few_models():
    c = classify_confidence(n_models=1, disagreement=0.01, edge_zscore=3.0)
    assert c == Confidence.NO_OPINION


def test_default_weights_claude_highest_and_bounded():
    # After wiring Claude into the ensemble at weight 0.30, the raw weight sum can
    # exceed 1.0 — `combine()` (via geometric_mean_odds) normalizes internally so
    # this is fine. We just check claude is highest and every weight is in [0, 1].
    assert DEFAULT_WEIGHTS["claude"] >= max(v for k, v in DEFAULT_WEIGHTS.items() if k != "claude")
    assert all(0.0 <= v <= 1.0 for v in DEFAULT_WEIGHTS.values())
    assert abs(sum(DEFAULT_WEIGHTS.values()) - 1.1) < 1e-6


def test_combine_factors_aggregated():
    res = combine(
        {
            "elo": _est("elo", 0.55, factors=["elo_says"]),
            "power_ratings": _est("power_ratings", 0.55, factors=["power_says"]),
        }
    )
    assert "elo_says" in res.factors
    assert "power_says" in res.factors


def test_combine_probability_clamped():
    res = combine(
        {
            "a": _est("a", 0.001),
            "b": _est("b", 0.001),
        }
    )
    assert res.probability >= 0.001


def test_combine_empty_returns_no_opinion():
    res = combine({})
    assert res.confidence == Confidence.NO_OPINION
