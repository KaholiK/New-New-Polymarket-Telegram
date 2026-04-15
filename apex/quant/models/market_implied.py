"""Extract denoised probability from Polymarket + sportsbook odds."""

from __future__ import annotations

from apex.core.models import Market, ModelEstimate
from apex.data.consensus_builder import Consensus
from apex.utils.math_utils import clamp_prob, remove_vig_two_way


def polymarket_implied_prob(market: Market) -> float:
    """Denoised YES prob from Polymarket: yes / (yes + no)."""
    y, n = market.yes_price, market.no_price
    s = y + n
    if s <= 0:
        return 0.5
    return clamp_prob(y / s)


class MarketImpliedModel:
    """Combines Polymarket price with sharp-weighted sportsbook consensus."""

    def __init__(self, polymarket_weight: float = 0.5, book_weight: float = 0.5) -> None:
        self.polymarket_weight = polymarket_weight
        self.book_weight = book_weight

    def predict(
        self,
        market: Market,
        consensus: Consensus | None = None,
        market_is_home: bool = True,
    ) -> float:
        """Blend Polymarket implied with sportsbook consensus (if available)."""
        pm = polymarket_implied_prob(market)
        if consensus is None:
            return pm
        sb = consensus.home_prob if market_is_home else consensus.away_prob
        # Two-way vig removal across the two sources
        total_w = self.polymarket_weight + self.book_weight
        p = (pm * self.polymarket_weight + sb * self.book_weight) / total_w
        return clamp_prob(p)

    def predict_estimate(
        self,
        market: Market,
        consensus: Consensus | None = None,
        market_is_home: bool = True,
    ) -> ModelEstimate:
        pm = polymarket_implied_prob(market)
        p = self.predict(market, consensus, market_is_home)
        factors: list[str] = [f"Polymarket implied {pm:.3f}"]
        if consensus is not None:
            sb = consensus.home_prob if market_is_home else consensus.away_prob
            factors.append(f"Sharp consensus {sb:.3f} ({consensus.book_count} books)")
        uncertainty = 0.03 if consensus is not None else 0.05
        confidence = 0.75 if consensus is not None else 0.6
        return ModelEstimate(
            model_name="market_implied",
            probability=p,
            uncertainty=uncertainty,
            confidence=confidence,
            factors=factors,
        )


def remove_vig_market(yes_price: float, no_price: float) -> tuple[float, float]:
    """Shortcut wrapper around two-way vig removal for Polymarket."""
    return remove_vig_two_way(yes_price, no_price)
