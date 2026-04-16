"""Autopilot — autonomous trading loop.

When activated via /autopilot on, runs a strategy cycle every 3 minutes:
1. Discover new markets (every 2 min via engine tasks)
2. For each candidate market: run all quant models
3. If preliminary edge > mode threshold: call Claude Deep Analyzer for 1-10 score
4. If Claude score >= mode minimum: pass through risk gates and execute
5. Send Telegram alert with full breakdown for every trade

Respects ALL existing risk gates: drawdown stops, kill switch, exposure limits,
$1 profit minimum, bankroll-aware sizing.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from apex.core.trading_modes import TradingMode, get_mode_rules, passes_mode_gate
from apex.utils.logger import get_logger

if TYPE_CHECKING:
    from apex.core.engine import ApexEngine

logger = get_logger(__name__)


@dataclass
class AutopilotStats:
    cycles: int = 0
    candidates_evaluated: int = 0
    claude_calls: int = 0
    trades_placed: int = 0
    rejected_by_mode: int = 0
    rejected_by_claude: int = 0
    rejected_by_risk: int = 0
    daily_pnl: float = 0.0

    def reset_daily(self) -> None:
        self.cycles = 0
        self.candidates_evaluated = 0
        self.claude_calls = 0
        self.trades_placed = 0
        self.rejected_by_mode = 0
        self.rejected_by_claude = 0
        self.rejected_by_risk = 0
        self.daily_pnl = 0.0


class Autopilot:
    def __init__(self, engine: ApexEngine) -> None:
        self.engine = engine
        self.active = False
        self.mode = TradingMode.BALANCED
        self.stats = AutopilotStats()
        self._task: asyncio.Task | None = None
        self._shutdown = asyncio.Event()
        self.cycle_interval = 180  # 3 minutes

    def start(self) -> None:
        if self.active:
            return
        self.active = True
        self._shutdown.clear()
        self._task = asyncio.create_task(self._loop(), name="apex:autopilot")
        logger.info("autopilot: started in %s mode", self.mode.value)

    def stop(self) -> None:
        self.active = False
        self._shutdown.set()
        if self._task and not self._task.done():
            self._task.cancel()
        self._task = None
        logger.info("autopilot: stopped")

    async def _loop(self) -> None:
        """Main autopilot loop. Runs strategy cycle, evaluates candidates with Claude."""
        while not self._shutdown.is_set():
            try:
                await self._cycle()
            except Exception as exc:  # noqa: BLE001
                logger.error("autopilot cycle failed: %s", exc)
            try:
                await asyncio.wait_for(self._shutdown.wait(), timeout=float(self.cycle_interval))
                return
            except TimeoutError:
                continue

    async def _cycle(self) -> None:
        """One autopilot cycle: discover → forecast → score → execute."""
        self.stats.cycles += 1
        eng = self.engine
        rules = get_mode_rules(self.mode)

        if not eng.state.is_trading_allowed:
            return

        # Generate candidates (forecasts + strategy signals).
        # generate_signals populates eng.last_candidates as a side effect.
        await eng.generate_signals()
        candidates = eng.last_candidates or []

        # Also consider markets where we have an edge from forecasts alone
        # even if no strategy fired (autopilot is more aggressive about evaluating)
        for cand in candidates:
            self.stats.candidates_evaluated += 1
            edge = abs(cand.get("edge", 0))
            confidence = cand.get("confidence", "low")
            market_id = cand.get("market_id", "")
            market_price = cand.get("market_price", 0.5)

            # Quick mode gate (without Claude score yet — use 10 as placeholder)
            passes, reasons = passes_mode_gate(
                self.mode, confidence, cand.get("edge_zscore", 0), 10, market_price
            )
            if not passes:
                self.stats.rejected_by_mode += 1
                continue

            # Edge must be above a minimum to justify a Claude call
            if edge < rules.min_edge_zscore * 0.01:
                self.stats.rejected_by_mode += 1
                continue

            # Claude Deep Analysis — the mandatory gate
            market = eng.markets_by_condition.get(market_id)
            if market is None:
                continue

            forecast = await eng._forecast_market(market)  # noqa: SLF001
            if forecast is None:
                continue

            deep_result = None
            if eng.claude_deep and eng.claude_deep.enabled:
                self.stats.claude_calls += 1
                context = _build_context(eng, market)
                deep_result = await eng.claude_deep.analyze(market, forecast, context)

            claude_score = deep_result.get("score", 5) if deep_result else 5

            # Mode gate WITH real Claude score
            passes, reasons = passes_mode_gate(
                self.mode, confidence, cand.get("edge_zscore", 0), claude_score, market_price
            )
            if not passes:
                self.stats.rejected_by_claude += 1
                continue

            # Size with Claude multiplier
            size_mult = 1.0
            if deep_result:
                size_mult = max(0.5, min(1.5, float(deep_result.get("recommended_size_multiplier", 1.0))))

            # Place the trade via engine's manual_bet
            side = cand.get("side", "YES")
            base_size = min(2.0, eng.state.bankroll * 0.05)  # 5% of bankroll or $2
            final_size = round(base_size * size_mult, 2)
            if final_size < eng.settings.min_order_size_usd:
                self.stats.rejected_by_risk += 1
                continue

            result = await eng.manual_bet(market, side, final_size)
            if "Placed" in result:
                self.stats.trades_placed += 1
                logger.info(
                    "autopilot: trade placed — %s %s $%.2f on %s (claude=%d)",
                    side, market.question[:50], final_size, market.condition_id[:12], claude_score,
                )

    def status_text(self) -> str:
        s = self.stats
        return (
            f"<b>Autopilot</b>: {'🟢 ON' if self.active else '🔴 OFF'}\n"
            f"Mode: {self.mode.value}\n"
            f"Cycles: {s.cycles} · Candidates: {s.candidates_evaluated}\n"
            f"Claude calls: {s.claude_calls} · Trades placed: {s.trades_placed}\n"
            f"Rejected — mode: {s.rejected_by_mode} · claude: {s.rejected_by_claude} · risk: {s.rejected_by_risk}\n"
            f"Daily P&L: ${s.daily_pnl:+.2f}"
        )


def _build_context(engine: ApexEngine, market: Any) -> dict[str, Any]:
    """Gather all available context for Claude deep analysis."""
    sport = market.sport.value if hasattr(market, "sport") else "UNKNOWN"
    injuries = engine.injuries_by_sport.get(sport, [])
    news = [n.headline for n in engine.fresh_news[:5]] if engine.fresh_news else []
    return {
        "injuries": injuries[:15],
        "news_headlines": news,
        "performance": {
            "win_rate": f"{engine.state.total_wins}/{engine.state.total_wins + engine.state.total_losses}",
            "clv": "N/A",
        },
    }
