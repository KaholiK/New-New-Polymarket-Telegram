"""Tests for Poisson model."""

from __future__ import annotations

import pytest

from apex.quant.models.poisson import PoissonModel


def test_lambdas_reasonable():
    m = PoissonModel(league_avg_goals=3.0, n_sims=1000, seed=7)
    hl, al = m.lambdas(3.2, 2.8, 2.8, 3.2)
    assert hl > 0 and al > 0


def test_zero_goals_uses_floor():
    m = PoissonModel(league_avg_goals=3.0, n_sims=1000, seed=7)
    hl, al = m.lambdas(0.0, 3.0, 3.0, 0.0)
    assert hl >= 0.1
    assert al >= 0.1


def test_simulation_distribution():
    m = PoissonModel(league_avg_goals=3.0, n_sims=5000, seed=7)
    home, away = m.simulate(3.0, 3.0)
    # Symmetric matchup → near 50/50 home-win after removing ties
    home_win = (home > away).mean()
    away_win = (away > home).mean()
    assert abs(home_win - away_win) < 0.05


def test_predict_returns_all_keys():
    m = PoissonModel(league_avg_goals=3.0, n_sims=2000, seed=7)
    res = m.predict(3.2, 2.8, 2.8, 3.2)
    for key in ("home_win", "away_win", "draw"):
        assert key in res


def test_predict_home_favored():
    m = PoissonModel(league_avg_goals=3.0, n_sims=5000, seed=7)
    # Home strong attack, away weak defense
    res = m.predict(4.0, 2.5, 2.0, 3.5)
    assert res["home_win"] > res["away_win"]


def test_predict_total_over_under():
    m = PoissonModel(league_avg_goals=3.0, n_sims=5000, seed=7)
    res = m.predict_total(3.0, 3.0, 3.0, 3.0, line=5.5)
    assert "over" in res and "under" in res
    assert res["over"] + res["under"] + res["push"] == pytest.approx(1.0, abs=0.02)


def test_predict_total_extreme_line():
    m = PoissonModel(league_avg_goals=3.0, n_sims=5000, seed=7)
    # Extreme line → almost no over
    res = m.predict_total(3.0, 3.0, 3.0, 3.0, line=50.0)
    assert res["over"] < 0.05


def test_predict_estimate_model_name():
    m = PoissonModel(league_avg_goals=3.0, n_sims=1000, seed=7)
    est = m.predict_estimate(3.2, 2.8, 2.8, 3.2)
    assert est.model_name == "poisson"


def test_zero_league_avg_no_crash():
    m = PoissonModel(league_avg_goals=0.0, n_sims=100, seed=7)
    # Should floor to 0.5 internally
    hl, al = m.lambdas(3.0, 3.0, 3.0, 3.0)
    assert hl > 0
