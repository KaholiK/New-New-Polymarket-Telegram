"""Tests for power ratings model."""

from __future__ import annotations

from apex.quant.data.stats_ingestor import TeamStats
from apex.quant.models.power_ratings import PowerRatingsModel


def _stats(team: str, pf: float, pa: float) -> TeamStats:
    return TeamStats(
        team=team,
        sport="NBA",
        wins=50,
        losses=32,
        games_played=82,
        points_for_total=pf * 82,
        points_against_total=pa * 82,
        avg_points_for=pf,
        avg_points_against=pa,
    )


def test_has_team_after_load():
    m = PowerRatingsModel("NBA")
    m.load([_stats("A", 115, 110)])
    assert m.has_team("A")


def test_predict_favorite():
    m = PowerRatingsModel("NBA")
    m.load([_stats("Good", 120, 105), _stats("Bad", 105, 120)])
    p = m.predict("Good", "Bad")
    assert p > 0.5


def test_predict_missing_team_fallback():
    m = PowerRatingsModel("NBA")
    m.load([_stats("A", 115, 110)])
    assert m.predict("A", "Nonexistent") == 0.5


def test_predict_estimate_missing_returns_none():
    m = PowerRatingsModel("NBA")
    m.load([_stats("A", 115, 110)])
    assert m.predict_estimate("A", "Other") is None


def test_predict_spread_sign():
    m = PowerRatingsModel("NBA")
    m.load([_stats("Good", 120, 105), _stats("Bad", 105, 120)])
    assert m.predict_spread("Good", "Bad") > 0
    assert m.predict_spread("Bad", "Good") < 0


def test_predict_total_positive():
    m = PowerRatingsModel("NBA")
    m.load([_stats("A", 115, 110), _stats("B", 115, 110)])
    assert m.predict_total("A", "B") > 0


def test_predict_scores_missing_returns_zeros():
    m = PowerRatingsModel("NBA")
    m.load([_stats("A", 115, 110)])
    a, b = m.predict_scores("A", "Nobody")
    assert a == 0 and b == 0


def test_estimate_includes_factors():
    m = PowerRatingsModel("NBA")
    m.load([_stats("A", 115, 110), _stats("B", 110, 115)])
    est = m.predict_estimate("A", "B")
    assert est is not None
    assert len(est.factors) > 0


def test_predict_stable_near_tie():
    m = PowerRatingsModel("NBA")
    m.load([_stats("A", 110, 110), _stats("B", 110, 110)])
    p = m.predict("A", "B")
    # Exact tie → 0.5
    assert 0.49 < p < 0.51
