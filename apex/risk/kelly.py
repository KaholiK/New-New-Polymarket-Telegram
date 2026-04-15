"""Shrunk fractional Kelly using lower CI bound for edge."""

from __future__ import annotations

from apex.config import get_settings
from apex.utils.math_utils import clamp_prob, kelly_from_polymarket


def shrunk_edge(edge: float, edge_std: float) -> float:
    """Use edge_lower_bound = max(0, raw_edge - 1*std) for shrinkage."""
    return max(0.0, edge - edge_std)


def kelly_size(
    true_prob: float,
    yes_price: float,
    edge_std: float,
    bankroll: float,
) -> tuple[float, float]:
    """Compute fractional-Kelly USD size. Returns (kelly_frac, size_usd).

    Shrinks the edge by its std (1σ lower bound), then applies a Kelly fraction
    (smaller for small bankrolls).
    """
    if bankroll <= 0 or yes_price <= 0 or yes_price >= 1:
        return 0.0, 0.0
    s = get_settings()
    # Raw edge implied by true_prob and yes_price
    raw_edge = clamp_prob(true_prob) - clamp_prob(yes_price)
    if raw_edge <= 0:
        return 0.0, 0.0
    # Shrink edge → adjust true_prob downward
    adjusted_edge = shrunk_edge(raw_edge, edge_std)
    if adjusted_edge <= 0:
        return 0.0, 0.0
    adjusted_prob = clamp_prob(yes_price + adjusted_edge)
    full_kelly = kelly_from_polymarket(adjusted_prob, yes_price)
    fraction = (
        s.kelly_fraction_small_bankroll if bankroll < s.small_bankroll_threshold else s.kelly_fraction
    )
    k = full_kelly * fraction
    return k, k * bankroll
