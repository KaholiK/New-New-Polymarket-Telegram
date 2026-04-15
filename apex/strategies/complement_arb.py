"""YES + NO ask sum anomaly scanner."""

from __future__ import annotations

from apex.config import get_settings
from apex.core.models import Confidence, Market, Side, Signal
from apex.strategies.base import BaseStrategy, DataContext


class ComplementArbStrategy(BaseStrategy):
    name = "complement_arb"

    ARB_THRESHOLD = 0.98

    async def signal(self, market: Market, context: DataContext) -> Signal | None:
        _ = get_settings()
        fc = context.forecast
        yes_book = context.orderbook_yes
        no_book = context.orderbook_no
        if fc is None or yes_book is None or no_book is None:
            return None
        if not self.freshness_ok(context):
            return None
        # YES ask + NO ask < 0.98 → theoretical free money
        yes_ask = yes_book.best_ask
        no_ask = no_book.best_ask
        if yes_ask <= 0 or no_ask <= 0:
            return None
        total = yes_ask + no_ask
        if total >= self.ARB_THRESHOLD:
            return None
        # Also require some depth on both sides to avoid one-level phantoms
        yes_depth = sum(lvl.size for lvl in yes_book.asks[:3])
        no_depth = sum(lvl.size for lvl in no_book.asks[:3])
        if yes_depth < 50 or no_depth < 50:
            return None
        return Signal(
            strategy=self.name,
            market_id=market.condition_id,
            event_id=fc.event_id,
            side=Side.YES,  # caller orchestrates both sides
            size_hint_usd=0.0,
            edge=1.0 - total,
            edge_zscore=fc.edge_zscore,
            confidence=Confidence.HIGH,
            urgency=0.95,
            forecast=fc,
            explanation=[
                f"YES ask {yes_ask:.3f} + NO ask {no_ask:.3f} = {total:.3f} (< {self.ARB_THRESHOLD})",
            ],
            required_freshness_ok=True,
        )

    def explain(self) -> list[str]:
        return [
            "YES + NO ask < 0.98. Requires simultaneous execution on both sides.",
            "Only fires if both sides have adequate depth.",
        ]

    def required_freshness(self) -> dict[str, int]:
        s = get_settings()
        return {"polymarket": s.polymarket_max_age}
