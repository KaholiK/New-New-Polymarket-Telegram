"""Tests for situational model."""

from __future__ import annotations

from apex.quant.models.situational import SituationalInputs, SituationalModel, situational_adjustment


def test_neutral_no_adjustment():
    inp = SituationalInputs(home_team="A", away_team="B")
    delta, factors = situational_adjustment(inp, sport="NBA")
    assert delta == 0.0


def test_rest_diff_helps_rested_team():
    inp = SituationalInputs(home_team="A", away_team="B", home_rest_days=4, away_rest_days=1)
    delta, factors = situational_adjustment(inp, sport="NBA")
    assert delta > 0
    assert any("rest" in f for f in factors)


def test_b2b_nba_hurts_home():
    inp = SituationalInputs(home_team="A", away_team="B", home_back_to_back=True)
    delta, factors = situational_adjustment(inp, sport="NBA")
    assert delta < 0


def test_altitude_advantage():
    inp = SituationalInputs(home_team="A", away_team="B", altitude_diff_meters=1500)
    delta, factors = situational_adjustment(inp, sport="NBA")
    assert delta > 0


def test_cap_total_at_plus_eight():
    # Stacking many positive factors
    inp = SituationalInputs(
        home_team="A", away_team="B",
        home_rest_days=5, away_rest_days=0,
        away_back_to_back=True,
        travel_timezone_shift=3,
        altitude_diff_meters=2500,
        home_playoff_elimination=True,
        is_rivalry=True,
    )
    delta, _ = situational_adjustment(inp, sport="NBA")
    assert delta <= 0.08


def test_cap_total_at_minus_eight():
    inp = SituationalInputs(
        home_team="A", away_team="B",
        home_rest_days=0, away_rest_days=5,
        home_back_to_back=True,
        away_playoff_elimination=True,
    )
    delta, _ = situational_adjustment(inp, sport="NBA")
    assert delta >= -0.08


def test_model_returns_estimate():
    inp = SituationalInputs(home_team="A", away_team="B", home_rest_days=4, away_rest_days=1)
    m = SituationalModel()
    est = m.predict_estimate(0.5, inp, sport="NBA")
    assert est.model_name == "situational"
    assert est.probability >= 0.5
