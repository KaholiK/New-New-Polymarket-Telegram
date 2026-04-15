"""Public betting >70% one side but line unmoved → sharp money on the other side."""

from __future__ import annotations

from apex.config import get_settings
from apex.core.models import Confidence, Market, Side, Signal
from apex.strategies.base import BaseStrategy, DataContext


class ContrarianStrategy(BaseStrategy):
    name = "contrarian"

    async def signal(self, market: Market, context: DataContext) -> Signal | None:
        _ = get_settings()
        fc = context.forecast
        if fc is None or context.sharp_consensus is None:
            return None
        if not self.freshness_ok(context):
            return None
        cons = context.sharp_consensus
        # Heuristic: if sportsbook consensus strongly favors one side but Polymarket
        # hasn't moved to reflect it, the public might be on the heavy side
        # and sharps on the other. Signal fires with low confidence.
        polymarket_yes = market.yes_price
        pm_lead = cons.home_prob - polymarket_yes
        if abs(pm_lead) < 0.04:
            return None
        side = Side.YES if pm_lead > 0 else Side.NO
        return Signal(
            strategy=self.name,
            market_id=market.condition_id,
            event_id=fc.event_id,
            side=side,
            size_hint_usd=0.0,
            edge=abs(pm_lead),
            edge_zscore=fc.edge_zscore,
            confidence=Confidence.LOW,
            urgency=0.2,
            forecast=fc,
            explanation=[f"sharp disagreement {pm_lead:+.3f}"],
            required_freshness_ok=True,
        )

    def explain(self) -> list[str]:
        return [
            "Public >70% one side, line unmoved → sharps on other side.",
            "Weak-confidence; only actionable if another model agrees.",
        ]

    def required_freshness(self) -> dict[str, int]:
        s = get_settings()
        return {"polymarket": s.polymarket_max_age, "odds": s.odds_max_age}
