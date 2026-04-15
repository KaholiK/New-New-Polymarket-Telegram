"""Sharp books moved, Polymarket hasn't followed — divergence opportunity."""

from __future__ import annotations

from apex.config import get_settings
from apex.core.models import Confidence, Market, Side, Signal
from apex.strategies.base import BaseStrategy, DataContext


class BookDivergenceStrategy(BaseStrategy):
    name = "book_divergence"

    MIN_DIVERGENCE = 0.03  # 3¢

    async def signal(self, market: Market, context: DataContext) -> Signal | None:
        _ = get_settings()
        fc = context.forecast
        if fc is None or context.sharp_consensus is None:
            return None
        if not self.freshness_ok(context):
            return None
        cons = context.sharp_consensus
        # cons.home_prob is sportsbook fair-value for home
        polymarket_yes = market.yes_price
        divergence = abs(cons.home_prob - polymarket_yes)
        if divergence < self.MIN_DIVERGENCE:
            return None
        side = Side.YES if cons.home_prob > polymarket_yes else Side.NO
        explanation = [
            f"sharp cons {cons.home_prob:.3f} vs polymarket {polymarket_yes:.3f}",
            f"divergence {divergence:.3f}",
        ]
        return Signal(
            strategy=self.name,
            market_id=market.condition_id,
            event_id=fc.event_id,
            side=side,
            size_hint_usd=0.0,
            edge=divergence,
            edge_zscore=fc.edge_zscore,
            confidence=Confidence.MEDIUM if divergence > 0.05 else Confidence.LOW,
            urgency=0.5,
            forecast=fc,
            explanation=explanation,
            required_freshness_ok=True,
        )

    def explain(self) -> list[str]:
        return [
            "Polymarket price lagging sharp sportsbook consensus by ≥3¢.",
            "Signal fades if Polymarket catches up within 10 minutes.",
        ]

    def required_freshness(self) -> dict[str, int]:
        s = get_settings()
        return {"polymarket": s.polymarket_max_age, "odds": s.odds_max_age}
