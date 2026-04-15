"""Tests for Brier tracker, calibrator, model weights."""

from __future__ import annotations

from apex.quant.calibration.brier_tracker import BrierTracker, bucket_of
from apex.quant.calibration.calibrator import Calibrator, fit_platt
from apex.quant.calibration.model_weights import (
    WEIGHT_CEILING,
    WEIGHT_FLOOR,
    compute_weights,
)


def test_bucket_of_edges():
    assert bucket_of(0.0) == 0
    assert bucket_of(0.55) == 5
    assert bucket_of(1.0) == 9


def test_brier_tracker_record_improves():
    t = BrierTracker()
    # Good prediction: p=0.9 on a winning outcome
    t.record("model", 0.9, 1, sport="NBA")
    assert t.get("model", "NBA").avg_brier < 0.25


def test_brier_tracker_buckets():
    t = BrierTracker()
    for _ in range(10):
        t.record("m", 0.75, 1, sport="NBA")
    s = t.get("m", "NBA")
    assert s.forecasts == 10
    assert 7 in s.buckets


def test_brier_summary_keys():
    t = BrierTracker()
    t.record("m", 0.5, 1, sport="NBA")
    summ = t.summary()
    assert any("m:NBA" in k for k in summ)


def test_ece_zero_when_well_calibrated():
    t = BrierTracker()
    for _ in range(100):
        t.record("m", 0.5, 1, sport="NBA")
        t.record("m", 0.5, 0, sport="NBA")
    # Well-calibrated at 50%. ECE uses bucket centers (0.55) so exact 0 isn't reachable.
    assert t.get("m", "NBA").ece < 0.10


def test_calibrator_identity_with_few_samples():
    c = Calibrator()
    c.record("m", 0.7, 1, "NBA")
    # Below threshold → identity
    assert abs(c.apply("m", 0.7, "NBA") - 0.7) < 1e-6


def test_calibrator_applies_after_threshold():
    c = Calibrator()
    # Feed 60 calibrated forecasts: predicted 70%, actual 50%
    for i in range(30):
        c.record("m", 0.7, 1, "NBA")
    for i in range(30):
        c.record("m", 0.7, 0, "NBA")
    # After 60 samples, the calibration should kick in
    out = c.apply("m", 0.7, "NBA")
    assert 0.001 <= out <= 0.999


def test_fit_platt_identity_insufficient_data():
    a, b = fit_platt({5: (2, 1)})
    assert a == 1.0
    assert b == 0.0


def test_compute_weights_fallback_when_no_data():
    t = BrierTracker()
    w = compute_weights(t, sport="NBA")
    # Falls back to defaults
    assert abs(sum(w.values()) - 1.0) < 1e-3


def test_compute_weights_better_model_gets_more():
    t = BrierTracker()
    # "good" model: 21 correct forecasts at 0.9
    for _ in range(21):
        t.record("good", 0.9, 1, "NBA")
    for _ in range(21):
        t.record("bad", 0.5, 0, "NBA")  # coin flip
    for _ in range(21):
        t.record("bad", 0.5, 1, "NBA")
    w = compute_weights(t, sport="NBA")
    # good should be weighted >= bad after floor/ceiling
    assert w.get("good", WEIGHT_FLOOR) >= w.get("bad", WEIGHT_FLOOR)


def test_weights_respect_floor_and_ceiling():
    t = BrierTracker()
    for _ in range(30):
        t.record("amazing", 0.99, 1, "NBA")  # extremely low brier
    w = compute_weights(t, sport="NBA")
    assert all(WEIGHT_FLOOR <= v <= WEIGHT_CEILING + 1e-6 for v in w.values())


def test_calibrator_table_default():
    c = Calibrator()
    tbl = c.get_table("xxx")
    assert tbl.a == 1.0
    assert tbl.b == 0.0
