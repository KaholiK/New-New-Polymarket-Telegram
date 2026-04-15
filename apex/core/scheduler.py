"""Thin compat shim — the real scheduler lives inside ApexEngine now.

Historical note: this module used to wrap APScheduler. Every time we tried that,
AsyncIOScheduler's coroutine-handling quirks produced "coroutine never awaited"
bugs on some platforms. We now use pure `asyncio.create_task` loops owned by the
engine. See `ApexEngine.start_periodic_tasks` in apex/core/engine.py.

This module remains only so that any external code that still imports
`apex.core.scheduler.register_jobs` (tests, older main.py copies) continues to
work — it simply starts the engine's own tasks.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from apex.utils.logger import get_logger

if TYPE_CHECKING:
    from apex.core.engine import ApexEngine

logger = get_logger(__name__)


def register_jobs(engine: ApexEngine) -> Any:
    """Compat entrypoint: delegates to the engine's own task manager.

    Returns the engine itself so the caller can await `engine.shutdown()` later.
    """
    engine.start_periodic_tasks()
    logger.info("scheduler: delegated to ApexEngine.start_periodic_tasks()")
    return engine
