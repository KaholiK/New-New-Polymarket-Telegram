"""APScheduler — registers all periodic jobs.

IMPORTANT: AsyncIOScheduler needs coroutine functions (async def) as job targets,
not sync lambdas that return coroutines. A lambda like `lambda: _wrap(...)` returns
a coroutine object which the scheduler never awaits — the job silently does nothing.
Each job here is wrapped as a real async def.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from apex.utils.logger import get_logger

if TYPE_CHECKING:
    from apex.core.engine import ApexEngine

logger = get_logger(__name__)


def _safe(name: str, fn: Callable[[], Awaitable[Any]]) -> Callable[[], Awaitable[None]]:
    """Wrap a coroutine factory so exceptions are logged, not silently lost."""

    async def runner() -> None:
        try:
            await fn()
        except Exception as exc:  # noqa: BLE001
            logger.warning("scheduled job %s failed: %s", name, exc)

    runner.__name__ = f"job_{name}"
    return runner


def register_jobs(engine: ApexEngine) -> Any:
    """Build a scheduler with every periodic job registered."""
    try:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
    except ImportError:
        logger.error("APScheduler not installed")
        raise
    sched = AsyncIOScheduler()
    s = engine.settings
    now = datetime.now(UTC)

    async def _cycle() -> None:
        signals = await engine.generate_signals()
        await engine.evaluate_and_place(signals)

    jobs = [
        ("scan_markets", engine.scan_markets, s.market_scan_interval, True),
        ("ingest_odds", engine.ingest_odds, s.strategy_cycle_interval, True),
        ("ingest_stats", engine.ingest_stats, s.results_tracker_interval, True),
        ("ingest_injuries", engine.ingest_injuries, max(60, s.injury_max_age // 2), True),
        ("ingest_news", engine.ingest_news, max(60, s.news_max_age // 2), True),
        ("strategy_cycle", _cycle, s.strategy_cycle_interval, False),
        ("poll_fills", engine.poll_fills, s.fill_poll_interval, False),
        ("poll_resolutions", engine.poll_resolutions, s.resolution_poll_interval, False),
        ("poll_results", engine.poll_results, s.results_tracker_interval, False),
    ]

    for name, fn, interval, run_now in jobs:
        sched.add_job(
            _safe(name, fn),
            "interval",
            seconds=interval,
            id=name,
            next_run_time=now if run_now else None,
            max_instances=1,
            coalesce=True,
        )

    return sched
