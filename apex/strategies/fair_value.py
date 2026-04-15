"""Fair-value strategy: ensemble forecast vs Polymarket price, z-score gated."""

from __future__ import annotations

from apex.config import get_settings
from apex.core.models import Confidence, Market, Side, Signal
from apex.strategies.base import BaseStrategy, DataContext


class FairValueStrategy(BaseStrategy):
    name = "fair_value"

    MIN_EDGE_ZSCORE = 1.5
    MIN_EDGE_AFTER_COSTS = 0.02

    async def signal(self, market: Market, context: DataContext) -> Signal | None:
        # Call settings dynamically so tests can monkeypatch (no lru_cache).
        _ = get_settings()
        fc = context.forecast
        if fc is None:
            return None
        # Skip single-team futures — Elo / power ratings / Poisson all need a real
        # head-to-head matchup. Confidence can be artificially high on these.
        if not fc.home_team or not fc.away_team:
            return None
        if fc.confidence not in (Confidence.HIGH, Confidence.MEDIUM):
            return None
        if abs(fc.edge_zscore) < self.MIN_EDGE_ZSCORE:
            return None
        if fc.edge_after_costs <= self.MIN_EDGE_AFTER_COSTS:
            return None
        if not self.freshness_ok(context):
            return None

        side: Side = fc.side
        explanation = list(fc.key_factors or [])
        explanation.append(f"edge {fc.raw_edge:+.3f} z={fc.edge_zscore:+.2f}")

        return Signal(
            strategy=self.name,
            market_id=market.condition_id,
            event_id=fc.event_id,
            side=side,
            size_hint_usd=0.0,  # sizing happens in risk engine
            edge=fc.raw_edge,
            edge_zscore=fc.edge_zscore,
            confidence=fc.confidence,
            urgency=0.3,
            forecast=fc,
            explanation=explanation,
            required_freshness_ok=True,
        )

    def explain(self) -> list[str]:
        return [
            "Compares ensemble probability to Polymarket price.",
            f"Requires edge z-score ≥ {self.MIN_EDGE_ZSCORE} and confidence ≥ medium.",
            f"Requires edge-after-costs > {self.MIN_EDGE_AFTER_COSTS:.2f}.",
        ]

    def required_freshness(self) -> dict[str, int]:
        s = get_settings()
        return {"polymarket": s.polymarket_max_age, "odds": s.odds_max_age}
