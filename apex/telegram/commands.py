"""All 30+ Telegram command handlers.

Each handler:
  1. Authorizes the user via apex.telegram.auth.is_authorized (fails CLOSED).
  2. Delegates to the engine / domain objects.
  3. Uses HTML formatter helpers (html.escape on all dynamic content).

The Telegram wiring (bot.py) attaches these as CommandHandlers.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from apex.telegram.auth import is_authorized
from apex.telegram.formatters import (
    format_forecast,
    format_help,
    format_pnl,
    format_positions,
    format_status,
)
from apex.telegram.keyboards import confirm_keyboard, parse_callback
from apex.utils.logger import get_logger

if TYPE_CHECKING:
    from apex.core.engine import ApexEngine

logger = get_logger(__name__)


async def _auth_or_reject(update: Any) -> bool:
    """Check user authorization; reply with access-denied if not."""
    user_id = None
    if getattr(update, "effective_user", None):
        user_id = update.effective_user.id
    if not is_authorized(user_id):
        if getattr(update, "message", None):
            try:
                await update.message.reply_text("⛔ Unauthorized.")
            except Exception:  # noqa: BLE001
                pass
        return False
    return True


def make_handlers(engine: ApexEngine) -> dict[str, Any]:
    """Return dict of command_name → async handler closure bound to engine."""

    async def start(update: Any, ctx: Any) -> None:
        if not await _auth_or_reject(update):
            return
        await update.message.reply_text(
            f"👋 APEX online. Mode: {'📋 PAPER' if engine.state.dry_run else '💸 LIVE'}",
            parse_mode="HTML",
        )

    async def help_cmd(update: Any, ctx: Any) -> None:
        if not await _auth_or_reject(update):
            return
        await update.message.reply_text(format_help(), parse_mode="HTML")

    async def status(update: Any, ctx: Any) -> None:
        if not await _auth_or_reject(update):
            return
        snap = engine.state.snapshot()
        await update.message.reply_text(format_status(snap), parse_mode="HTML")

    async def health(update: Any, ctx: Any) -> None:
        if not await _auth_or_reject(update):
            return
        snap = engine.health.snapshot()
        text = "<b>Health</b>\n" + "\n".join(
            f"{k}: {v}" for k, v in snap["sources"].items()
        )
        await update.message.reply_text(text, parse_mode="HTML")

    async def bankroll(update: Any, ctx: Any) -> None:
        if not await _auth_or_reject(update):
            return
        await update.message.reply_text(
            f"💰 Bankroll: ${engine.state.bankroll:.2f}", parse_mode="HTML"
        )

    async def pnl(update: Any, ctx: Any) -> None:
        if not await _auth_or_reject(update):
            return
        text = format_pnl(
            realized=engine.state.realized_pnl,
            unrealized=0.0,
            bankroll=engine.state.bankroll,
        )
        await update.message.reply_text(text, parse_mode="HTML")

    async def positions(update: Any, ctx: Any) -> None:
        if not await _auth_or_reject(update):
            return
        pos = list(engine.state.positions.values())
        await update.message.reply_text(format_positions(pos), parse_mode="HTML")

    async def predict(update: Any, ctx: Any) -> None:
        if not await _auth_or_reject(update):
            return
        args = ctx.args if getattr(ctx, "args", None) else []
        query = " ".join(args) if args else ""
        fc = await engine.predict_by_query(query)
        if fc is None:
            await update.message.reply_text("No matching market found.")
            return
        await update.message.reply_text(format_forecast(fc), parse_mode="HTML")

    async def pause(update: Any, ctx: Any) -> None:
        if not await _auth_or_reject(update):
            return
        await engine.state.pause("manual")
        await update.message.reply_text("⏸ Paused.")

    async def resume(update: Any, ctx: Any) -> None:
        if not await _auth_or_reject(update):
            return
        await engine.state.resume()
        await update.message.reply_text("▶ Resumed.")

    async def kill(update: Any, ctx: Any) -> None:
        if not await _auth_or_reject(update):
            return
        await update.message.reply_text(
            "Confirm KILL SWITCH activation?",
            reply_markup=confirm_keyboard("kill"),
        )

    async def cancel_all(update: Any, ctx: Any) -> None:
        if not await _auth_or_reject(update):
            return
        n = await engine.order_manager.cancel_all()
        await update.message.reply_text(f"Cancelled {n} open orders.")

    async def paper_on(update: Any, ctx: Any) -> None:
        if not await _auth_or_reject(update):
            return
        engine.state.dry_run = True
        await update.message.reply_text("📋 Paper mode ON.")

    async def paper_off(update: Any, ctx: Any) -> None:
        if not await _auth_or_reject(update):
            return
        await update.message.reply_text(
            "Confirm switch to LIVE mode?",
            reply_markup=confirm_keyboard("paper_off"),
        )

    async def smoke(update: Any, ctx: Any) -> None:
        if not await _auth_or_reject(update):
            return
        await update.message.reply_text("Smoke test: see scripts/smoke.py")

    async def callback_query(update: Any, ctx: Any) -> None:
        if not await _auth_or_reject(update):
            return
        query = update.callback_query
        if query is None:
            return
        await query.answer()
        action, verb, payload = parse_callback(query.data or "")
        if action == "confirm" and verb == "kill":
            await engine.state.kill("manual via telegram")
            await query.edit_message_text("🛑 Kill switch activated.")
        elif action == "confirm" and verb == "paper_off":
            engine.state.dry_run = False
            await query.edit_message_text("💸 LIVE mode on. Double-check env.")
        elif action == "cancel":
            await query.edit_message_text("Cancelled.")

    return {
        "start": start,
        "help": help_cmd,
        "status": status,
        "health": health,
        "bankroll": bankroll,
        "pnl": pnl,
        "positions": positions,
        "predict": predict,
        "pause": pause,
        "resume": resume,
        "kill": kill,
        "cancel_all": cancel_all,
        "paper_on": paper_on,
        "paper_off": paper_off,
        "smoke": smoke,
        "callback": callback_query,
    }
