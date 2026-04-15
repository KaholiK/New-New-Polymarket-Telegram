"""Late edge before game start — very strict freshness."""

from __future__ import annotations

from apex.config import get_settings
from apex.core.models import Confidence, Market, Signal
from apex.strategies.base import BaseStrategy, DataContext
from apex.utils.time_utils import minutes_until


class PrelockRepriceStrategy(BaseStrategy):
    name = "prelock_reprice"

    MIN_Z = 2.0
    FRESHNESS_WINDOW_S = 120  # 2 min for all sources
    MAX_MINUTES_TO_START = 60.0

    async def signal(self, market: Market, context: DataContext) -> Signal | None:
        _ = get_settings()
        fc = context.forecast
        if fc is None or market.end_date is None:
            return None
        mins = minutes_until(market.end_date)
        if mins > self.MAX_MINUTES_TO_START or mins < 0:
            return None
        if fc.confidence != Confidence.HIGH:
            return None
        if abs(fc.edge_zscore) < self.MIN_Z:
            return None
        # Strict freshness requirement
        for age in context.source_ages.values():
            if age > self.FRESHNESS_WINDOW_S:
                return None
        return Signal(
            strategy=self.name,
            market_id=market.condition_id,
            event_id=fc.event_id,
            side=fc.side,
            size_hint_usd=0.0,
            edge=fc.raw_edge,
            edge_zscore=fc.edge_zscore,
            confidence=Confidence.HIGH,
            urgency=1.0,
            forecast=fc,
            explanation=[f"edge {fc.raw_edge:+.3f} z={fc.edge_zscore:+.2f}, {mins:.0f}m to start"],
            required_freshness_ok=True,
        )

    def explain(self) -> list[str]:
        return [
            f"Edge detected within {self.MAX_MINUTES_TO_START:.0f} min of game start.",
            f"Extra strict: all data <{self.FRESHNESS_WINDOW_S}s, confidence HIGH, z>{self.MIN_Z}.",
        ]

    def required_freshness(self) -> dict[str, int]:
        # Self-enforces stricter window above
        return {"polymarket": self.FRESHNESS_WINDOW_S, "odds": self.FRESHNESS_WINDOW_S}
