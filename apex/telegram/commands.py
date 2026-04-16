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


async def _wait_for_startup(engine: Any, update: Any) -> bool:
    """Block data commands from replying with empty results during cold-start.

    Returns True if startup is complete; otherwise replies with a friendly
    "starting up" message and returns False. Safe to call on every data command.
    """
    if getattr(engine, "startup_complete", False):
        return True
    if getattr(update, "message", None):
        try:
            await update.message.reply_text(
                "⏳ APEX is starting up, please wait a few seconds and try again."
            )
        except Exception:  # noqa: BLE001
            pass
    return False


def detect_category_for(market: Any) -> Any:
    """Helper for category detection from a Market object."""
    from apex.market.categories import detect_category
    return detect_category(market.question or "", event_title=None, tags=market.tags if hasattr(market, "tags") else None)


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
        await update.message.reply_text(
            format_help(
                dry_run=engine.state.dry_run,
                engine_online=getattr(engine, "startup_complete", False),
            ),
            parse_mode="HTML",
        )

    async def status(update: Any, ctx: Any) -> None:
        if not await _auth_or_reject(update):
            return
        snap = engine.state.snapshot()
        await update.message.reply_text(format_status(snap), parse_mode="HTML")

    async def health(update: Any, ctx: Any) -> None:
        if not await _auth_or_reject(update):
            return
        if not await _wait_for_startup(engine, update):
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
        lines.append("<b>Upgrades</b>")
        claude_status = "✅ ON" if engine.claude.enabled else "➖ OFF (no key)"
        today = engine.cost_tracker.today_cost()
        cap = engine.cost_tracker.daily_cap_usd
        lines.append(
            f"  {claude_status} Claude ({esc(engine.settings.anthropic_model)}) "
            f"— spent ${today:.4f}/${cap:.2f} today"
        )
        sportsdata_status = "✅ ON" if engine.sportsdata.enabled else "➖ OFF (no key)"
        lines.append(f"  {sportsdata_status} SportsDataIO")
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
        if not await _wait_for_startup(engine, update):
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
        if not await _wait_for_startup(engine, update):
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
        if not await _wait_for_startup(engine, update):
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
        if not await _wait_for_startup(engine, update):
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
        if not await _wait_for_startup(engine, update):
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
        if not await _wait_for_startup(engine, update):
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

    async def costs(update: Any, ctx: Any) -> None:
        """Show daily + weekly Anthropic API spend vs. cap."""
        if not await _auth_or_reject(update):
            return
        from apex.telegram.formatters import esc

        summary = await engine.cost_tracker.summary(n_days=7)
        pct = 0.0
        if summary["daily_cap_usd"] > 0:
            pct = summary["today_cost_usd"] / summary["daily_cap_usd"]
        status = "🟢"
        if pct >= 1.0:
            status = "🛑 CAPPED"
        elif pct >= 0.8:
            status = "🟠"
        lines = [
            "<b>Anthropic API Costs</b>",
            f"Model: <code>{esc(engine.settings.anthropic_model)}</code>",
            f"{status} Today: ${summary['today_cost_usd']:.4f} / "
            f"${summary['daily_cap_usd']:.2f} cap ({pct:.1%})",
            f"Remaining: ${summary['remaining_usd']:.4f}",
            f"7-day total: ${summary['week_cost_usd']:.4f}",
        ]
        days = summary.get("days") or []
        if days:
            lines.append("")
            lines.append("<b>Last 7 days</b>")
            for d in days:
                lines.append(
                    f"  {esc(str(d.get('day_bucket')))}: "
                    f"{int(d.get('calls') or 0)} calls, "
                    f"${float(d.get('cost') or 0):.4f}"
                )
        if not engine.claude.enabled:
            lines.append("")
            lines.append("⚠️ Claude disabled (no ANTHROPIC_API_KEY or SDK init failed).")
        await update.message.reply_text("\n".join(lines), parse_mode="HTML")

    # ---- Trading Modes ----

    async def mode_cmd(update: Any, ctx: Any) -> None:
        if not await _auth_or_reject(update):
            return
        from apex.core.trading_modes import TradingMode, format_modes_list, get_mode_rules

        args = ctx.args if getattr(ctx, "args", None) else []
        if not args:
            await update.message.reply_text(format_modes_list(engine.trading_mode), parse_mode="HTML")
            return
        name = args[0].lower()
        try:
            new_mode = TradingMode(name)
        except ValueError:
            await update.message.reply_text(f"Unknown mode '{name}'. Try /mode to see all modes.")
            return
        rules = get_mode_rules(new_mode)
        if rules.warning:
            await update.message.reply_text(
                f"⚠️ {rules.warning}\nConfirm switch to {rules.name}?",
                reply_markup=confirm_keyboard("mode", name),
            )
        else:
            engine.trading_mode = new_mode
            engine.autopilot.mode = new_mode
            await update.message.reply_text(f"✅ Mode switched to <b>{rules.name}</b>", parse_mode="HTML")

    async def modes(update: Any, ctx: Any) -> None:
        if not await _auth_or_reject(update):
            return
        from apex.core.trading_modes import format_modes_list
        await update.message.reply_text(format_modes_list(engine.trading_mode), parse_mode="HTML")

    async def current_mode(update: Any, ctx: Any) -> None:
        if not await _auth_or_reject(update):
            return
        from apex.core.trading_modes import get_mode_rules
        from apex.telegram.formatters import esc
        r = get_mode_rules(engine.trading_mode)
        await update.message.reply_text(
            f"<b>Current Mode: {esc(r.name)}</b>\n"
            f"{esc(r.description)}\n"
            f"Edge ≥ {r.min_edge_zscore} · Claude ≥ {r.min_claude_score}/10\n"
            f"Expected: ~{r.expected_trades_per_day}/day · WR: {r.target_win_rate}",
            parse_mode="HTML",
        )

    # ---- Autopilot ----

    async def autopilot_cmd(update: Any, ctx: Any) -> None:
        if not await _auth_or_reject(update):
            return
        args = ctx.args if getattr(ctx, "args", None) else []
        if not args:
            await update.message.reply_text(engine.autopilot.status_text(), parse_mode="HTML")
            return
        action = args[0].lower()
        if action == "on":
            engine.autopilot.start()
            await update.message.reply_text("🟢 Autopilot ON — autonomous trading started.")
        elif action == "off":
            engine.autopilot.stop()
            await update.message.reply_text("🔴 Autopilot OFF — autonomous trading stopped.")
        elif action == "status":
            await update.message.reply_text(engine.autopilot.status_text(), parse_mode="HTML")
        else:
            await update.message.reply_text("Usage: /autopilot on|off|status")

    # ---- Crypto ----

    async def crypto(update: Any, ctx: Any) -> None:
        if not await _auth_or_reject(update):
            return
        if not await _wait_for_startup(engine, update):
            return
        from apex.market.categories import Category
        from apex.telegram.formatters import esc
        crypto_markets = [m for m in engine.markets_by_condition.values()
                         if detect_category_for(m) == Category.CRYPTO]
        if not crypto_markets:
            await update.message.reply_text(
                "No crypto markets in cache. Try /scan to discover markets."
            )
            return
        crypto_markets.sort(key=lambda m: m.volume, reverse=True)
        lines = [f"<b>🔐 Crypto Markets</b> ({len(crypto_markets)} found, top 10 by volume)\n"]
        for m in crypto_markets[:10]:
            yes = m.yes_price
            no = m.no_price if m.no_price else round(1.0 - yes, 3)
            indicator = "🟢" if yes > 0.5 else "🔴"
            lines.append(
                f"{indicator} YES={yes:.3f} NO={no:.3f} · vol ${m.volume:,.0f}\n"
                f"   {esc(m.question[:70])}"
            )
        await update.message.reply_text("\n".join(lines), parse_mode="HTML")

    async def predict_crypto(update: Any, ctx: Any) -> None:
        if not await _auth_or_reject(update):
            return
        if not await _wait_for_startup(engine, update):
            return
        import re

        from apex.market.categories import Category
        from apex.quant.crypto_ensemble import predict as crypto_predict
        from apex.telegram.formatters import esc

        args = ctx.args if getattr(ctx, "args", None) else []
        asset = args[0].lower() if args else "btc"
        timeframe_arg = args[1].lower() if len(args) > 1 else "24h"

        # Parse timeframe to hours
        def _parse_tf_hours(s: str) -> float:
            s = s.strip().lower()
            if s.endswith("d"):
                return float(s[:-1]) * 24
            if s.endswith("h"):
                return float(s[:-1])
            if s.endswith("m"):
                return float(s[:-1]) / 60
            return 24.0

        try:
            tf_hours = _parse_tf_hours(timeframe_arg)
        except ValueError:
            tf_hours = 24.0

        # Find the best matching crypto market
        crypto_markets = [
            m for m in engine.markets_by_condition.values()
            if detect_category_for(m) == Category.CRYPTO
            and asset in (m.question or "").lower()
        ]
        if not crypto_markets:
            await update.message.reply_text(
                f"No crypto market found for '<code>{esc(asset)}</code>'. "
                "Try /crypto to see available markets.",
                parse_mode="HTML",
            )
            return
        market = max(crypto_markets, key=lambda m: m.volume)

        # Extract target price from the question (e.g. "Will BTC hit $100,000?")
        price_match = re.search(r"\$([0-9][0-9,]*(?:\.[0-9]+)?)\s*[kK]?", market.question or "")
        if price_match:
            raw = price_match.group(1).replace(",", "")
            multiplier = 1000.0 if market.question and "k" in market.question[price_match.end()-1:price_match.end()+1].lower() else 1.0
            target_price = float(raw) * multiplier
        else:
            target_price = 0.0  # unknown; models will use relative positioning

        # Fetch live crypto data
        await update.message.reply_text(f"🔄 Fetching data for {asset.upper()}…")
        price_data: dict = {}
        klines: list = []
        fear_greed_val = 50
        try:
            price_data = await engine.crypto_client.get_price(asset)
            klines = await engine.crypto_client.get_klines(asset, interval="1h", limit=100)
            fg = await engine.crypto_client.get_fear_greed()
            fear_greed_val = fg.get("value", 50) if fg else 50
        except Exception as exc:  # noqa: BLE001
            logger.warning("predict_crypto: data fetch failed: %s", exc)

        current_price = price_data.get("price_usd") or 0.0
        change_24h = price_data.get("change_24h_pct")

        # If we couldn't determine target price, use +5% as a placeholder
        if target_price == 0.0 and current_price > 0:
            target_price = current_price * 1.05

        # Run the crypto ensemble
        result = crypto_predict(
            asset=asset.upper(),
            timeframe_hours=tf_hours,
            klines=klines,
            current_price=current_price,
            target_price=target_price,
            fear_greed=fear_greed_val,
        )

        prob = result["ensemble_prob"]
        std = result["ensemble_std"]
        confidence = result["confidence"]
        edge = prob - market.yes_price
        side = "YES" if edge > 0 else "NO"
        edge_pct = abs(edge) * 100

        lines = [
            f"🔮 <b>Crypto Forecast: {asset.upper()}</b> ({timeframe_arg})",
            "",
            f"❓ <b>Market:</b> {esc(market.question[:80])}",
            f"💲 <b>Current Price:</b> ${current_price:,.2f}"
            + (f" ({change_24h:+.1f}% 24h)" if change_24h is not None else ""),
            f"🎯 <b>Target Price:</b> ${target_price:,.2f}",
            "",
            f"📊 <b>Model Probability:</b> {prob:.3f} ± {std:.3f}",
            f"💰 <b>Market YES Price:</b> {market.yes_price:.3f}",
            f"📈 <b>Edge:</b> {edge:+.3f} ({edge_pct:.1f}%)",
            f"🎯 <b>Confidence:</b> {esc(str(confidence.value))}",
            f"⚡ <b>Side:</b> {side}",
            f"😱 <b>Fear &amp; Greed:</b> {fear_greed_val}/100",
            "",
            "<b>Model Breakdown:</b>",
        ]
        for name, est in result["model_estimates"].items():
            w = result["weights"].get(name, 0)
            short_name = name.replace("crypto_", "")
            lines.append(f"  {esc(short_name):12} {est.probability:.3f}  (w={w:.2f})")
        if result.get("key_factors"):
            lines.append("")
            lines.append("<b>Key Factors:</b>")
            for kf in result["key_factors"][:4]:
                lines.append(f"  • {esc(kf)}")

        await update.message.reply_text("\n".join(lines), parse_mode="HTML")

    async def claude_score(update: Any, ctx: Any) -> None:
        """Get on-demand Claude deep analysis with 1-10 score."""
        if not await _auth_or_reject(update):
            return
        if not await _wait_for_startup(engine, update):
            return
        args = ctx.args if getattr(ctx, "args", None) else []
        query = " ".join(args) if args else ""
        if not query:
            await update.message.reply_text("Usage: /claude_score <market query or condition_id>")
            return
        fc = await engine.predict_by_query(query)
        if not fc:
            await update.message.reply_text(f"No market found for '{query}'")
            return
        market = engine.markets_by_condition.get(fc.market_id)
        if not market:
            await update.message.reply_text("Market not in cache.")
            return
        if not engine.claude_deep or not engine.claude_deep.enabled:
            await update.message.reply_text("Claude API not configured (no ANTHROPIC_API_KEY).")
            return
        await update.message.reply_text("🤖 Running Claude deep analysis…")
        from apex.core.autopilot import _build_context
        context = _build_context(engine, market)
        result = await engine.claude_deep.analyze(market, fc, context)
        if result is None:
            await update.message.reply_text("Claude analysis failed or daily cap hit.")
            return
        from apex.telegram.formatters import esc
        lines = [
            f"🤖 <b>Claude Deep Analysis</b>: {esc(market.question[:60])}",
            f"Score: <b>{result['score']}/10</b>",
            f"Probability: {result.get('probability', 0.5):.3f}",
            f"Confidence: {esc(str(result.get('confidence', '?')))}",
            f"Size multiplier: {result.get('recommended_size_multiplier', 1.0):.1f}x",
            "",
            f"<b>Reasoning</b>: {esc(str(result.get('reasoning', ''))[:200])}",
        ]
        factors_for = result.get("key_factors_for", [])
        if factors_for:
            lines.append("\n<b>For</b>:")
            for f in factors_for[:5]:
                lines.append(f"  ✅ {esc(str(f))}")
        factors_against = result.get("key_factors_against", [])
        if factors_against:
            lines.append("<b>Against</b>:")
            for f in factors_against[:5]:
                lines.append(f"  ❌ {esc(str(f))}")
        warnings = result.get("warnings", [])
        if warnings:
            lines.append("<b>Warnings</b>:")
            for w in warnings:
                lines.append(f"  ⚠️ {esc(str(w))}")
        await update.message.reply_text("\n".join(lines), parse_mode="HTML")

    # ---- Performance ----

    async def performance(update: Any, ctx: Any) -> None:
        if not await _auth_or_reject(update):
            return
        from apex.telegram.formatters import esc
        summary = engine.performance.mode_summary()
        if not summary:
            await update.message.reply_text("No performance data yet — start trading first.")
            return
        lines = ["<b>Performance by Mode</b>"]
        for mode_name, stats in summary.items():
            lines.append(
                f"  <b>{esc(mode_name)}</b>: {stats['trades']} trades · "
                f"WR {stats['win_rate']} · P&L {stats['pnl']} · CLV {stats['avg_clv']}"
            )
        await update.message.reply_text("\n".join(lines), parse_mode="HTML")

    async def best_setups(update: Any, ctx: Any) -> None:
        if not await _auth_or_reject(update):
            return
        from apex.telegram.formatters import esc
        top = engine.performance.best_setups(5)
        if not top:
            await update.message.reply_text("Not enough data (need 10+ trades per bucket).")
            return
        lines = ["<b>Best Setups</b>"]
        for label, s in top:
            lines.append(f"  {esc(label)}: WR {s.win_rate:.0%} ({s.trades} trades) P&L ${s.total_pnl:+.2f}")
        await update.message.reply_text("\n".join(lines), parse_mode="HTML")

    async def worst_setups(update: Any, ctx: Any) -> None:
        if not await _auth_or_reject(update):
            return
        from apex.telegram.formatters import esc
        bottom = engine.performance.worst_setups(5)
        if not bottom:
            await update.message.reply_text("Not enough data (need 10+ trades per bucket).")
            return
        lines = ["<b>Worst Setups</b>"]
        for label, s in bottom:
            lines.append(f"  {esc(label)}: WR {s.win_rate:.0%} ({s.trades} trades) P&L ${s.total_pnl:+.2f}")
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
        await update.message.reply_text("🔬 Running self-test…")
        results: list[str] = []

        # 1. DB connection
        try:
            db_ok = engine.health.db_healthy
        except Exception:  # noqa: BLE001
            db_ok = False
        results.append(f"{'✅' if db_ok else '❌'} Database connection")

        # 2. Polymarket API (markets in cache)
        market_count = len(engine.markets_by_condition)
        pm_ok = market_count > 0
        results.append(f"{'✅' if pm_ok else '⚠️'} Polymarket ({market_count} markets cached)")

        # 3. Crypto market discoverable
        try:
            from apex.market.categories import Category
            crypto_count = sum(
                1 for m in engine.markets_by_condition.values()
                if detect_category_for(m) == Category.CRYPTO
            )
        except Exception:  # noqa: BLE001
            crypto_count = 0
        crypto_ok = crypto_count > 0
        results.append(f"{'✅' if crypto_ok else '⚠️'} Crypto markets ({crypto_count} discovered)")

        # 4. CryptoClient live ping (BTC price)
        try:
            price_data = await engine.crypto_client.get_price("btc")
            btc_price = price_data.get("price_usd", 0) if price_data else 0
            crypto_api_ok = btc_price > 0
        except Exception:  # noqa: BLE001
            crypto_api_ok = False
            btc_price = 0
        results.append(
            f"{'✅' if crypto_api_ok else '❌'} CoinGecko API"
            + (f" (BTC=${btc_price:,.0f})" if crypto_api_ok else "")
        )

        # 5. Telegram (if we got this far, polling is alive)
        results.append("✅ Telegram polling (this message proves it)")

        # 6. Startup complete
        started = getattr(engine, "startup_complete", False)
        results.append(f"{'✅' if started else '⏳'} Startup sequence {'complete' if started else 'in progress'}")

        # 7. Tasks running
        running = sum(1 for t in engine._tasks if not t.done())  # noqa: SLF001
        total = len(engine._tasks)  # noqa: SLF001
        tasks_ok = running == total
        results.append(f"{'✅' if tasks_ok else '⚠️'} Background tasks ({running}/{total} running)")

        all_ok = all(r.startswith("✅") for r in results)
        header = "✅ <b>All systems go</b>" if all_ok else "⚠️ <b>Smoke test — some checks failed</b>"
        text = header + "\n\n" + "\n".join(results)
        await update.message.reply_text(text, parse_mode="HTML")

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
        elif action == "confirm" and verb == "mode":
            from apex.core.trading_modes import TradingMode
            try:
                new_mode = TradingMode(payload)
                engine.trading_mode = new_mode
                engine.autopilot.mode = new_mode
                await query.edit_message_text(f"✅ Mode switched to {new_mode.value}")
            except ValueError:
                await query.edit_message_text(f"Invalid mode: {payload}")
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
        "costs": costs,
        "mode": mode_cmd,
        "modes": modes,
        "current_mode": current_mode,
        "autopilot": autopilot_cmd,
        "crypto": crypto,
        "predict_crypto": predict_crypto,
        "claude_score": claude_score,
        "performance": performance,
        "best_setups": best_setups,
        "worst_setups": worst_setups,
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
