"""Tests for Elo model — predict, update, regression, K-factor."""

from __future__ import annotations

import pytest

from apex.quant.models.elo import (
    STARTING_ELO,
    EloModel,
    expected_score,
    k_factor,
    season_regression,
)


def test_expected_score_equal():
    assert expected_score(1500, 1500) == 0.5


def test_expected_score_higher_wins_more():
    assert expected_score(1600, 1500) > 0.5
    assert expected_score(1400, 1500) < 0.5


def test_k_factor_early_late():
    early = k_factor("NBA", games_played=0)
    late = k_factor("NBA", games_played=40)
    assert early > late


def test_k_factor_ufc_flat():
    assert k_factor("UFC", 0) == k_factor("UFC", 20)


def test_season_regression():
    assert season_regression(1700, 0.25) == pytest.approx(1650.0, abs=1e-6)
    # Regression toward 1500
    assert season_regression(1500, 0.25) == 1500.0


def test_default_elo():
    m = EloModel("NBA")
    assert m.get("Anyone") == STARTING_ELO


def test_predict_home_advantage():
    m = EloModel("NBA")
    # Same Elo; home advantage should push >50%
    p = m.predict("A", "B", home_is_home=True)
    assert p > 0.5


def test_predict_symmetric_without_home():
    m = EloModel("UFC")  # no home advantage
    p = m.predict("A", "B", home_is_home=True)
    assert p == pytest.approx(0.5, abs=1e-6)


def test_update_winner_gains():
    m = EloModel("NBA")
    delta_home, delta_away = m.update("A", "B", home_won=True)
    assert delta_home > 0
    assert delta_away < 0


def test_update_increases_games():
    m = EloModel("NBA")
    m.update("A", "B", home_won=True)
    assert m.get_games("A") == 1
    assert m.get_games("B") == 1


def test_regress_all_resets_games():
    m = EloModel("NBA")
    m.update("A", "B", home_won=True)
    assert m.get_games("A") == 1
    m.regress_all()
    assert m.get_games("A") == 0


def test_predict_estimate_contains_factors():
    m = EloModel("NBA")
    m.set("A", 1600)
    m.set("B", 1500)
    est = m.predict_estimate("A", "B")
    assert est.model_name == "elo"
    assert est.factors


def test_bulk_load():
    m = EloModel("NBA")
    m.bulk_load({"A": 1550, "B": 1520})
    assert m.get("A") == 1550


def test_update_losses_are_symmetric_in_magnitude():
    m = EloModel("UFC")  # no home advantage, equal start
    dh, da = m.update("A", "B", home_won=True, home_is_home=False)
    assert abs(dh + da) < 1e-6  # zero-sum-ish


def test_early_k_is_higher_after_season_reset():
    m = EloModel("NBA")
    for _ in range(30):
        m.update("A", "B", home_won=True)
    late_k = k_factor("NBA", m.get_games("A"))
    m.regress_all()
    early_k = k_factor("NBA", m.get_games("A"))
    assert early_k >= late_k
