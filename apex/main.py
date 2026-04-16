"""APEX entry point — initialize engine + start Telegram polling.

The engine owns its own asyncio-task scheduler (see ApexEngine.start_periodic_tasks).
We intentionally do NOT use APScheduler — its async job handling has been the source
of multiple "coroutine never awaited" bugs. Pure asyncio is simpler and provably
correct.
"""

from __future__ import annotations

import asyncio
import signal

from apex.config import get_settings
from apex.core.engine import ApexEngine
from apex.telegram.bot import build_application
from apex.utils.logger import configure_logging, get_logger

logger = get_logger(__name__)


async def main_async() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)

    engine = ApexEngine(settings)
    await engine.startup()  # fires initial ingest synchronously
    engine.start_periodic_tasks()  # kicks off background loops

    app = None
    if settings.telegram_bot_token and settings.telegram_bot_token != "test_token":
        try:
            app = build_application(engine, settings.telegram_bot_token)
            await app.initialize()
            await app.start()
            await app.updater.start_polling()
            # Wire the admin notifier to the live bot so alerts can reach Telegram.
            try:
                engine.notifier.attach_bot(app.bot)
            except Exception as exc:  # noqa: BLE001
                logger.warning("notifier.attach_bot failed: %s", exc)
            logger.info("telegram polling running")
        except Exception as exc:  # noqa: BLE001
            logger.error("telegram init failed (%s); continuing without bot", exc)
            if app is not None:
                try:
                    await app.shutdown()
                except Exception:  # noqa: BLE001
                    pass
            app = None
    else:
        logger.warning("no telegram token configured; bot-less mode")

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:  # Windows
            pass

    await stop.wait()
    logger.info("shutdown signal received")

    if app is not None:
        try:
            await app.updater.stop()
            await app.stop()
            await app.shutdown()
        except Exception as exc:  # noqa: BLE001
            logger.warning("telegram shutdown error: %s", exc)

    await engine.shutdown()


def main() -> None:
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
