"""APEX entry point — initialize engine, start scheduler + Telegram polling."""

from __future__ import annotations

import asyncio
import signal

from apex.config import get_settings
from apex.core.engine import ApexEngine
from apex.core.scheduler import register_jobs
from apex.telegram.bot import build_application
from apex.utils.logger import configure_logging, get_logger

logger = get_logger(__name__)


async def main_async() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)

    engine = ApexEngine(settings)
    await engine.startup()

    scheduler = register_jobs(engine)
    scheduler.start()

    app = None
    if settings.telegram_bot_token and settings.telegram_bot_token != "test_token":
        try:
            app = build_application(engine, settings.telegram_bot_token)
            await app.initialize()
            await app.start()
            await app.updater.start_polling()
            logger.info("telegram polling running")
        except Exception as exc:  # noqa: BLE001
            # Bad token, network issue, or missing deps → keep the engine/scheduler
            # running in bot-less mode. The operator can fix .env and restart.
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

    scheduler.shutdown(wait=False)
    if app is not None:
        await app.updater.stop()
        await app.stop()
        await app.shutdown()
    await engine.shutdown()


def main() -> None:
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
