"""Multi-factor signal scoring 0-100.

Weights by component (sum of max contributions = 110, decision threshold is 60/40).
Penalties reduce the score below 0 if stacked.
"""

from __future__ import annotations

from apex.core.models import Confidence, Signal

STRATEGY_PRIORITY: dict[str, int] = {
    "fair_value": 10,
    "news_shock": 9,
    "injury_reprice": 9,
    "steam_move": 8,
    "prelock_reprice": 8,
    "sharp_follow": 7,
    "complement_arb": 8,
    "book_divergence": 6,
    "contrarian": 5,
    "orderbook_scalp": 5,
    "momentum_confirmation": 0,
}


def score_edge_zscore(z: float) -> float:
    """0-25 pts. Cap at |z|=5."""
    z_abs = min(5.0, abs(z))
    return (z_abs / 5.0) * 25.0


def score_confidence(conf: Confidence) -> float:
    """0-20 pts."""
    mapping = {
        Confidence.HIGH: 20.0,
        Confidence.MEDIUM: 12.0,
        Confidence.LOW: 5.0,
        Confidence.NO_OPINION: 0.0,
    }
    return mapping.get(conf, 0.0)


def score_liquidity(volume: float, liquidity: float) -> float:
    """0-15 pts — logarithmic in volume."""
    import math

    if volume <= 0 and liquidity <= 0:
        return 0.0
    combined = max(1.0, volume + liquidity * 10.0)
    # log10(combined) at $1k → 3, at $100k → 5, at $10M → 7
    norm = min(1.0, (math.log10(combined) - 2.0) / 5.0)
    return max(0.0, min(15.0, norm * 15.0))


def score_freshness(freshness: float) -> float:
    """0-15 pts — linear in freshness ∈ [0,1]."""
    return max(0.0, min(1.0, freshness)) * 15.0


def score_priority(strategy: str) -> float:
    """0-10 pts."""
    return float(STRATEGY_PRIORITY.get(strategy, 5))


def score_urgency(urgency: float) -> float:
    """0-10 pts."""
    return max(0.0, min(1.0, urgency)) * 10.0


def correlation_penalty(existing_same_event: int, existing_same_sport: int) -> float:
    """-5 to -15 for existing exposure in same sport/event."""
    penalty = 0.0
    if existing_same_event > 0:
        penalty -= 15.0
    elif existing_same_sport > 2:
        penalty -= 10.0
    elif existing_same_sport > 0:
        penalty -= 5.0
    return penalty


def stale_data_penalty(freshness: float) -> float:
    if freshness >= 0.9:
        return 0.0
    if freshness >= 0.6:
        return -10.0
    return -20.0


def mapping_penalty(mapping_confidence: float) -> float:
    if mapping_confidence >= 0.85:
        return 0.0
    if mapping_confidence >= 0.70:
        return -5.0
    return -15.0


def score_signal(
    signal: Signal,
    volume: float,
    liquidity: float,
    data_freshness: float,
    mapping_confidence: float,
    existing_same_event: int = 0,
    existing_same_sport: int = 0,
) -> tuple[float, dict[str, float], dict[str, float]]:
    """Return (total_score, positive_components, penalty_components)."""
    comps = {
        "edge_zscore": score_edge_zscore(signal.edge_zscore),
        "confidence": score_confidence(signal.confidence),
        "liquidity": score_liquidity(volume, liquidity),
        "freshness": score_freshness(data_freshness),
        "priority": score_priority(signal.strategy),
        "urgency": score_urgency(signal.urgency),
    }
    penalties = {
        "correlation": correlation_penalty(existing_same_event, existing_same_sport),
        "stale_data": stale_data_penalty(data_freshness),
        "mapping": mapping_penalty(mapping_confidence),
    }
    total = sum(comps.values()) + sum(penalties.values())
    return total, comps, penalties
