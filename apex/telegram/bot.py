"""python-telegram-bot setup, command registration, polling start."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from apex.telegram.commands import make_handlers
from apex.utils.logger import get_logger

if TYPE_CHECKING:
    from apex.core.engine import ApexEngine

logger = get_logger(__name__)


def build_application(engine: ApexEngine, token: str) -> Any:
    """Create a python-telegram-bot Application with every handler registered."""
    try:
        from telegram.ext import Application, CallbackQueryHandler, CommandHandler
    except BaseException:  # noqa: BLE001  # pyo3 PanicException is a BaseException
        logger.error("python-telegram-bot unavailable")
        raise

    app = Application.builder().token(token).build()
    handlers = make_handlers(engine)
    for name in (
        "start",
        "help",
        "status",
        "health",
        "bankroll",
        "pnl",
        "positions",
        "predict",
        "markets",
        "scan",
        "signals",
        "diagnostics",
        "bet",
        "orders",
        "fills",
        "exposure",
        "heat",
        "risk",
        "arb",
        "costs",
        "mode",
        "modes",
        "current_mode",
        "autopilot",
        "crypto",
        "predict_crypto",
        "alerts",
        "portfolio",
        "watchlist",
        "claude_score",
        "performance",
        "best_setups",
        "worst_setups",
        "setstop",
        "pause",
        "resume",
        "kill",
        "cancel_all",
        "paper_on",
        "paper_off",
        "smoke",
    ):
        h = handlers.get(name)
        if h is None:
            continue
        app.add_handler(CommandHandler(name, h))
    # Callback query handler for inline keyboards
    app.add_handler(CallbackQueryHandler(handlers["callback"]))
    return app


async def run_polling(engine: ApexEngine, token: str) -> None:
    app = build_application(engine, token)
    await app.initialize()
    await app.start()
    await app.updater.start_polling()
    logger.info("Telegram polling started")
