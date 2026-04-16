"""Claude-powered matchup analyzer.

This is the highest-weighted model in the ensemble when enabled — Claude has
deep context understanding that pure math models lack (rotations, injury
severity, momentum, rivalry dynamics, coach tendencies).

Cost discipline:
- Only called when at least one basic model already detects a raw edge above
  `anthropic_edge_threshold` (default 2%). The forecaster makes the gating decision;
  this module just runs the analysis when asked.
- Uses prompt caching on the system prompt so repeat calls for the same "shape"
  of market are cheaper.
- Records token usage via `CostTracker` before every call — hitting the daily
  cap causes `analyze` to return None and the forecaster falls back to the
  non-Claude ensemble.

The prompt asks Claude to return STRICT JSON so parsing is deterministic; we
ignore anything outside the JSON block.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from apex.core.models import InjuryNote, Market, ModelEstimate
from apex.quant.calibration.cost_tracker import CostTracker, estimate_cost_usd
from apex.utils.logger import get_logger
from apex.utils.math_utils import clamp_prob

logger = get_logger(__name__)


SYSTEM_PROMPT = """You are a world-class quantitative sports analyst helping a \
Polymarket prediction-market trading bot called APEX. For each matchup you receive, \
you must return a probability estimate and a terse factor list.

You MUST respond with a single JSON object — nothing else, no markdown fences, no \
commentary before or after. Schema:

{
  "home_win_probability": <float 0..1 — NOT the Polymarket price, YOUR estimate>,
  "confidence": <"high" | "medium" | "low">,
  "uncertainty": <float 0..0.2 — your 1-sigma spread, lower = more sure>,
  "key_factors": [<3 to 5 short factor strings, most impactful first>],
  "reasoning": "<one or two sentences, <= 60 words>"
}

Rules:
- Stay calibrated. If the basic models and market agree closely, your probability \
  should not swing wildly away from theirs.
- Clamp the probability to [0.01, 0.99].
- "high" confidence only when data quality is good AND there is a clear edge \
  vs. the Polymarket price.
- If the market is a futures/championship question (not a single head-to-head \
  game), treat "home_win_probability" as the probability of the referenced team \
  winning the referenced event, and be conservative.
- Never hallucinate facts about specific players. If the context omits key info, \
  return lower confidence.
"""


@dataclass
class _UsageEstimate:
    input_tokens: int = 0
    output_tokens: int = 0


class ClaudeAnalyzer:
    """Async wrapper around the Anthropic Python SDK.

    Constructor accepts the SDK lazily: if the `anthropic` package isn't
    installed or the API key is missing, `enabled` is False and `analyze`
    returns None without raising.
    """

    def __init__(
        self,
        api_key: str,
        model: str,
        cost_tracker: CostTracker,
        max_output_tokens: int = 400,
    ) -> None:
        self.api_key = (api_key or "").strip()
        self.model = model
        self.cost_tracker = cost_tracker
        self.max_output_tokens = max_output_tokens
        self._client: Any = None
        self._init_error: str | None = None

        if self.api_key:
            try:
                from anthropic import AsyncAnthropic  # type: ignore

                self._client = AsyncAnthropic(api_key=self.api_key)
            except Exception as exc:  # noqa: BLE001
                self._init_error = str(exc)
                logger.warning("claude_analyzer: SDK init failed: %s", exc)

    @property
    def enabled(self) -> bool:
        return self._client is not None

    async def analyze(
        self,
        market: Market,
        ensemble_prob_before: float,
        basic_factors: list[str],
        team_context: dict[str, Any] | None = None,
        injuries: list[InjuryNote] | None = None,
        odds_consensus: dict[str, Any] | None = None,
    ) -> ModelEstimate | None:
        """Run one Claude analysis. Returns a ModelEstimate or None on any failure.

        The returned ModelEstimate has model_name='claude' so the ensemble can
        weight it via `DEFAULT_WEIGHTS['claude']`.
        """
        if not self.enabled:
            return None

        # Rough pre-call budget check: ~800 in, ~150 out.
        est_cost = estimate_cost_usd(self.model, 800, 150)
        if not await self.cost_tracker.can_spend(est_cost):
            logger.info("claude_analyzer: daily cap hit, skipping")
            return None

        user_prompt = self._build_prompt(
            market=market,
            ensemble_prob_before=ensemble_prob_before,
            basic_factors=basic_factors,
            team_context=team_context or {},
            injuries=injuries or [],
            odds_consensus=odds_consensus or {},
        )

        try:
            response = await self._client.messages.create(
                model=self.model,
                max_tokens=self.max_output_tokens,
                system=[
                    {
                        "type": "text",
                        "text": SYSTEM_PROMPT,
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                messages=[{"role": "user", "content": user_prompt}],
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("claude_analyzer: API error: %s", exc)
            await self.cost_tracker.record(
                self.model, 0, 0, market_id=market.condition_id, ok=False
            )
            return None

        usage = self._extract_usage(response)
        await self.cost_tracker.record(
            self.model,
            usage.input_tokens,
            usage.output_tokens,
            market_id=market.condition_id,
            ok=True,
        )

        text = self._extract_text(response)
        parsed = _parse_json(text)
        if parsed is None:
            logger.warning(
                "claude_analyzer: could not parse response for %s: %s",
                market.condition_id,
                text[:200] if text else "<empty>",
            )
            return None

        prob = clamp_prob(float(parsed.get("home_win_probability", ensemble_prob_before)))
        conf_str = str(parsed.get("confidence", "medium")).lower()
        conf_map = {"high": 0.85, "medium": 0.65, "low": 0.4}
        confidence = conf_map.get(conf_str, 0.55)
        uncertainty = float(parsed.get("uncertainty", 0.05))
        uncertainty = max(0.01, min(0.2, uncertainty))
        factors = parsed.get("key_factors") or []
        if not isinstance(factors, list):
            factors = []
        factors = [str(f)[:120] for f in factors[:5]]
        reasoning = str(parsed.get("reasoning") or "").strip()
        if reasoning:
            factors.append(reasoning[:200])

        return ModelEstimate(
            model_name="claude",
            probability=prob,
            uncertainty=uncertainty,
            confidence=confidence,
            factors=factors,
        )

    # ----------------- helpers -----------------

    def _build_prompt(
        self,
        market: Market,
        ensemble_prob_before: float,
        basic_factors: list[str],
        team_context: dict[str, Any],
        injuries: list[InjuryNote],
        odds_consensus: dict[str, Any],
    ) -> str:
        # Pre-format the injury slice so we don't dump all 1400 entries to Claude.
        inj_lines: list[str] = []
        for inj in injuries[:8]:
            if not inj or not inj.player:
                continue
            inj_lines.append(
                f"- {inj.player} ({inj.team or '?'}) — {inj.status or 'unknown'}"
                + (f": {inj.description[:80]}" if inj.description else "")
            )

        odds_lines: list[str] = []
        for book, probs in list((odds_consensus or {}).items())[:5]:
            if isinstance(probs, (list, tuple)) and len(probs) >= 2:
                odds_lines.append(f"- {book}: home={probs[0]:.3f}, away={probs[1]:.3f}")

        ctx_parts = [
            f"Market question: {market.question}",
            f"Sport: {market.sport.value} / market_type: {market.market_type.value}",
            f"Home team: {market.home_team or '?'}",
            f"Away team: {market.away_team or '(futures/single-team market)'}",
            "",
            f"Polymarket YES price: {market.yes_price:.3f}  "
            f"(implies YES prob ≈ {market.yes_price:.3f})",
            f"Polymarket volume: ${market.volume:,.0f}",
            f"Polymarket liquidity: ${market.liquidity:,.0f}",
            "",
            f"Basic quant ensemble probability (pre-Claude): {ensemble_prob_before:.3f}",
            f"Basic model factors: {'; '.join(basic_factors[:5]) if basic_factors else '(none)'}",
            "",
            "Home team context (SportsDataIO, current season):",
            self._format_team_ctx(team_context) if team_context else "  (no enriched context)",
            "",
            "Recent injuries (top 8):",
            "\n".join(inj_lines) if inj_lines else "  (none reported)",
            "",
            "Sharp-book odds consensus (fair probs after vig removal):",
            "\n".join(odds_lines) if odds_lines else "  (no odds data)",
            "",
            "Return the JSON object only.",
        ]
        return "\n".join(ctx_parts)

    @staticmethod
    def _format_team_ctx(ctx: dict[str, Any]) -> str:
        if not ctx:
            return "  (no enriched context)"
        keys = ["wins", "losses", "points_per_game", "points_against_per_game",
                "conference_rank", "division_rank"]
        lines = []
        for k in keys:
            v = ctx.get(k)
            if v is not None:
                lines.append(f"  {k}: {v}")
        return "\n".join(lines) if lines else "  (team not found in stats feed)"

    @staticmethod
    def _extract_text(response: Any) -> str:
        try:
            blocks = response.content or []
            for b in blocks:
                if getattr(b, "type", None) == "text":
                    return str(b.text)
        except Exception:  # noqa: BLE001
            pass
        return ""

    @staticmethod
    def _extract_usage(response: Any) -> _UsageEstimate:
        usage = getattr(response, "usage", None)
        if usage is None:
            return _UsageEstimate()
        return _UsageEstimate(
            input_tokens=int(getattr(usage, "input_tokens", 0) or 0),
            output_tokens=int(getattr(usage, "output_tokens", 0) or 0),
        )


_JSON_BLOCK = re.compile(r"\{[\s\S]*\}")


def _parse_json(text: str) -> dict[str, Any] | None:
    """Pick the first JSON object out of `text` and parse it."""
    if not text:
        return None
    # Try the whole text first
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
    except (ValueError, TypeError):
        pass
    # Fall back to the first {...} span
    m = _JSON_BLOCK.search(text)
    if not m:
        return None
    try:
        obj = json.loads(m.group(0))
        return obj if isinstance(obj, dict) else None
    except (ValueError, TypeError):
        return None
