"""3+ books move same direction within 5 min."""

from __future__ import annotations

from apex.config import get_settings
from apex.core.models import Confidence, Market, Side, Signal
from apex.strategies.base import BaseStrategy, DataContext


class SteamMoveStrategy(BaseStrategy):
    name = "steam_move"

    async def signal(self, market: Market, context: DataContext) -> Signal | None:
        _ = get_settings()
        fc = context.forecast
        if fc is None:
            return None
        if not self.freshness_ok(context):
            return None
        if not context.steam_moves:
            return None
        best = max(context.steam_moves, key=lambda x: x.total_delta_prob)
        if best.books_moved < 3:
            return None
        side = Side.YES if best.side == "home" else Side.NO
        return Signal(
            strategy=self.name,
            market_id=market.condition_id,
            event_id=fc.event_id,
            side=side,
            size_hint_usd=0.0,
            edge=best.total_delta_prob,
            edge_zscore=fc.edge_zscore,
            confidence=Confidence.MEDIUM,
            urgency=0.95,  # high urgency — taker execution
            forecast=fc,
            explanation=[
                f"{best.books_moved} books moved {best.side} by {best.total_delta_prob:.3f}",
                f"window {best.window_seconds:.0f}s",
            ],
            required_freshness_ok=True,
        )

    def explain(self) -> list[str]:
        return [
            "3+ sportsbooks moved ≥2¢ same direction within 5 min.",
            "High urgency (taker execution), signal decays after 20 min.",
        ]

    def required_freshness(self) -> dict[str, int]:
        s = get_settings()
        return {"polymarket": s.polymarket_max_age, "odds": s.odds_max_age}
