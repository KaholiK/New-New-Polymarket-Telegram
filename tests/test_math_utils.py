"""Tests for math utilities — odds conversion, vig removal, Kelly, EV, clamping."""

from __future__ import annotations

import math

import pytest

from apex.utils.math_utils import (
    PROB_CEIL,
    PROB_FLOOR,
    american_to_decimal,
    brier_score,
    clamp_prob,
    decimal_to_american,
    ev_polymarket,
    expected_value,
    geometric_mean_odds,
    implied_prob_from_american,
    implied_prob_from_decimal,
    kelly_fraction,
    kelly_from_polymarket,
    log_loss,
    polymarket_edge,
    remove_vig_power,
    remove_vig_two_way,
    sigmoid,
    z_score,
)


class TestClampProb:
    def test_clamps_zero_to_floor(self):
        assert clamp_prob(0.0) == PROB_FLOOR

    def test_clamps_one_to_ceil(self):
        assert clamp_prob(1.0) == PROB_CEIL

    def test_passes_through_valid(self):
        assert clamp_prob(0.5) == 0.5

    def test_handles_nan(self):
        assert clamp_prob(float("nan")) == 0.5

    def test_clamps_negative(self):
        assert clamp_prob(-0.5) == PROB_FLOOR

    def test_clamps_greater_than_one(self):
        assert clamp_prob(1.5) == PROB_CEIL


class TestAmericanToDecimal:
    def test_minus_110(self):
        assert american_to_decimal(-110) == pytest.approx(1.909, abs=1e-3)

    def test_plus_100(self):
        assert american_to_decimal(100) == 2.0

    def test_plus_150(self):
        assert american_to_decimal(150) == 2.5

    def test_minus_200(self):
        assert american_to_decimal(-200) == 1.5

    def test_zero_raises(self):
        with pytest.raises(ValueError):
            american_to_decimal(0)


class TestDecimalToAmerican:
    def test_two_point_zero(self):
        assert decimal_to_american(2.0) == 100

    def test_one_point_five(self):
        assert decimal_to_american(1.5) == -200

    def test_invalid_raises(self):
        with pytest.raises(ValueError):
            decimal_to_american(1.0)


class TestImpliedProb:
    def test_decimal_two(self):
        assert implied_prob_from_decimal(2.0) == 0.5

    def test_decimal_four(self):
        assert implied_prob_from_decimal(4.0) == 0.25

    def test_american_minus_110(self):
        assert implied_prob_from_american(-110) == pytest.approx(0.524, abs=1e-2)


class TestRemoveVig:
    def test_two_way_symmetric(self):
        a, b = remove_vig_two_way(0.524, 0.524)
        assert a == pytest.approx(0.5, abs=1e-6)
        assert b == pytest.approx(0.5, abs=1e-6)

    def test_two_way_asymmetric(self):
        a, b = remove_vig_two_way(0.6, 0.45)
        assert a > b
        assert a + b == pytest.approx(1.0, abs=1e-6)

    def test_two_way_zero_sum(self):
        a, b = remove_vig_two_way(0.0, 0.0)
        assert a == 0.5
        assert b == 0.5

    def test_power_normalizes(self):
        probs = [0.4, 0.35, 0.3]
        out = remove_vig_power(probs)
        assert sum(out) == pytest.approx(1.0, abs=1e-4)

    def test_power_already_normalized(self):
        probs = [0.5, 0.5]
        out = remove_vig_power(probs)
        assert sum(out) == pytest.approx(1.0, abs=1e-6)

    def test_power_empty(self):
        assert remove_vig_power([]) == []


class TestKelly:
    def test_positive_edge(self):
        # 60% true prob at even money → clear positive edge
        f = kelly_fraction(0.6, 2.0)
        assert f > 0

    def test_no_edge(self):
        # 50% at even money → 0 edge, Kelly=0
        f = kelly_fraction(0.5, 2.0)
        assert f == pytest.approx(0.0, abs=1e-6)

    def test_negative_edge_floored(self):
        f = kelly_fraction(0.4, 2.0)
        assert f == 0.0

    def test_polymarket_yes(self):
        # True 55% vs market 48¢ → clear edge
        f = kelly_from_polymarket(0.55, 0.48)
        assert f > 0

    def test_polymarket_no_edge(self):
        f = kelly_from_polymarket(0.45, 0.50)
        assert f == 0.0

    def test_polymarket_invalid_price(self):
        assert kelly_from_polymarket(0.5, 0.0) == 0.0
        assert kelly_from_polymarket(0.5, 1.0) == 0.0


class TestEV:
    def test_positive_ev(self):
        ev = expected_value(0.6, 2.0, stake=1.0)
        assert ev > 0

    def test_zero_ev(self):
        ev = expected_value(0.5, 2.0, stake=1.0)
        assert ev == pytest.approx(0.0, abs=1e-6)

    def test_polymarket_ev(self):
        # 55% true, 48¢ price, $10 stake
        ev = ev_polymarket(0.55, 0.48, 10.0)
        assert ev > 0

    def test_polymarket_ev_invalid_price(self):
        assert ev_polymarket(0.5, 0.0, 10.0) == 0.0
        assert ev_polymarket(0.5, 0.5, 0.0) == 0.0

    def test_polymarket_edge(self):
        e = polymarket_edge(0.55, 0.48)
        assert e == pytest.approx(0.07, abs=1e-6)


class TestBrierAndLogLoss:
    def test_brier_perfect_win(self):
        assert brier_score(1.0, 1) < 1e-3  # clamped

    def test_brier_perfect_loss(self):
        assert brier_score(0.0, 0) < 1e-3

    def test_brier_coin_flip(self):
        assert brier_score(0.5, 1) == 0.25

    def test_brier_invalid_outcome(self):
        with pytest.raises(ValueError):
            brier_score(0.5, 2)

    def test_log_loss_symmetric(self):
        l1 = log_loss(0.9, 1)
        l2 = log_loss(0.1, 0)
        assert l1 == pytest.approx(l2, abs=1e-6)

    def test_log_loss_invalid(self):
        with pytest.raises(ValueError):
            log_loss(0.5, 2)


class TestGeometricMean:
    def test_equal_probs_return_input(self):
        assert geometric_mean_odds([0.5, 0.5, 0.5]) == pytest.approx(0.5, abs=1e-6)

    def test_weights_bias(self):
        # Heavier weight on higher prob → combined pulled up
        combined = geometric_mean_odds([0.6, 0.4], weights=[3.0, 1.0])
        # > naive mean 0.5
        assert combined > 0.5

    def test_empty(self):
        assert geometric_mean_odds([]) == 0.5

    def test_mismatched_weights_raises(self):
        with pytest.raises(ValueError):
            geometric_mean_odds([0.5, 0.5], weights=[1.0])

    def test_zero_weights_falls_back(self):
        out = geometric_mean_odds([0.5, 0.5], weights=[0.0, 0.0])
        assert out == pytest.approx(0.5, abs=1e-6)


class TestMisc:
    def test_z_score_zero_std(self):
        assert z_score(1.0, 0.0, 0.0) == 0.0

    def test_z_score_normal(self):
        assert z_score(2.0, 1.0, 0.5) == 2.0

    def test_sigmoid_zero(self):
        assert sigmoid(0.0) == 0.5

    def test_sigmoid_large_positive(self):
        assert sigmoid(100.0) == pytest.approx(1.0, abs=1e-6)

    def test_sigmoid_large_negative(self):
        assert sigmoid(-100.0) == pytest.approx(0.0, abs=1e-6)

    def test_log_loss_finite_at_clamp(self):
        # Even p=0 is clamped so log doesn't blow up
        assert math.isfinite(log_loss(0.0, 1))
        assert math.isfinite(log_loss(1.0, 0))
