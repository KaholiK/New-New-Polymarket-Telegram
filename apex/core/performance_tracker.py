"""Performance tracking per mode, sport, timeframe. Auto-downgrade on losing streaks."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from apex.core.trading_modes import TradingMode
from apex.utils.logger import get_logger

logger = get_logger(__name__)

AUTO_DOWNGRADE_THRESHOLD = 0.45  # win rate below this over 30 trades → downgrade
AUTO_UPGRADE_THRESHOLD = 0.60  # win rate above this over 50 trades + positive CLV → suggest upgrade
AUTO_DOWNGRADE_WINDOW = 30
AUTO_UPGRADE_WINDOW = 50

# Downgrade path: AGGRESSIVE → BALANCED → CONSERVATIVE → SAFE
_DOWNGRADE_MAP: dict[TradingMode, TradingMode] = {
    TradingMode.AGGRESSIVE: TradingMode.BALANCED,
    TradingMode.SCALPING: TradingMode.BALANCED,
    TradingMode.HIGH_RISK_REWARD: TradingMode.BALANCED,
    TradingMode.BALANCED: TradingMode.CONSERVATIVE,
    TradingMode.MED_RISK_LOW_REWARD: TradingMode.CONSERVATIVE,
    TradingMode.SWING: TradingMode.CONSERVATIVE,
    TradingMode.CONSERVATIVE: TradingMode.SAFE,
    TradingMode.LONGTERM: TradingMode.SAFE,
}

# Upgrade path (suggestions only, not automatic)
_UPGRADE_MAP: dict[TradingMode, TradingMode] = {
    TradingMode.SAFE: TradingMode.CONSERVATIVE,
    TradingMode.CONSERVATIVE: TradingMode.BALANCED,
    TradingMode.BALANCED: TradingMode.AGGRESSIVE,
}


@dataclass
class BucketStats:
    """Stats for one mode×sport×timeframe bucket."""
    wins: int = 0
    losses: int = 0
    total_pnl: float = 0.0
    total_edge: float = 0.0
    total_clv: float = 0.0
    recent_outcomes: list[bool] = field(default_factory=list)  # True=win

    @property
    def trades(self) -> int:
        return self.wins + self.losses

    @property
    def win_rate(self) -> float:
        return self.wins / max(1, self.trades)

    @property
    def avg_clv(self) -> float:
        return self.total_clv / max(1, self.trades)

    @property
    def roi(self) -> float:
        return self.total_pnl  # simplified; full ROI needs cost basis

    def record(self, won: bool, pnl: float, edge: float, clv: float) -> None:
        if won:
            self.wins += 1
        else:
            self.losses += 1
        self.total_pnl += pnl
        self.total_edge += edge
        self.total_clv += clv
        self.recent_outcomes.append(won)
        if len(self.recent_outcomes) > 100:
            self.recent_outcomes.pop(0)

    def recent_win_rate(self, n: int = 30) -> float:
        recent = self.recent_outcomes[-n:]
        if not recent:
            return 0.5
        return sum(1 for w in recent if w) / len(recent)


class PerformanceTracker:
    def __init__(self) -> None:
        # Keyed by (mode, sport, timeframe)
        self._buckets: dict[tuple[str, str, str], BucketStats] = defaultdict(BucketStats)
        # Global per-mode
        self._by_mode: dict[str, BucketStats] = defaultdict(BucketStats)

    def record(
        self,
        mode: str,
        sport: str,
        timeframe: str,
        won: bool,
        pnl: float,
        edge: float = 0.0,
        clv: float = 0.0,
    ) -> None:
        self._buckets[(mode, sport, timeframe)].record(won, pnl, edge, clv)
        self._by_mode[mode].record(won, pnl, edge, clv)

    def check_auto_downgrade(self, current_mode: TradingMode) -> TradingMode | None:
        """If recent win rate is below threshold, return the safer mode to switch to."""
        stats = self._by_mode.get(current_mode.value)
        if stats is None or stats.trades < AUTO_DOWNGRADE_WINDOW:
            return None
        recent_wr = stats.recent_win_rate(AUTO_DOWNGRADE_WINDOW)
        if recent_wr < AUTO_DOWNGRADE_THRESHOLD:
            new_mode = _DOWNGRADE_MAP.get(current_mode)
            if new_mode:
                logger.warning(
                    "auto-downgrade: %s win_rate=%.1f%% over last %d → %s",
                    current_mode.value, recent_wr * 100, AUTO_DOWNGRADE_WINDOW, new_mode.value,
                )
                return new_mode
        return None

    def check_upgrade_suggestion(self, current_mode: TradingMode) -> TradingMode | None:
        """If recent performance is strong, suggest (not auto-execute) an upgrade."""
        stats = self._by_mode.get(current_mode.value)
        if stats is None or stats.trades < AUTO_UPGRADE_WINDOW:
            return None
        recent_wr = stats.recent_win_rate(AUTO_UPGRADE_WINDOW)
        if recent_wr >= AUTO_UPGRADE_THRESHOLD and stats.avg_clv > 0:
            return _UPGRADE_MAP.get(current_mode)
        return None

    def best_setups(self, n: int = 5) -> list[tuple[str, BucketStats]]:
        """Top N (mode, sport, timeframe) combos by win rate (min 10 trades)."""
        eligible = [
            (f"{k[0]}:{k[1]}:{k[2]}", s)
            for k, s in self._buckets.items()
            if s.trades >= 10
        ]
        eligible.sort(key=lambda x: x[1].win_rate, reverse=True)
        return eligible[:n]

    def worst_setups(self, n: int = 5) -> list[tuple[str, BucketStats]]:
        eligible = [
            (f"{k[0]}:{k[1]}:{k[2]}", s)
            for k, s in self._buckets.items()
            if s.trades >= 10
        ]
        eligible.sort(key=lambda x: x[1].win_rate)
        return eligible[:n]

    def mode_summary(self) -> dict[str, dict]:
        out: dict[str, dict] = {}
        for mode_name, stats in self._by_mode.items():
            out[mode_name] = {
                "trades": stats.trades,
                "wins": stats.wins,
                "losses": stats.losses,
                "win_rate": f"{stats.win_rate:.1%}",
                "pnl": f"${stats.total_pnl:+.2f}",
                "avg_clv": f"{stats.avg_clv:+.4f}",
            }
        return out
