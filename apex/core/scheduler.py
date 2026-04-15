"""APScheduler — registers all periodic jobs."""

from __future__ import annotations

from typing import TYPE_CHECKING

from apex.utils.logger import get_logger

if TYPE_CHECKING:
    from apex.core.engine import ApexEngine

logger = get_logger(__name__)


async def _wrap(name: str, coro):
    try:
        await coro
    except Exception as exc:  # noqa: BLE001
        logger.warning("scheduled job %s failed: %s", name, exc)


def register_jobs(engine: ApexEngine) -> any:  # type: ignore[no-redef]
    """Build a scheduler with every periodic job registered."""
    try:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
    except ImportError:
        logger.error("APScheduler not installed")
        raise
    sched = AsyncIOScheduler()
    s = engine.settings

    sched.add_job(
        lambda: _wrap("scan_markets", engine.scan_markets()),
        "interval",
        seconds=s.market_scan_interval,
        id="scan_markets",
    )
    sched.add_job(
        lambda: _wrap("ingest_odds", engine.ingest_odds()),
        "interval",
        seconds=s.strategy_cycle_interval,
        id="ingest_odds",
    )
    sched.add_job(
        lambda: _wrap("generate_and_act", _cycle(engine)),
        "interval",
        seconds=s.strategy_cycle_interval,
        id="strategy_cycle",
    )
    sched.add_job(
        lambda: _wrap("poll_fills", engine.poll_fills()),
        "interval",
        seconds=s.fill_poll_interval,
        id="poll_fills",
    )
    sched.add_job(
        lambda: _wrap("poll_resolutions", engine.poll_resolutions()),
        "interval",
        seconds=s.resolution_poll_interval,
        id="poll_resolutions",
    )
    sched.add_job(
        lambda: _wrap("poll_results", engine.poll_results()),
        "interval",
        seconds=s.results_tracker_interval,
        id="poll_results",
    )
    return sched


async def _cycle(engine: ApexEngine) -> None:
    signals = await engine.generate_signals()
    await engine.evaluate_and_place(signals)
