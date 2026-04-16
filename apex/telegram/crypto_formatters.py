"""Rich HTML formatters for crypto commands and the enhanced /status dashboard."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from apex.core.crypto_state import CoinSnapshot, CryptoState
    from apex.core.engine import ApexEngine, ServiceStatus
    from apex.core.models import Market


_COIN_EMOJI = {
    "btc": "₿",
    "eth": "Ξ",
    "sol": "◎",
    "ada": "₳",
    "avax": "🔺",
    "link": "🔗",
    "dot": "●",
    "matic": "⬢",
    "doge": "🐕",
    "shib": "🐕",
    "xrp": "✕",
    "bnb": "🟡",
}


def _age_str(age_s: float) -> str:
    if age_s == float("inf"):
        return "never"
    if age_s < 60:
        return f"{int(age_s)}s"
    if age_s < 3600:
        return f"{int(age_s / 60)}m"
    return f"{age_s / 3600:.1f}h"


def _format_price_line(snap: CoinSnapshot, esc: Any) -> str:
    symbol = snap.symbol.upper()
    emoji = _COIN_EMOJI.get(snap.symbol.lower(), "")
    prefix = f"{emoji} {symbol}".strip()
    chg_str = ""
    if snap.change_24h_pct is not None:
        arrow = "🟢" if snap.change_24h_pct >= 0 else "🔴"
        chg_str = f" {arrow} {snap.change_24h_pct:+.2f}%"
    return f"  {esc(prefix):<8} ${snap.price_usd:>12,.2f}{chg_str}"


def format_crypto_dashboard(
    state: CryptoState,
    service_status: ServiceStatus,
    markets: list[Market],
    esc: Any,
) -> str:
    """Render the /crypto dashboard: prices, Fear & Greed, top markets."""
    lines: list[str] = ["<b>📊 CRYPTO DASHBOARD</b>", "━━━━━━━━━━━━━━━━━━━"]

    coins = state.top_coins(10)
    if not coins:
        stale = "⚠️ No prices yet" if not service_status.coingecko_degraded \
            else "❌ CoinGecko degraded"
        lines.append(stale)
    else:
        for snap in coins:
            lines.append(_format_price_line(snap, esc))
        # Stale warning if the freshest coin is older than 15 min.
        freshest = min(s.age_seconds for s in coins)
        if freshest > 15 * 60:
            lines.append(f"⚠️ Prices stale ({_age_str(freshest)} old)")

    lines.append("")
    if state.fear_greed:
        lines.append(
            f"🌡️ Fear &amp; Greed: <b>{state.get_fear_greed_value()}</b> "
            f"({esc(state.fear_greed.get('classification', '?'))})"
        )
    else:
        lines.append("🌡️ Fear &amp; Greed: unavailable")

    if markets:
        lines.append("")
        lines.append("<b>🔮 Top Crypto Markets</b>")
        for i, m in enumerate(markets, 1):
            title = (m.question or "")[:60]
            lines.append(
                f"  {i}. {esc(title)}\n"
                f"     YES=${m.yes_price:.3f} · NO=${m.no_price:.3f} · "
                f"vol ${m.volume:,.0f}"
            )
    else:
        lines.append("")
        lines.append("No crypto Polymarket markets cached.")

    lines.append("━━━━━━━━━━━━━━━━━━━")
    return "\n".join(lines)


def format_crypto_prediction(
    result: dict[str, Any],
    snap: CoinSnapshot,
    market: Market | None,
    market_yes_price: float | None,
    fear_greed: dict[str, Any],
) -> str:
    """Render a full /predict_crypto response with ensemble breakdown + edge."""
    import html

    def esc(s: Any) -> str:
        return html.escape(str(s) if s is not None else "")

    lines: list[str] = ["<b>🔮 APEX CRYPTO PREDICTION</b>", "━━━━━━━━━━━━━━━━━━━━━"]

    if market is not None:
        lines.append(f"📌 Market: {esc((market.question or '')[:80])}")
    lines.append(f"💰 {esc(snap.symbol.upper())}: ${snap.price_usd:,.2f}")
    target = result.get("target_price", 0.0)
    distance_pct = (target - snap.price_usd) / snap.price_usd if snap.price_usd else 0.0
    lines.append(f"🎯 Target: ${target:,.2f} ({distance_pct:+.2%} away)")

    prob = float(result.get("ensemble_prob", 0.5))
    confidence = result.get("confidence")
    lines.append("")
    if market_yes_price is not None:
        yes_price = market_yes_price
        edge = prob - yes_price
        side = "YES" if edge > 0 else "NO"
        entry_price = yes_price if side == "YES" else (1.0 - yes_price)
        lines.append(
            f"📊 Polymarket: YES=${yes_price:.3f} · NO=${1 - yes_price:.3f}"
        )
        lines.append(f"🧠 APEX Model: {prob:.2%}")
        lines.append(f"📈 Edge: {edge:+.2%} ({'YES' if edge > 0 else 'NO'} side)")
        lines.append(f"🎯 Confidence: {esc(getattr(confidence, 'value', str(confidence)))}")
        if abs(edge) >= 0.05:
            lines.append(f"✅ Recommendation: BUY {side} @ ${entry_price:.3f}")
        else:
            lines.append("⏸ Recommendation: no edge (< 5%)")
    else:
        lines.append(f"🧠 APEX Model: {prob:.2%} (no matched Polymarket)")
        lines.append(f"🎯 Confidence: {esc(getattr(confidence, 'value', str(confidence)))}")

    lines.append("")
    lines.append("<b>📋 Model Breakdown</b>")
    estimates = result.get("model_estimates", {})
    weights = result.get("weights", {})
    for name in ("crypto_momentum", "crypto_volatility", "crypto_technical", "crypto_sentiment"):
        est = estimates.get(name)
        w = weights.get(name, 0.0)
        if est is None:
            continue
        factor_hint = ""
        if getattr(est, "factors", None):
            # take first non-meta factor
            for f in est.factors:
                if not f.startswith("target=") and "tf=" not in f:
                    factor_hint = f
                    break
        short_name = name.replace("crypto_", "").capitalize()
        lines.append(
            f"  {esc(short_name):<10} {est.probability:.2%} "
            f"(w={w:.2f}) {esc(factor_hint[:40])}"
        )

    lines.append("")
    if fear_greed:
        lines.append(
            f"🌡️ Fear &amp; Greed: {fear_greed.get('value', '?')} "
            f"({esc(fear_greed.get('classification', '?'))})"
        )

    lines.append("━━━━━━━━━━━━━━━━━━━━━")
    return "\n".join(lines)


def format_system_status(engine: ApexEngine, bot_snapshot: dict, esc: Any) -> str:
    """Render the enhanced /status health dashboard.

    Each integration gets a ✅ / ⚠️ / ❌ badge plus an age or reason.
    Uptime is computed from ``engine.startup_started_at``.
    """
    import time

    ss: ServiceStatus = engine.service_status
    sh = engine.source_health
    state = engine.crypto_state

    def _badge(ok: bool, stale_or_degraded: bool = False) -> str:
        if not ok:
            return "❌"
        if stale_or_degraded:
            return "⚠️"
        return "✅"

    def _row(badge: str, label: str, detail: str) -> str:
        return f"  {badge} <b>{esc(label):<15}</b> {esc(detail)}"

    lines = ["<b>🏥 APEX SYSTEM STATUS</b>", "━━━━━━━━━━━━━━━━━━━"]

    # Database
    lines.append(
        _row(
            _badge(ss.db_healthy),
            "Database",
            "connected" if ss.db_healthy else f"DOWN: {engine.db.last_error or 'unknown'}",
        )
    )

    # Polymarket
    poly_age = sh.age("polymarket")
    lines.append(
        _row(
            _badge(not ss.polymarket_degraded and poly_age != float("inf")),
            "Polymarket",
            f"{len(engine.markets_by_condition)} markets · {_age_str(poly_age)} ago",
        )
    )

    # Odds API
    if not engine.odds.key_configured:
        lines.append(_row("⚠️", "Odds API", "no key configured"))
    elif ss.odds_api_degraded:
        lines.append(
            _row("❌", "Odds API", f"DOWN: {ss.odds_api_reason or 'unknown'}")
        )
    else:
        lines.append(
            _row("✅", "Odds API", f"OK · {_age_str(sh.age('odds'))} ago")
        )

    # Injuries / news
    inj_age = sh.age("injuries")
    total_inj = sum(len(v) for v in engine.injuries_by_sport.values())
    lines.append(
        _row("✅" if total_inj else "⚠️", "ESPN Injuries",
             f"{total_inj} entries · {_age_str(inj_age)} ago")
    )
    news_age = sh.age("news")
    lines.append(
        _row("✅" if engine.fresh_news else "⚠️", "ESPN News",
             f"{len(engine.fresh_news)} items · {_age_str(news_age)} ago")
    )

    # CoinGecko
    n_coins = len(state.top_coins(20))
    if not n_coins:
        lines.append(_row("❌" if ss.coingecko_degraded else "⚠️", "CoinGecko", "no prices"))
    else:
        freshest = min((s.age_seconds for s in state.top_coins(20)), default=float("inf"))
        lines.append(
            _row(
                _badge(not ss.coingecko_degraded, freshest > 900),
                "CoinGecko",
                f"{n_coins} coins · {_age_str(freshest)} ago",
            )
        )

    # Binance klines
    n_kl = len(state.klines)
    if not n_kl:
        lines.append(_row("⚠️" if not ss.binance_degraded else "❌", "Binance", "no klines"))
    else:
        freshest_kl = min(
            (time.monotonic() - t for t in state.klines_fetched_at.values()),
            default=float("inf"),
        )
        lines.append(
            _row(
                _badge(not ss.binance_degraded, freshest_kl > 1800),
                "Binance",
                f"{n_kl} series · {_age_str(freshest_kl)} ago",
            )
        )

    # Fear & Greed
    if state.fear_greed:
        lines.append(
            _row(
                _badge(not ss.fear_greed_degraded),
                "Fear & Greed",
                f"{state.get_fear_greed_value()} · "
                f"{esc(state.fear_greed.get('classification', '?'))} · "
                f"{_age_str(state.fear_greed_age_seconds)} ago",
            )
        )
    else:
        lines.append(
            _row(
                "❌" if ss.fear_greed_degraded else "⚠️",
                "Fear & Greed",
                "unavailable",
            )
        )

    lines.append("")
    mode = "📋 Paper" if bot_snapshot.get("dry_run", True) else "💸 Live"
    lines.append(f"🤖 Bot Mode: {esc(mode)}")
    lines.append(f"💰 Bankroll: ${bot_snapshot.get('bankroll', 0):.2f}")
    lines.append(f"📊 Positions: {bot_snapshot.get('position_count', 0)}")

    if engine.startup_started_at is not None:
        uptime_s = time.monotonic() - engine.startup_started_at
        hours = int(uptime_s // 3600)
        minutes = int((uptime_s % 3600) // 60)
        lines.append(f"⏱️ Uptime: {hours}h {minutes}m")

    running = sum(1 for t in engine._tasks if not t.done())  # noqa: SLF001
    total = len(engine._tasks)  # noqa: SLF001
    lines.append(f"🔁 Tasks: {running}/{total} running")

    lines.append("━━━━━━━━━━━━━━━━━━━")
    return "\n".join(lines)
