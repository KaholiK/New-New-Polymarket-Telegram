"""Auto-pause after N consecutive resolved losses."""

from __future__ import annotations

from apex.config import get_settings
from apex.core.state import BotState


async def check_and_pause(state: BotState) -> bool:
    """If consecutive_losses >= limit, pause and return True."""
    s = get_settings()
    if state.consecutive_losses >= s.max_consecutive_losses and not state.paused:
        await state.pause(f"consecutive_losses={state.consecutive_losses}")
        return True
    return False
