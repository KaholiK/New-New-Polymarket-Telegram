"""BotState — single source of truth for bankroll, positions, kill flag, mode.

All mutations are guarded by an asyncio.Lock to prevent TOCTOU bugs (e.g. checking
bankroll and debiting in separate awaits).
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from apex.core.models import Position, Side
from apex.utils.logger import get_logger

logger = get_logger(__name__)


class BotState:
    def __init__(
        self,
        starting_bankroll: float = 20.0,
        dry_run: bool = True,
    ) -> None:
        self._lock = asyncio.Lock()
        self.starting_bankroll = starting_bankroll
        self.bankroll = starting_bankroll
        self.peak_bankroll = starting_bankroll
        self.day_start_bankroll = starting_bankroll
        self.day_start_ts: datetime = datetime.now(UTC)
        self.dry_run = dry_run
        self.paused = False
        self.killed = False
        self.pause_reason: str = ""
        self.kill_reason: str = ""
        self.positions: dict[str, Position] = {}  # key: f"{market_id}:{side}"
        self.realized_pnl: float = 0.0
        self.consecutive_losses: int = 0
        self.total_wins: int = 0
        self.total_losses: int = 0

    # --- helpers ---

    @staticmethod
    def position_key(market_id: str, side: Side) -> str:
        return f"{market_id}:{side.value}"

    @property
    def total_exposure_usd(self) -> float:
        return sum(p.cost_basis_usd for p in self.positions.values())

    @property
    def available_bankroll(self) -> float:
        return max(0.0, self.bankroll)

    @property
    def drawdown_from_peak(self) -> float:
        if self.peak_bankroll <= 0:
            return 0.0
        return max(0.0, (self.peak_bankroll - self.bankroll) / self.peak_bankroll)

    @property
    def daily_drawdown(self) -> float:
        if self.day_start_bankroll <= 0:
            return 0.0
        return max(0.0, (self.day_start_bankroll - self.bankroll) / self.day_start_bankroll)

    # --- bankroll ---

    async def debit(self, usd: float, reason: str = "") -> bool:
        """Deduct USD from bankroll. Triggers auto-kill if it would go negative.

        Returns True if debit succeeded, False if overdraft was prevented.
        """
        async with self._lock:
            if usd < 0:
                return False
            if self.bankroll - usd < 0:
                self.killed = True
                self.kill_reason = f"overdraft_prevented: debit ${usd:.2f} against ${self.bankroll:.2f}"
                logger.error("auto-kill: %s", self.kill_reason)
                return False
            self.bankroll -= usd
            if reason:
                logger.info("debit $%.2f (%s) → bankroll $%.2f", usd, reason, self.bankroll)
            return True

    async def credit(self, usd: float, reason: str = "") -> None:
        async with self._lock:
            self.bankroll += usd
            if self.bankroll > self.peak_bankroll:
                self.peak_bankroll = self.bankroll
            if reason:
                logger.info("credit $%.2f (%s) → bankroll $%.2f", usd, reason, self.bankroll)

    async def apply_realized_pnl(self, pnl: float, won: bool | None) -> None:
        async with self._lock:
            self.realized_pnl += pnl
            if won is True:
                self.total_wins += 1
                self.consecutive_losses = 0
            elif won is False:
                self.total_losses += 1
                self.consecutive_losses += 1

    # --- positions ---

    async def upsert_position(self, pos: Position) -> None:
        async with self._lock:
            self.positions[self.position_key(pos.market_id, pos.side)] = pos

    async def remove_position(self, market_id: str, side: Side) -> Position | None:
        async with self._lock:
            return self.positions.pop(self.position_key(market_id, side), None)

    async def get_position(self, market_id: str, side: Side) -> Position | None:
        async with self._lock:
            return self.positions.get(self.position_key(market_id, side))

    # --- control flags ---

    async def pause(self, reason: str) -> None:
        async with self._lock:
            self.paused = True
            self.pause_reason = reason
            logger.warning("paused: %s", reason)

    async def resume(self) -> None:
        async with self._lock:
            self.paused = False
            self.pause_reason = ""
            logger.info("resumed")

    async def kill(self, reason: str) -> None:
        async with self._lock:
            self.killed = True
            self.kill_reason = reason
            logger.error("kill switch: %s", reason)

    async def reset_day(self) -> None:
        async with self._lock:
            self.day_start_bankroll = self.bankroll
            self.day_start_ts = datetime.now(UTC)
            logger.info("daily reset: day_start_bankroll=$%.2f", self.bankroll)

    @property
    def is_trading_allowed(self) -> bool:
        return not (self.killed or self.paused)

    def snapshot(self) -> dict:
        return {
            "bankroll": round(self.bankroll, 4),
            "peak_bankroll": round(self.peak_bankroll, 4),
            "day_start_bankroll": round(self.day_start_bankroll, 4),
            "realized_pnl": round(self.realized_pnl, 4),
            "total_exposure": round(self.total_exposure_usd, 4),
            "dry_run": self.dry_run,
            "paused": self.paused,
            "killed": self.killed,
            "pause_reason": self.pause_reason,
            "kill_reason": self.kill_reason,
            "position_count": len(self.positions),
            "wins": self.total_wins,
            "losses": self.total_losses,
            "consecutive_losses": self.consecutive_losses,
            "drawdown_from_peak": round(self.drawdown_from_peak, 4),
            "daily_drawdown": round(self.daily_drawdown, 4),
        }
