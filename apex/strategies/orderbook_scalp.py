"""Wide spread capture, maker-only, strict liquidity gate."""

from __future__ import annotations

from apex.config import get_settings
from apex.core.models import Confidence, Market, Side, Signal
from apex.strategies.base import BaseStrategy, DataContext


class OrderbookScalpStrategy(BaseStrategy):
    name = "orderbook_scalp"

    MIN_SPREAD = 0.05
    MIN_DEPTH_USD = 500.0

    async def signal(self, market: Market, context: DataContext) -> Signal | None:
        _ = get_settings()
        fc = context.forecast
        book = context.orderbook_yes
        if fc is None or book is None:
            return None
        if not self.freshness_ok(context):
            return None
        if book.spread < self.MIN_SPREAD:
            return None
        # Depth check: $500 on both sides within 2¢ of mid
        mid = book.mid
        bid_depth = sum(lvl.size * lvl.price for lvl in book.bids if lvl.price >= mid - 0.02)
        ask_depth = sum(lvl.size * lvl.price for lvl in book.asks if lvl.price <= mid + 0.02)
        if min(bid_depth, ask_depth) < self.MIN_DEPTH_USD:
            return None
        return Signal(
            strategy=self.name,
            market_id=market.condition_id,
            event_id=fc.event_id,
            side=Side.YES,
            size_hint_usd=0.0,
            edge=book.spread / 2.0,
            edge_zscore=fc.edge_zscore,
            confidence=Confidence.LOW,
            urgency=0.1,  # maker, no rush
            forecast=fc,
            explanation=[
                f"spread {book.spread:.3f}, bid_depth ${bid_depth:.0f}, ask_depth ${ask_depth:.0f}",
            ],
            required_freshness_ok=True,
        )

    def explain(self) -> list[str]:
        return [
            "Wide spread scalp (≥5¢) with ≥$500 depth on both sides.",
            "Maker-only; cancel if spread narrows below 3¢.",
            "Disabled by default until real liquidity is observed.",
        ]

    def required_freshness(self) -> dict[str, int]:
        s = get_settings()
        return {"polymarket": s.polymarket_max_age}
