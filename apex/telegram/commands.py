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
        from apex.telegram.formatters import esc
        from apex.utils.time_utils import format_duration

        lines = ["<b>Data Sources</b>"]
        sources = [
            ("polymarket", "Gamma", f"{len(engine.markets_by_condition)} markets"),
            ("odds", "Odds API", "multi-book"),
            ("stats", "ESPN stats",
             f"{sum(len(m._stats_by_team) for m in engine.power_models.values())} teams"),  # noqa: SLF001
            ("injuries", "ESPN injuries",
             f"{sum(len(v) for v in engine.injuries_by_sport.values())} entries"),
            ("news", "ESPN news", f"{len(engine.fresh_news)} items"),
        ]
        for src, label, detail in sources:
            age = engine.source_health.age(src)
            state = engine.source_health.breaker(src).state
            if age == float("inf"):
                status = "❌ NEVER"
                age_str = "—"
            else:
                limit = {
                    "polymarket": engine.settings.polymarket_max_age,
                    "odds": engine.settings.odds_max_age,
                    "stats": engine.settings.results_tracker_interval * 2,
                    "injuries": engine.settings.injury_max_age,
                    "news": engine.settings.news_max_age,
                }.get(src, 600)
                status = "✅ OK" if age <= limit else "⚠️ STALE"
                age_str = format_duration(age)
            if state == "open":
                status = "🛑 BREAKER OPEN"
            lines.append(
                f"  {status} <b>{esc(label):18}</b> {esc(detail):22} age={esc(age_str)}"
            )
        lines.append("")
        lines.append(f"DB: {'✅ OK' if engine.health.db_healthy else '❌ ERROR'}")
        lines.append(
            f"Tasks running: {sum(1 for t in engine._tasks if not t.done())}/"  # noqa: SLF001
            f"{len(engine._tasks)}"  # noqa: SLF001
        )
        await update.message.reply_text("\n".join(lines), parse_mode="HTML")

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
        # No-arg fallback: forecast the highest-volume cached market.
        if not query:
            if not engine.markets_by_condition:
                await update.message.reply_text(
                    "No markets in cache. Run /scan, then try /predict <team|sport>."
                )
                return
            top = max(engine.markets_by_condition.values(), key=lambda m: m.volume)
            fc = await engine._forecast_market(top)  # noqa: SLF001
            if fc is None:
                await update.message.reply_text("Forecast failed on top market.")
                return
            await update.message.reply_text(format_forecast(fc), parse_mode="HTML")
            return
        fc = await engine.predict_by_query(query)
        if fc is None:
            n = len(engine.markets_by_condition)
            await update.message.reply_text(
                f"No matching market for '{query}'. "
                f"({n} markets in cache — try /markets NBA to browse)"
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
        all_m.sort(key=lambda m: m.volume, reverse=True)
        top = all_m[:10]
        if not top:
            if not engine.markets_by_condition:
                await update.message.reply_text(
                    "No markets in cache yet. Run /scan to force a refresh. "
                    "(If the bot just started, try again in ~10 seconds.)",
                    parse_mode="HTML",
                )
            else:
                await update.message.reply_text(
                    f"No markets for sport '{sport_filter}'. "
                    f"Have {len(engine.markets_by_condition)} markets across "
                    "all sports — try /markets without a filter.",
                    parse_mode="HTML",
                )
            return
        from apex.telegram.formatters import esc
        lines = [
            f"<b>Markets</b> ({len(all_m)} total"
            + (f" in {sport_filter}" if sport_filter else "")
            + f", top {len(top)} by volume):"
        ]
        for m in top:
            title = (m.question or "")[:55]
            lines.append(
                f"<b>{esc(m.sport.value)}</b> · vol ${m.volume:,.0f} · "
                f"YES={m.yes_price:.3f} NO={m.no_price:.3f}"
            )
            lines.append(f"  {esc(title)}")
            lines.append(f"  <code>{esc(m.condition_id[:20])}...</code>")
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
        lines: list[str] = []
        # Section 1: fired signals (if any)
        if sigs:
            lines.append(f"<b>🔥 Fired Signals</b> ({len(sigs)})")
            for s in sigs[:10]:
                lines.append(
                    f"  <b>{esc(s.strategy)}</b> · {esc(s.side.value)} · "
                    f"edge {s.edge:+.3f} (z={s.edge_zscore:+.2f}) · {esc(s.confidence.value)}"
                )
                if s.forecast:
                    matchup = s.forecast.home_team
                    if s.forecast.away_team:
                        matchup += f" vs {s.forecast.away_team}"
                    lines.append(f"    {esc(matchup)}")
        else:
            lines.append("<b>🔥 Fired Signals</b>: none this cycle")
        # Section 2: top candidates (always shown so operator sees the brain thinking)
        cands = engine.last_candidates
        if cands:
            lines.append("")
            lines.append(f"<b>Top Candidates</b> (top 5 of {len(cands)}):")
            for c in cands[:5]:
                status = "✅ actionable" if c["is_actionable"] else "⏸"
                matchup = c["home_team"] or "?"
                if c["away_team"]:
                    matchup += f" vs {c['away_team']}"
                lines.append(
                    f"  {status} {esc(c['sport']):4} edge {c['edge']:+.3f} "
                    f"(z={c['edge_zscore']:+.2f}) conf={esc(c['confidence'])}"
                )
                lines.append(f"    {esc(matchup[:60])}")
                if c["fired_strategies"]:
                    lines.append(f"    fired: {esc(', '.join(c['fired_strategies']))}")
                if c["rejection_reasons"]:
                    lines.append(
                        f"    reasons: {esc(', '.join(c['rejection_reasons'][:3]))}"
                    )
        else:
            lines.append("")
            lines.append("No candidates yet — wait for next strategy cycle or /scan.")
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

    async def bet(update: Any, ctx: Any) -> None:
        """Usage: /bet <market_id|query> <YES|NO> <usd>."""
        if not await _auth_or_reject(update):
            return
        args = ctx.args if getattr(ctx, "args", None) else []
        if len(args) < 3:
            await update.message.reply_text(
                "Usage: <code>/bet &lt;market_id|query&gt; &lt;YES|NO&gt; &lt;usd&gt;</code>",
                parse_mode="HTML",
            )
            return
        ident = args[0]
        side_str = args[1].upper()
        try:
            size_usd = float(args[2])
        except ValueError:
            await update.message.reply_text("Amount must be a number (e.g. 2.00).")
            return
        if side_str not in ("YES", "NO"):
            await update.message.reply_text("Side must be YES or NO.")
            return
        # Resolve market: exact condition_id first, then fuzzy title match
        mkt = engine.markets_by_condition.get(ident)
        if mkt is None:
            from apex.utils.parsing import fuzzy_ratio

            best = None
            for m in engine.markets_by_condition.values():
                r = fuzzy_ratio(ident, m.question or "")
                if best is None or r > best[1]:
                    best = (m, r)
            if best and best[1] >= 0.4:
                mkt = best[0]
        if mkt is None:
            await update.message.reply_text(
                f"No market matching '{ident}'. Try /markets first."
            )
            return
        result = await engine.manual_bet(mkt, side_str, size_usd)
        await update.message.reply_text(result, parse_mode="HTML")

    async def orders(update: Any, ctx: Any) -> None:
        if not await _auth_or_reject(update):
            return
        snap = engine.dry.snapshot()
        if not snap:
            await update.message.reply_text("No orders.")
            return
        from apex.telegram.formatters import esc
        lines = [f"<b>Orders</b> ({len(snap)})"]
        for o in snap[:20]:
            lines.append(
                f"  <code>{esc(o['id'][:8])}</code> {esc(o['status'])} "
                f"filled {o['filled']:.2f} @ {o['avg_price']:.3f}"
            )
        await update.message.reply_text("\n".join(lines), parse_mode="HTML")

    async def fills(update: Any, ctx: Any) -> None:
        if not await _auth_or_reject(update):
            return
        accs = engine.fills.all_accumulators()
        if not accs:
            await update.message.reply_text("No fills.")
            return
        from apex.telegram.formatters import esc
        lines = [f"<b>Fills</b> ({len(accs)})"]
        for acc in accs[:20]:
            lines.append(
                f"  <code>{esc(acc.order_id[:8])}</code> "
                f"{acc.total_contracts:.2f} contracts @ {acc.avg_price:.3f} "
                f"(${acc.total_usd:.2f})"
            )
        await update.message.reply_text("\n".join(lines), parse_mode="HTML")

    async def exposure(update: Any, ctx: Any) -> None:
        if not await _auth_or_reject(update):
            return
        from collections import defaultdict
        by_sport = defaultdict(float)
        for pos in engine.state.positions.values():
            m = engine.markets_by_condition.get(pos.market_id)
            sport = m.sport.value if m else "UNKNOWN"
            by_sport[sport] += pos.cost_basis_usd
        if not by_sport:
            await update.message.reply_text("No exposure.")
            return
        from apex.telegram.formatters import esc
        total = sum(by_sport.values())
        lines = [f"<b>Exposure</b> — total ${total:.2f}"]
        for sp, amt in sorted(by_sport.items(), key=lambda x: -x[1]):
            pct = amt / max(1e-9, engine.state.bankroll)
            lines.append(f"  {esc(sp)}: ${amt:.2f} ({pct:.1%} of bankroll)")
        await update.message.reply_text("\n".join(lines), parse_mode="HTML")

    async def heat(update: Any, ctx: Any) -> None:
        """Alias/expanded version of /exposure — portfolio heat map."""
        await exposure(update, ctx)

    async def risk(update: Any, ctx: Any) -> None:
        if not await _auth_or_reject(update):
            return
        from apex.risk.drawdown import check_drawdowns

        dd = check_drawdowns(engine.state)
        s = engine.settings
        lines = [
            "<b>Risk</b>",
            f"Daily DD: {dd.daily_dd:.2%} (limit {s.daily_drawdown_pct:.0%})",
            f"Peak DD: {dd.rolling_dd:.2%} (limit {s.rolling_drawdown_pct:.0%})",
            f"Consecutive losses: {engine.state.consecutive_losses} / {s.max_consecutive_losses}",
            f"Kelly fraction: {s.kelly_fraction} (small-roll {s.kelly_fraction_small_bankroll})",
            f"Max position: {s.max_position_pct:.0%} bankroll",
            f"Max sport exposure: {s.max_sport_exposure_pct:.0%}",
            f"Min profit gate: ${s.min_profit_threshold}",
        ]
        if dd.daily_exceeded or dd.rolling_exceeded:
            lines.append("⚠️ DRAWDOWN LIMIT HIT — trading halted")
        await update.message.reply_text("\n".join(lines), parse_mode="HTML")

    async def arb(update: Any, ctx: Any) -> None:
        """Scan cached markets for YES+NO mispricing."""
        if not await _auth_or_reject(update):
            return
        from apex.telegram.formatters import esc

        candidates = []
        for m in engine.markets_by_condition.values():
            if m.yes_price <= 0 or m.no_price <= 0:
                continue
            total = m.yes_price + m.no_price
            if total < 0.98:
                candidates.append((m, total))
        if not candidates:
            await update.message.reply_text(
                f"No arb (YES+NO < 0.98) in {len(engine.markets_by_condition)} markets."
            )
            return
        candidates.sort(key=lambda x: x[1])
        lines = [f"<b>Arb candidates</b> ({len(candidates)})"]
        for m, total in candidates[:10]:
            lines.append(
                f"  {esc(m.sport.value):4} y+n={total:.3f} "
                f"(y={m.yes_price:.3f} n={m.no_price:.3f}) · {esc(m.question[:70])}"
            )
        await update.message.reply_text("\n".join(lines), parse_mode="HTML")

    async def setstop(update: Any, ctx: Any) -> None:
        """Usage: /setstop <market_id> <stop%> [take%] [trail%]"""
        if not await _auth_or_reject(update):
            return
        args = ctx.args if getattr(ctx, "args", None) else []
        if len(args) < 2:
            await update.message.reply_text(
                "Usage: <code>/setstop &lt;market_id&gt; &lt;stop%&gt; [take%] [trail%]</code>",
                parse_mode="HTML",
            )
            return
        market_id = args[0]
        # Find the matching open position to get its side
        pos_key = None
        for key, p in engine.state.positions.items():
            if p.market_id == market_id:
                pos_key = p
                break
        if pos_key is None:
            await update.message.reply_text("No open position for that market.")
            return
        try:
            sl = float(args[1]) / 100.0
            tp = float(args[2]) / 100.0 if len(args) > 2 else None
            tr = float(args[3]) / 100.0 if len(args) > 3 else None
        except ValueError:
            await update.message.reply_text("Stop values must be numbers (e.g. 20 for 20%).")
            return
        engine.stops.set_rule(market_id, pos_key.side, sl, tp, tr)
        await update.message.reply_text(
            f"Stop set on {market_id[:10]} {pos_key.side.value}: "
            f"SL={sl:.0%} TP={tp if tp is None else f'{tp:.0%}'} TR={tr if tr is None else f'{tr:.0%}'}"
        )

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
        "bet": bet,
        "orders": orders,
        "fills": fills,
        "exposure": exposure,
        "heat": heat,
        "risk": risk,
        "arb": arb,
        "setstop": setstop,
        "pause": pause,
        "resume": resume,
        "kill": kill,
        "cancel_all": cancel_all,
        "paper_on": paper_on,
        "paper_off": paper_off,
        "smoke": smoke,
        "callback": callback_query,
    }
