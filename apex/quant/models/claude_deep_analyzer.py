"""Claude Deep Analyzer — MANDATORY 1-10 score before every trade.

No score → no trade. This is the final quality gate in the pipeline. Every mode
requires a minimum Claude score (SAFE=9, BALANCED=7, AGGRESSIVE=6, etc.).

The prompt sends Claude EVERYTHING available: quant models, odds, injuries, news,
line movement, historical CLV, recent win rate. Claude returns strict JSON with
a 1-10 score and reasoning.

Cost protection:
- SAFE mode: unlimited calls (few candidates reach this stage anyway)
- AGGRESSIVE mode: capped at 50 calls/day to prevent waste on low-quality candidates
- All modes: pre-call budget check via CostTracker
"""

from __future__ import annotations

import json
import re
from typing import Any

from apex.core.models import Forecast, Market
from apex.quant.calibration.cost_tracker import CostTracker, estimate_cost_usd
from apex.utils.logger import get_logger
from apex.utils.math_utils import clamp_prob

logger = get_logger(__name__)

DEEP_SYSTEM_PROMPT = """You are the final decision gate for APEX, a Polymarket prediction-market \
trading bot. For every potential trade, you receive comprehensive data from our quant models, \
sportsbooks, news feeds, and market data. You must return a 1-10 score and analysis.

RESPOND WITH ONLY A JSON OBJECT — no markdown, no commentary:

{
  "score": <integer 1-10>,
  "probability": <float 0.01-0.99 — YOUR independent probability estimate>,
  "confidence": "high" | "medium" | "low",
  "reasoning": "<2-3 sentences, max 80 words>",
  "key_factors_for": ["<factor 1>", "<factor 2>", "<factor 3>"],
  "key_factors_against": ["<factor 1>", "<factor 2>"],
  "recommended_size_multiplier": <float 0.5-1.5>,
  "warnings": ["<warning if any, else empty list>"]
}

Score guide:
  10: Near-certain edge. Multiple strong signals align. Market is clearly mispriced.
  9:  Very strong. High confidence, clear reasoning, good data quality.
  8:  Strong. Solid edge with minor uncertainties.
  7:  Good. Reasonable edge but some data gaps or model disagreement.
  6:  Marginal. Small edge, higher uncertainty. Only aggressive modes should take this.
  5:  Coinflip. No clear edge. DO NOT TRADE.
  1-4: Negative edge or serious red flags. REJECT.

Rules:
- Be calibrated. If our models say 55% and the market says 52%, that's a 3% edge — score ~6-7, not 9.
- Score 9-10 ONLY when edge is large (>5%), data is fresh, and multiple independent signals agree.
- For futures markets (single team, no H2H), be MORE conservative — score max 7 unless the mispricing is extreme.
- If data is stale (>10 min old), deduct 1-2 points.
- If models disagree significantly, deduct 1-2 points.
- recommended_size_multiplier: 0.5 for uncertain, 1.0 for normal, 1.5 for very high conviction.
- Include warnings for: stale data, low liquidity, correlated positions, event-specific risk.
"""


class ClaudeDeepAnalyzer:
    """Mandatory pre-trade analysis. Returns a 1-10 score or None on failure."""

    def __init__(
        self,
        api_key: str,
        model: str,
        cost_tracker: CostTracker,
        max_output_tokens: int = 500,
    ) -> None:
        self.api_key = (api_key or "").strip()
        self.model = model
        self.cost_tracker = cost_tracker
        self.max_output_tokens = max_output_tokens
        self._client: Any = None

        if self.api_key:
            try:
                from anthropic import AsyncAnthropic

                self._client = AsyncAnthropic(api_key=self.api_key)
            except Exception as exc:  # noqa: BLE001
                logger.warning("claude_deep: SDK init failed: %s", exc)

    @property
    def enabled(self) -> bool:
        return self._client is not None

    async def analyze(
        self,
        market: Market,
        forecast: Forecast,
        context: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Run deep analysis. Returns parsed JSON dict or None on failure.

        The dict always contains at minimum: {"score": int, "probability": float}.
        """
        if not self.enabled:
            return None

        est_cost = estimate_cost_usd(self.model, 1200, 250)
        if not await self.cost_tracker.can_spend(est_cost):
            logger.info("claude_deep: daily cap hit, skipping")
            return None

        prompt = _build_deep_prompt(market, forecast, context)

        try:
            response = await self._client.messages.create(
                model=self.model,
                max_tokens=self.max_output_tokens,
                system=[{"type": "text", "text": DEEP_SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
                messages=[{"role": "user", "content": prompt}],
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("claude_deep: API error: %s", exc)
            await self.cost_tracker.record(self.model, 0, 0, market_id=market.condition_id, ok=False)
            return None

        usage = getattr(response, "usage", None)
        in_tok = int(getattr(usage, "input_tokens", 0) or 0) if usage else 0
        out_tok = int(getattr(usage, "output_tokens", 0) or 0) if usage else 0
        await self.cost_tracker.record(self.model, in_tok, out_tok, market_id=market.condition_id, ok=True)

        text = ""
        for block in (response.content or []):
            if getattr(block, "type", None) == "text":
                text = str(block.text)
                break

        parsed = _parse_deep_json(text)
        if parsed is None:
            logger.warning("claude_deep: parse failed for %s: %s", market.condition_id, text[:200])
            return None

        # Validate score
        score = parsed.get("score")
        if not isinstance(score, (int, float)) or not (1 <= score <= 10):
            logger.warning("claude_deep: invalid score %s", score)
            return None

        parsed["score"] = int(score)
        parsed["probability"] = clamp_prob(float(parsed.get("probability", 0.5)))
        return parsed


def _build_deep_prompt(market: Market, forecast: Forecast, context: dict[str, Any]) -> str:
    """Assemble the comprehensive prompt with all available data."""
    sections = [
        f"MARKET: {market.question}",
        f"Sport/Category: {market.sport.value} · Type: {market.market_type.value}",
        f"Home: {market.home_team or '(single team)'} · Away: {market.away_team or '(futures)'}",
        f"Polymarket YES: {market.yes_price:.3f} · NO: {market.no_price:.3f}",
        f"Volume: ${market.volume:,.0f} · Liquidity: ${market.liquidity:,.0f}",
        "",
        "=== QUANT MODEL ESTIMATES ===",
    ]
    for name, est in forecast.model_estimates.items():
        sections.append(f"  {name}: prob={est.probability:.3f} ±{est.uncertainty:.3f} factors={est.factors[:3]}")
    sections.extend([
        f"\nEnsemble probability: {forecast.ensemble_prob:.3f} ± {forecast.ensemble_std:.3f}",
        f"Raw edge: {forecast.raw_edge:+.3f} (z-score: {forecast.edge_zscore:+.2f})",
        f"Confidence: {forecast.confidence.value}",
        f"Side: {forecast.side.value}",
        f"Kelly fraction: {forecast.kelly_fraction:.4f}",
    ])
    if forecast.rejection_reasons:
        sections.append(f"Rejection reasons from basic models: {forecast.rejection_reasons}")

    # Contextual data
    injuries = context.get("injuries", [])
    if injuries:
        sections.append("\n=== INJURIES (top 10) ===")
        for inj in injuries[:10]:
            if hasattr(inj, "player"):
                sections.append(f"  {inj.player} ({inj.team}) — {inj.status}")
            elif isinstance(inj, dict):
                sections.append(f"  {inj.get('player', '?')} ({inj.get('team', '?')}) — {inj.get('status', '?')}")

    odds_info = context.get("odds_summary", "")
    if odds_info:
        sections.append(f"\n=== SPORTSBOOK ODDS ===\n{odds_info}")

    news = context.get("news_headlines", [])
    if news:
        sections.append("\n=== RECENT NEWS ===")
        for h in news[:5]:
            sections.append(f"  • {h}")

    # Crypto-specific context
    crypto = context.get("crypto", {})
    if crypto:
        sections.append("\n=== CRYPTO DATA ===")
        for k, v in crypto.items():
            sections.append(f"  {k}: {v}")

    # Performance context
    perf = context.get("performance", {})
    if perf:
        sections.append("\n=== RECENT PERFORMANCE ===")
        sections.append(f"  Win rate (last 30): {perf.get('win_rate', 'N/A')}")
        sections.append(f"  CLV: {perf.get('clv', 'N/A')}")

    sections.append("\nReturn the JSON score object only.")
    return "\n".join(sections)


_JSON_RE = re.compile(r"\{[\s\S]*\}")


def _parse_deep_json(text: str) -> dict[str, Any] | None:
    if not text:
        return None
    try:
        obj = json.loads(text)
        if isinstance(obj, dict) and "score" in obj:
            return obj
    except (ValueError, TypeError):
        pass
    m = _JSON_RE.search(text)
    if not m:
        return None
    try:
        obj = json.loads(m.group(0))
        return obj if isinstance(obj, dict) and "score" in obj else None
    except (ValueError, TypeError):
        return None
