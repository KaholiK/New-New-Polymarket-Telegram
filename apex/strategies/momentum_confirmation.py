"""SECONDARY FILTER ONLY — never generates standalone signals.

Confirms or weakens other strategies' signals based on recent price trend.
"""

from __future__ import annotations

from apex.core.models import Market, Signal
from apex.strategies.base import BaseStrategy, DataContext


class MomentumConfirmationStrategy(BaseStrategy):
    name = "momentum_confirmation"

    async def signal(self, market: Market, context: DataContext) -> Signal | None:
        # Explicitly never returns a standalone signal
        return None

    def confirm(self, incoming: Signal, recent_trend: float) -> float:
        """Return a multiplier to the incoming signal's score.

        recent_trend > 0 means Polymarket price rose recently (YES strengthening).
        If trend agrees with incoming side → slight boost (1.10). Disagrees → slight dampen (0.90).
        """
        if incoming.side.value == "YES":
            return 1.10 if recent_trend > 0 else 0.90
        return 1.10 if recent_trend < 0 else 0.90

    def explain(self) -> list[str]:
        return [
            "Secondary filter only — never originates signals.",
            "Boosts or dampens other strategies' scores based on short-term price trend.",
        ]

    def required_freshness(self) -> dict[str, int]:
        return {}
