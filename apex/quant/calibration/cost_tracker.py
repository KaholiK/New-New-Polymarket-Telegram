"""Anthropic API cost tracker.

Records every call (tokens + USD cost) in `anthropic_costs`. Blocks further calls
once the daily spend hits `anthropic_daily_cap_usd`. The engine consults this
tracker before issuing a Claude call; hitting the cap causes the forecaster to
silently fall back to the non-Claude ensemble.

Pricing (per 1M tokens, as of Claude Sonnet 4.x family):
  input:  $3.00
  output: $15.00

We hardcode these rates here and can override per-model via _MODEL_RATES.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from apex.storage.db import Database
from apex.utils.logger import get_logger
from apex.utils.time_utils import day_bucket_utc

logger = get_logger(__name__)

# $ per 1M tokens (input, output). Keep in sync with anthropic pricing docs.
_MODEL_RATES: dict[str, tuple[float, float]] = {
    "claude-sonnet-4-20250514": (3.00, 15.00),
    "claude-sonnet-4-5": (3.00, 15.00),
    "claude-opus-4-5": (15.00, 75.00),
    "claude-haiku-4-5": (1.00, 5.00),
}
_DEFAULT_RATES = (3.00, 15.00)  # safe fallback to Sonnet pricing


def estimate_cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    in_rate, out_rate = _MODEL_RATES.get(model, _DEFAULT_RATES)
    return (input_tokens * in_rate + output_tokens * out_rate) / 1_000_000.0


class CostTracker:
    """Persistent + in-memory daily cost cap enforcement."""

    def __init__(self, db: Database | None, daily_cap_usd: float = 1.0) -> None:
        self.db = db
        self.daily_cap_usd = daily_cap_usd
        # In-memory cumulative cost for today (reloaded from DB lazily on boot).
        self._today_bucket = day_bucket_utc()
        self._today_cost = 0.0
        self._today_loaded = False

    async def _ensure_today_loaded(self) -> None:
        if self._today_loaded or self.db is None:
            return
        try:
            self._today_cost = await self.db.anthropic_cost_for_day(self._today_bucket)
        except Exception as exc:  # noqa: BLE001
            logger.warning("cost_tracker: could not load today's ledger: %s", exc)
            self._today_cost = 0.0
        self._today_loaded = True

    async def _roll_day_if_needed(self) -> None:
        today = day_bucket_utc()
        if today != self._today_bucket:
            self._today_bucket = today
            self._today_cost = 0.0
            self._today_loaded = False
            await self._ensure_today_loaded()

    async def can_spend(self, estimate_usd: float) -> bool:
        """True if we're allowed to spend `estimate_usd` without exceeding the cap."""
        await self._roll_day_if_needed()
        await self._ensure_today_loaded()
        return (self._today_cost + estimate_usd) <= self.daily_cap_usd

    async def record(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
        market_id: str = "",
        ok: bool = True,
    ) -> float:
        """Record an API call and return the computed cost in USD."""
        await self._roll_day_if_needed()
        cost = estimate_cost_usd(model, input_tokens, output_tokens)
        self._today_cost += cost
        self._today_loaded = True
        if self.db is not None:
            try:
                await self.db.record_anthropic_cost(
                    {
                        "ts": datetime.now(UTC).isoformat(),
                        "day_bucket": self._today_bucket,
                        "model": model,
                        "input_tokens": input_tokens,
                        "output_tokens": output_tokens,
                        "cost_usd": cost,
                        "market_id": market_id,
                        "ok": 1 if ok else 0,
                    }
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("cost_tracker: failed to persist cost row: %s", exc)
        return cost

    def today_cost(self) -> float:
        return self._today_cost

    def today_bucket(self) -> str:
        return self._today_bucket

    async def summary(self, n_days: int = 7) -> dict[str, Any]:
        """Return a summary for the /costs Telegram command."""
        await self._roll_day_if_needed()
        await self._ensure_today_loaded()
        days: list[dict[str, Any]] = []
        total_week = 0.0
        if self.db is not None:
            try:
                days = await self.db.anthropic_cost_last_n_days(n_days)
                total_week = sum(float(d.get("cost") or 0) for d in days)
            except Exception as exc:  # noqa: BLE001
                logger.warning("cost_tracker: summary read failed: %s", exc)
        return {
            "today_bucket": self._today_bucket,
            "today_cost_usd": round(self._today_cost, 4),
            "daily_cap_usd": self.daily_cap_usd,
            "remaining_usd": round(max(0.0, self.daily_cap_usd - self._today_cost), 4),
            "capped": self._today_cost >= self.daily_cap_usd,
            "week_cost_usd": round(total_week, 4),
            "days": days,
        }
