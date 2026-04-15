"""Calibration-weighted log-linear pooling of model outputs."""

from __future__ import annotations

from dataclasses import dataclass

from apex.core.models import Confidence, ModelEstimate
from apex.utils.math_utils import clamp_prob, geometric_mean_odds

# Fallback weights if no calibration history available
DEFAULT_WEIGHTS: dict[str, float] = {
    "market_implied": 0.35,
    "elo": 0.20,
    "power_ratings": 0.20,
    "poisson": 0.10,
    "situational": 0.10,
    "injury": 0.05,
}

MIN_MODELS_REQUIRED = 2


@dataclass
class EnsembleResult:
    probability: float
    std: float  # uncertainty across models
    disagreement: float  # std of model probs
    confidence: Confidence
    contributing_models: list[str]
    factors: list[str]


def combine(
    estimates: dict[str, ModelEstimate],
    weights: dict[str, float] | None = None,
    edge_zscore: float = 0.0,
) -> EnsembleResult:
    """Log-linear pool of model probs with dynamic weights.

    - Skip None / missing estimates.
    - Require at least 2 usable models.
    - Confidence from disagreement + edge_zscore.
    """
    weights = weights or DEFAULT_WEIGHTS
    usable = {name: est for name, est in estimates.items() if est is not None}
    if len(usable) < MIN_MODELS_REQUIRED:
        return EnsembleResult(
            probability=0.5,
            std=0.2,
            disagreement=0.2,
            confidence=Confidence.NO_OPINION,
            contributing_models=list(usable.keys()),
            factors=["insufficient_models"],
        )

    probs: list[float] = []
    ws: list[float] = []
    factors: list[str] = []
    for name, est in usable.items():
        w = weights.get(name, 0.05)
        probs.append(clamp_prob(est.probability))
        ws.append(w)
        factors.extend(est.factors)

    combined = geometric_mean_odds(probs, ws)

    mean_p = sum(probs) / len(probs)
    variance = sum((p - mean_p) ** 2 for p in probs) / len(probs)
    disagreement = variance**0.5

    # Confidence classification
    confidence = classify_confidence(
        n_models=len(usable),
        disagreement=disagreement,
        edge_zscore=edge_zscore,
    )

    return EnsembleResult(
        probability=clamp_prob(combined),
        std=disagreement,
        disagreement=disagreement,
        confidence=confidence,
        contributing_models=list(usable.keys()),
        factors=factors,
    )


def classify_confidence(
    n_models: int, disagreement: float, edge_zscore: float
) -> Confidence:
    """Thresholds from the spec:
    high:   3+ models, std < 0.03, |z| > 2.0
    medium: 2+ models, std < 0.06, |z| > 1.5
    low:    models disagree (std > 0.06) OR few data points
    no_opinion: < 2 models OR all data stale
    """
    if n_models < MIN_MODELS_REQUIRED:
        return Confidence.NO_OPINION
    z = abs(edge_zscore)
    if n_models >= 3 and disagreement < 0.03 and z > 2.0:
        return Confidence.HIGH
    if n_models >= 2 and disagreement < 0.06 and z > 1.5:
        return Confidence.MEDIUM
    if disagreement > 0.06:
        return Confidence.LOW
    return Confidence.LOW
