"""Quant math: odds conversion, vig removal, Kelly, EV, probability clamping.

Every probability entering or leaving a model must go through clamp_prob() to avoid
log(0), division by zero, and absurd Kelly sizes at the boundaries.
"""

from __future__ import annotations

import math

# Hard floor/ceiling for probabilities — prevents log(0) and infinite Kelly
PROB_FLOOR = 0.001
PROB_CEIL = 0.999


def clamp_prob(p: float) -> float:
    """Clamp probability to [PROB_FLOOR, PROB_CEIL]."""
    if p != p:  # NaN
        return 0.5
    return max(PROB_FLOOR, min(PROB_CEIL, float(p)))


def american_to_decimal(american: float) -> float:
    """American odds to decimal. -110 → 1.909, +150 → 2.50."""
    american = float(american)
    if american == 0:
        raise ValueError("American odds cannot be 0")
    if american > 0:
        return 1.0 + american / 100.0
    return 1.0 + 100.0 / abs(american)


def decimal_to_american(decimal: float) -> float:
    """Decimal odds to American. 2.0 → +100, 1.5 → -200."""
    decimal = float(decimal)
    if decimal <= 1.0:
        raise ValueError(f"Decimal odds must be > 1.0, got {decimal}")
    if decimal >= 2.0:
        return round((decimal - 1.0) * 100.0)
    return round(-100.0 / (decimal - 1.0))


def implied_prob_from_decimal(decimal: float) -> float:
    """Implied probability from decimal odds (raw, includes vig). 2.0 → 0.5."""
    if decimal <= 1.0:
        raise ValueError(f"Decimal odds must be > 1.0, got {decimal}")
    return clamp_prob(1.0 / decimal)


def implied_prob_from_american(american: float) -> float:
    """Implied probability from American odds (raw, includes vig)."""
    return implied_prob_from_decimal(american_to_decimal(american))


def remove_vig_two_way(p_a_raw: float, p_b_raw: float) -> tuple[float, float]:
    """Normalize two-way raw implied probs by dividing by their sum.

    Simple but robust for binary markets. Returns (p_a_fair, p_b_fair).
    """
    s = p_a_raw + p_b_raw
    if s <= 0:
        return 0.5, 0.5
    return clamp_prob(p_a_raw / s), clamp_prob(p_b_raw / s)


def remove_vig_power(probs: list[float], tol: float = 1e-6, max_iter: int = 64) -> list[float]:
    """Power-method vig removal: find k so sum(p_i^k) = 1.

    More accurate than simple normalization for 3+ way markets. Bisects k in (0, 2].
    """
    if not probs:
        return []
    probs = [max(PROB_FLOOR, min(PROB_CEIL, float(p))) for p in probs]
    if abs(sum(probs) - 1.0) < tol:
        return probs

    lo, hi = 0.001, 10.0
    for _ in range(max_iter):
        k = (lo + hi) / 2.0
        s = sum(p**k for p in probs)
        if abs(s - 1.0) < tol:
            break
        if s > 1.0:
            lo = k
        else:
            hi = k
    return [clamp_prob(p**k) for p in probs]


def kelly_fraction(p: float, decimal_odds: float) -> float:
    """Full Kelly fraction. Returns max(0, edge / (odds-1))."""
    p = clamp_prob(p)
    if decimal_odds <= 1.0:
        return 0.0
    b = decimal_odds - 1.0
    q = 1.0 - p
    f = (b * p - q) / b
    return max(0.0, f)


def kelly_from_polymarket(p: float, yes_price: float) -> float:
    """Kelly fraction for Polymarket YES position where payout = 1.0.

    Polymarket pays $1.00 per YES share if YES wins. Buying at yes_price means:
    - Profit if YES wins: 1 - yes_price per $yes_price staked → decimal_odds = 1/yes_price
    """
    if yes_price <= 0.0 or yes_price >= 1.0:
        return 0.0
    decimal_odds = 1.0 / yes_price
    return kelly_fraction(p, decimal_odds)


def expected_value(p: float, decimal_odds: float, stake: float = 1.0) -> float:
    """EV of a bet with win prob p and decimal odds. Negative = losing bet in expectation."""
    p = clamp_prob(p)
    win = (decimal_odds - 1.0) * stake
    lose = -stake
    return p * win + (1.0 - p) * lose


def ev_polymarket(true_prob: float, yes_price: float, size_usd: float) -> float:
    """Expected USD profit buying YES at yes_price with size_usd stake.

    Contracts bought = size_usd / yes_price. Each contract pays $1 if YES wins.
    """
    if yes_price <= 0.0 or yes_price >= 1.0 or size_usd <= 0:
        return 0.0
    contracts = size_usd / yes_price
    payout_if_win = contracts * 1.0
    profit_if_win = payout_if_win - size_usd
    profit_if_loss = -size_usd
    p = clamp_prob(true_prob)
    return p * profit_if_win + (1.0 - p) * profit_if_loss


def polymarket_edge(true_prob: float, yes_price: float) -> float:
    """Raw probability edge when buying YES at yes_price."""
    return clamp_prob(true_prob) - clamp_prob(yes_price)


def brier_score(prob: float, outcome: int) -> float:
    """Brier score for single forecast. outcome ∈ {0, 1}."""
    if outcome not in (0, 1):
        raise ValueError(f"outcome must be 0 or 1, got {outcome}")
    p = clamp_prob(prob)
    return (p - outcome) ** 2


def log_loss(prob: float, outcome: int) -> float:
    """Binary log-loss for single forecast."""
    if outcome not in (0, 1):
        raise ValueError(f"outcome must be 0 or 1, got {outcome}")
    p = clamp_prob(prob)
    if outcome == 1:
        return -math.log(p)
    return -math.log(1.0 - p)


def geometric_mean_odds(probs: list[float], weights: list[float] | None = None) -> float:
    """Log-linear pool (geometric mean of odds) of multiple probabilities.

    Numerically stable; clamps inputs; normalizes weights.
    """
    if not probs:
        return 0.5
    probs = [clamp_prob(p) for p in probs]
    if weights is None:
        weights = [1.0] * len(probs)
    if len(weights) != len(probs):
        raise ValueError("weights and probs must be same length")
    w_sum = sum(weights)
    if w_sum <= 0:
        weights = [1.0] * len(probs)
        w_sum = float(len(probs))
    norm_w = [w / w_sum for w in weights]

    # log odds pool: log(p/(1-p))
    log_odds = sum(w * math.log(p / (1.0 - p)) for p, w in zip(probs, norm_w))
    # back to probability
    p = 1.0 / (1.0 + math.exp(-log_odds))
    return clamp_prob(p)


def z_score(x: float, mean: float, std: float) -> float:
    """Z-score with safe zero std handling."""
    if std <= 0:
        return 0.0
    return (x - mean) / std


def sigmoid(x: float) -> float:
    """Numerically stable sigmoid."""
    if x >= 0:
        z = math.exp(-x)
        return 1.0 / (1.0 + z)
    z = math.exp(x)
    return z / (1.0 + z)
