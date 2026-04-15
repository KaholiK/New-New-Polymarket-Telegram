"""Dynamic model weighting from recent Brier performance.

Better (lower) Brier → higher weight. Apply 5% floor and 40% ceiling.
"""

from __future__ import annotations

from apex.quant.calibration.brier_tracker import BrierTracker
from apex.quant.models.ensemble import DEFAULT_WEIGHTS

WEIGHT_FLOOR = 0.05
WEIGHT_CEILING = 0.40


def compute_weights(
    tracker: BrierTracker,
    sport: str = "ALL",
    min_forecasts: int = 20,
) -> dict[str, float]:
    """Weight ∝ 1 / avg_brier (lower Brier → higher weight).

    Falls back to DEFAULT_WEIGHTS if no model has enough forecasts.
    """
    # Consider only models with sufficient forecasts
    eligible: dict[str, float] = {}
    for (name, s), stats in tracker._stats.items():  # noqa: SLF001
        if s not in (sport, "ALL"):
            continue
        if stats.forecasts < min_forecasts:
            continue
        brier = max(1e-4, stats.avg_brier)
        # inverse relationship, normalized after
        eligible[name] = 1.0 / brier

    if not eligible:
        return dict(DEFAULT_WEIGHTS)

    # Normalize
    total = sum(eligible.values())
    raw = {k: v / total for k, v in eligible.items()}

    # Apply floor/ceiling. No final renormalization — geometric_mean_odds will
    # normalize internally. This preserves the [floor, ceiling] invariant on
    # per-model weights (the value downstream code sees).
    clipped: dict[str, float] = {}
    for k, v in raw.items():
        clipped[k] = max(WEIGHT_FLOOR, min(WEIGHT_CEILING, v))

    # Ensure all default models are represented with at least floor weight
    for name in DEFAULT_WEIGHTS:
        clipped.setdefault(name, WEIGHT_FLOOR)

    return clipped
