"""Platt scaling on rolling prediction history.

If bucket 70% only wins 55% of the time, we're overconfident → shrink probabilities
toward 0.5. Uses a simple linear fit on (predicted bucket center, actual win rate).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from apex.utils.math_utils import clamp_prob

MIN_EVENTS_FOR_CALIBRATION = 50


@dataclass
class CalibrationTable:
    model_name: str
    sport: str = "ALL"
    # Platt parameters: calibrated_p = sigmoid(a * logit(p) + b)
    a: float = 1.0
    b: float = 0.0
    sample_count: int = 0
    buckets: dict[int, tuple[int, int]] = field(default_factory=dict)

    def apply(self, prob: float) -> float:
        p = clamp_prob(prob)
        logit = math.log(p / (1.0 - p))
        z = self.a * logit + self.b
        if z >= 0:
            e = math.exp(-z)
            calibrated = 1.0 / (1.0 + e)
        else:
            e = math.exp(z)
            calibrated = e / (1.0 + e)
        return clamp_prob(calibrated)


def fit_platt(buckets: dict[int, tuple[int, int]]) -> tuple[float, float]:
    """Least-squares fit y = a*x + b on bucket center logit vs actual win rate logit.

    buckets: {bucket_idx: (count, wins)}.
    Returns (a, b). Defaults (1,0) if not enough data.
    """
    points: list[tuple[float, float]] = []
    for b_idx, (count, wins) in buckets.items():
        if count < 5:
            continue
        predicted_center = (b_idx + 0.5) / 10.0  # e.g. bucket 7 → 0.75
        actual = wins / count
        # Avoid logit(0) or logit(1)
        predicted_center = clamp_prob(predicted_center)
        actual = clamp_prob(actual)
        x = math.log(predicted_center / (1 - predicted_center))
        y = math.log(actual / (1 - actual))
        points.append((x, y))

    if len(points) < 3:
        return 1.0, 0.0

    n = len(points)
    sx = sum(p[0] for p in points)
    sy = sum(p[1] for p in points)
    sxx = sum(p[0] ** 2 for p in points)
    sxy = sum(p[0] * p[1] for p in points)
    denom = n * sxx - sx * sx
    if abs(denom) < 1e-9:
        return 1.0, 0.0
    a = (n * sxy - sx * sy) / denom
    b = (sy - a * sx) / n
    # Safety: keep slope positive and bounded
    if a < 0.3:
        a = 0.3
    if a > 3.0:
        a = 3.0
    return a, b


class Calibrator:
    def __init__(self) -> None:
        self._tables: dict[tuple[str, str], CalibrationTable] = {}

    def _key(self, model_name: str, sport: str) -> tuple[str, str]:
        return (model_name, sport or "ALL")

    def get_table(self, model_name: str, sport: str = "ALL") -> CalibrationTable:
        key = self._key(model_name, sport)
        if key not in self._tables:
            self._tables[key] = CalibrationTable(model_name=model_name, sport=sport or "ALL")
        return self._tables[key]

    def record(
        self, model_name: str, prob: float, outcome: int, sport: str = "ALL"
    ) -> None:
        tbl = self.get_table(model_name, sport)
        from apex.quant.calibration.brier_tracker import bucket_of

        b = bucket_of(prob)
        count, wins = tbl.buckets.get(b, (0, 0))
        tbl.buckets[b] = (count + 1, wins + (1 if outcome == 1 else 0))
        tbl.sample_count += 1
        if tbl.sample_count >= MIN_EVENTS_FOR_CALIBRATION and tbl.sample_count % 10 == 0:
            tbl.a, tbl.b = fit_platt(tbl.buckets)

    def apply(self, model_name: str, prob: float, sport: str = "ALL") -> float:
        tbl = self.get_table(model_name, sport)
        if tbl.sample_count < MIN_EVENTS_FOR_CALIBRATION:
            return clamp_prob(prob)  # insufficient data → identity
        return tbl.apply(prob)
