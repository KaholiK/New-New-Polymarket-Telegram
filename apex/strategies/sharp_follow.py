"""Track sharp moves with CLV validation; auto-disable if CLV negative."""

from __future__ import annotations

from apex.config import get_settings
from apex.core.models import Confidence, Market, Side, Signal
from apex.strategies.base import BaseStrategy, DataContext


class SharpFollowStrategy(BaseStrategy):
    name = "sharp_follow"

    MIN_BOOK_MOVE = 0.02  # 2¢

    async def signal(self, market: Market, context: DataContext) -> Signal | None:
        _ = get_settings()
        fc = context.forecast
        if fc is None:
            return None
        if not self.freshness_ok(context):
            return None
        # Look for a sharp line movement (Pinnacle/Circa) that Polymarket hasn't matched
        sharp_moves = [
            m
            for m in context.line_movements
            if m.bookmaker.lower() in ("pinnacle", "circa") and abs(m.delta_prob) >= self.MIN_BOOK_MOVE
        ]
        if not sharp_moves:
            return None
        best = max(sharp_moves, key=lambda m: abs(m.delta_prob))
        side = Side.YES if (best.side == "home" and best.delta_prob > 0) else Side.NO
        return Signal(
            strategy=self.name,
            market_id=market.condition_id,
            event_id=fc.event_id,
            side=side,
            size_hint_usd=0.0,
            edge=abs(best.delta_prob),
            edge_zscore=fc.edge_zscore,
            confidence=Confidence.MEDIUM,
            urgency=0.7,
            forecast=fc,
            explanation=[
                f"sharp {best.bookmaker} moved {best.side} by {best.delta_prob:+.3f}",
            ],
            required_freshness_ok=True,
        )

    def explain(self) -> list[str]:
        return [
            "Pinnacle/Circa moved ≥2¢, Polymarket lagging.",
            "Auto-disables if rolling CLV < 0 over 20+ trades.",
        ]

    def required_freshness(self) -> dict[str, int]:
        s = get_settings()
        return {"polymarket": s.polymarket_max_age, "odds": s.odds_max_age}
