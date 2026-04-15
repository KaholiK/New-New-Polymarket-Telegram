"""Fresh news + quantified impact via injury_adjuster."""

from __future__ import annotations

from apex.config import get_settings
from apex.core.models import Confidence, Market, Side, Signal
from apex.quant.models.injury_adjuster import lookup_player
from apex.strategies.base import BaseStrategy, DataContext
from apex.utils.time_utils import age_seconds


class NewsShockStrategy(BaseStrategy):
    name = "news_shock"

    MAX_NEWS_AGE = 900  # 15 min
    MIN_QUANTIFIED_IMPACT = 0.03

    async def signal(self, market: Market, context: DataContext) -> Signal | None:
        _ = get_settings()
        fc = context.forecast
        if fc is None:
            return None
        if not self.freshness_ok(context):
            return None

        # Find fresh news referencing either team
        if not context.fresh_news:
            return None
        relevant = []
        for item in context.fresh_news:
            if age_seconds(item.published_at) > self.MAX_NEWS_AGE:
                continue
            tokens = (fc.home_team or "").lower(), (fc.away_team or "").lower()
            headline_l = item.headline.lower()
            if any(tok and tok in headline_l for tok in tokens):
                relevant.append(item)
            elif any(any(tok in (t or "").lower() for tok in tokens) for t in item.teams):
                relevant.append(item)
        if not relevant:
            return None

        # Quantify impact: did a curated player appear in headline?
        quantified_impact = 0.0
        evidence: list[str] = []
        for item in relevant:
            # Rough: look up any top player name in headline
            headline_lower = item.headline.lower()
            for key in headline_lower.split():
                hit = lookup_player(key, fc.sport.value)
                if hit is None:
                    continue
                team, tier = hit
                from apex.quant.models.injury_adjuster import PLAYER_IMPACT

                base = PLAYER_IMPACT.get(fc.sport.value, {}).get(tier, 0.0)
                # News is typically a status change — assume QUESTIONABLE → OUT style
                quantified_impact = max(quantified_impact, base)
                evidence.append(f"{key} ({tier}) in news")
                break

        if quantified_impact < self.MIN_QUANTIFIED_IMPACT:
            return None

        # Direction: if impact is on home team, signal NO (home loses prob)
        side = Side.NO  # conservative default
        return Signal(
            strategy=self.name,
            market_id=market.condition_id,
            event_id=fc.event_id,
            side=side,
            size_hint_usd=0.0,
            edge=quantified_impact,
            edge_zscore=fc.edge_zscore,
            confidence=Confidence.MEDIUM,
            urgency=0.9,  # news is time-sensitive
            forecast=fc,
            explanation=[f"fresh news impact {quantified_impact:+.3f}"] + evidence,
            required_freshness_ok=True,
        )

    def explain(self) -> list[str]:
        return [
            "Fires when fresh (<15 min) news references a top player and the quantified",
            "impact exceeds 3% probability. Market expected to reprice quickly.",
        ]

    def required_freshness(self) -> dict[str, int]:
        s = get_settings()
        return {"polymarket": s.polymarket_max_age, "news": s.news_max_age}
