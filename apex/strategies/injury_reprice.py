"""Fast repricing when injury/lineup status changes."""

from __future__ import annotations

from apex.config import get_settings
from apex.core.models import Confidence, Market, Side, Signal
from apex.quant.models.injury_adjuster import compute_team_impact
from apex.strategies.base import BaseStrategy, DataContext


class InjuryRepriceStrategy(BaseStrategy):
    name = "injury_reprice"

    MIN_IMPACT = 0.025

    async def signal(self, market: Market, context: DataContext) -> Signal | None:
        _ = get_settings()
        fc = context.forecast
        if fc is None:
            return None
        if not self.freshness_ok(context):
            return None
        if not context.fresh_injuries:
            return None

        home_impact = compute_team_impact(
            fc.sport.value, fc.home_team, context.fresh_injuries
        ).total_impact
        away_impact = compute_team_impact(
            fc.sport.value, fc.away_team, context.fresh_injuries
        ).total_impact
        delta = away_impact - home_impact
        if abs(delta) < self.MIN_IMPACT:
            return None

        side = Side.YES if delta > 0 else Side.NO
        return Signal(
            strategy=self.name,
            market_id=market.condition_id,
            event_id=fc.event_id,
            side=side,
            size_hint_usd=0.0,
            edge=abs(delta),
            edge_zscore=fc.edge_zscore,
            confidence=Confidence.MEDIUM,
            urgency=0.8,
            forecast=fc,
            explanation=[
                f"home injury impact {home_impact:.3f}, away {away_impact:.3f}",
                f"net prob shift {delta:+.3f}",
            ],
            required_freshness_ok=True,
        )

    def explain(self) -> list[str]:
        return [
            "Fires immediately on new injury status that materially shifts probability.",
            f"Requires net impact ≥ {self.MIN_IMPACT:.2f}.",
        ]

    def required_freshness(self) -> dict[str, int]:
        s = get_settings()
        return {"polymarket": s.polymarket_max_age, "injuries": s.injury_max_age}
