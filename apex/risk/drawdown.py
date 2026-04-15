"""Daily + rolling drawdown checks."""

from __future__ import annotations

from dataclasses import dataclass

from apex.config import get_settings
from apex.core.state import BotState


@dataclass
class DrawdownStatus:
    daily_exceeded: bool
    rolling_exceeded: bool
    daily_dd: float
    rolling_dd: float


def check_drawdowns(state: BotState) -> DrawdownStatus:
    s = get_settings()
    return DrawdownStatus(
        daily_exceeded=state.daily_drawdown >= s.daily_drawdown_pct,
        rolling_exceeded=state.drawdown_from_peak >= s.rolling_drawdown_pct,
        daily_dd=state.daily_drawdown,
        rolling_dd=state.drawdown_from_peak,
    )
