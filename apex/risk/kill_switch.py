"""Hard stop — operator /kill or automatic on critical error."""

from __future__ import annotations

from apex.core.state import BotState
from apex.utils.logger import get_logger

logger = get_logger(__name__)


class KillSwitch:
    def __init__(self, state: BotState) -> None:
        self.state = state

    async def trigger(self, reason: str) -> None:
        await self.state.kill(reason)

    async def resume(self) -> None:
        # Resuming requires explicit action — just flip the flag.
        # Keep /resume separate so the operator re-attests.
        self.state.killed = False
        self.state.kill_reason = ""

    @property
    def is_active(self) -> bool:
        return self.state.killed
