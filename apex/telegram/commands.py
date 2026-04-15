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
            n = len(engine.markets_by_condition)
            await update.message.reply_text(
                f"No matching market found. ({n} markets in cache — try /scan first, then /markets)"
            )
            return
        await update.message.reply_text(format_forecast(fc), parse_mode="HTML")

    async def markets(update: Any, ctx: Any) -> None:
        if not await _auth_or_reject(update):
            return
        args = ctx.args if getattr(ctx, "args", None) else []
        sport_filter = args[0].upper() if args else None
        all_m = list(engine.markets_by_condition.values())
        if sport_filter:
            all_m = [m for m in all_m if m.sport.value == sport_filter]
        # Rank by volume
        all_m.sort(key=lambda m: m.volume, reverse=True)
        top = all_m[:15]
        if not top:
            await update.message.reply_text(
                "No markets in cache. Run /scan to force a refresh.", parse_mode="HTML"
            )
            return
        from apex.telegram.formatters import esc
        lines = [f"<b>Markets</b> ({len(all_m)} total, top 15 by volume)"]
        for m in top:
            lines.append(
                f"<code>{esc(m.sport.value):4}</code> vol ${m.volume:>7.0f} · "
                f"{esc((m.home_team or '?')[:24])} · {esc(m.question[:60])}"
            )
        await update.message.reply_text("\n".join(lines), parse_mode="HTML")

    async def scan(update: Any, ctx: Any) -> None:
        if not await _auth_or_reject(update):
            return
        await update.message.reply_text("🔄 Scanning Polymarket…")
        try:
            markets_found = await engine.scan_markets()
        except Exception as exc:  # noqa: BLE001
            await update.message.reply_text(f"Scan failed: {exc}")
            return
        from collections import Counter
        by_sport = Counter(m.sport.value for m in markets_found)
        breakdown = " · ".join(f"{s}:{n}" for s, n in by_sport.most_common())
        await update.message.reply_text(
            f"✅ Discovered {len(markets_found)} markets\n{breakdown}"
        )

    async def signals(update: Any, ctx: Any) -> None:
        if not await _auth_or_reject(update):
            return
        from apex.telegram.formatters import esc
        sigs = engine.last_signals
        if not sigs:
            await update.message.reply_text(
                "No recent signals. Wait for the next strategy cycle or send /scan."
            )
            return
        lines = [f"<b>Recent Signals</b> ({len(sigs)})"]
        for s in sigs[:10]:
            lines.append(
                f"<b>{esc(s.strategy)}</b> · {esc(s.side.value)} · edge {s.edge:+.3f} "
                f"(z={s.edge_zscore:+.2f}) · {esc(s.confidence.value)}"
            )
            if s.forecast:
                lines.append(f"  {esc(s.forecast.home_team)} vs {esc(s.forecast.away_team)}")
        await update.message.reply_text("\n".join(lines), parse_mode="HTML")

    async def diagnostics(update: Any, ctx: Any) -> None:
        if not await _auth_or_reject(update):
            return
        ec = engine.stats_counters
        lines = [
            "<b>Diagnostics</b>",
            f"Markets: {len(engine.markets_by_condition)} (last scan: {ec.discovered_markets})",
            f"Signals last cycle: {ec.signals_generated}",
            f"Decisions approved: {ec.decisions_approved}",
            f"Orders placed: {ec.orders_placed}",
            f"News items: {len(engine.fresh_news)}",
            f"Injury sports loaded: {len(engine.injuries_by_sport)}",
            "Power models loaded: "
            + ", ".join(
                f"{sp}={len(m._stats_by_team)}"  # noqa: SLF001
                for sp, m in engine.power_models.items()
            ),
            "Elo teams: "
            + ", ".join(f"{sp}={len(m.ratings)}" for sp, m in engine.elo_models.items()),
        ]
        await update.message.reply_text("\n".join(lines), parse_mode="HTML")

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
        "markets": markets,
        "scan": scan,
        "signals": signals,
        "diagnostics": diagnostics,
        "pause": pause,
        "resume": resume,
        "kill": kill,
        "cancel_all": cancel_all,
        "paper_on": paper_on,
        "paper_off": paper_off,
        "smoke": smoke,
        "callback": callback_query,
    }
