"""HTML-escaped, mobile-friendly message formatting.

CRITICAL: html.escape() ALL dynamic content before embedding in HTML messages.
"""

from __future__ import annotations

import html
from typing import Any

from apex.core.models import Decision, Forecast, Trade


def esc(s: Any) -> str:
    """Shorthand for html.escape on any value."""
    return html.escape(str(s) if s is not None else "")


def paper_prefix(dry_run: bool) -> str:
    return "📋 " if dry_run else ""


def format_forecast(fc: Forecast) -> str:
    """Format a Forecast for the /predict command."""
    lines: list[str] = []
    lines.append(f"🔮 <b>{esc('APEX FORECAST')}</b>: {esc(fc.home_team)} vs {esc(fc.away_team)}")
    lines.append(f"📅 {esc(fc.created_at.strftime('%b %d'))} · {esc(fc.sport.value)} · {esc(fc.market_type.value)}")
    lines.append("")
    lines.append("<b>Model Estimates:</b>")
    for name, est in fc.model_estimates.items():
        lines.append(f"  {esc(name)}: {est.probability:.3f} (±{est.uncertainty:.3f})")
    lines.append("")
    lines.append(f"📊 <b>Ensemble:</b> {fc.ensemble_prob:.3f} ± {fc.ensemble_std:.3f}")
    lines.append(f"💰 <b>Polymarket:</b> {fc.market_price:.3f}")
    lines.append(f"📈 <b>Edge:</b> {fc.raw_edge:+.3f} (z={fc.edge_zscore:+.2f})")
    lines.append(f"🎯 <b>Confidence:</b> {esc(fc.confidence.value)}")
    if fc.key_factors:
        lines.append("")
        lines.append("<b>Key Factors:</b>")
        for f in fc.key_factors[:5]:
            lines.append(f"  • {esc(f)}")
    lines.append("")
    lines.append(f"💵 Kelly: {fc.kelly_fraction:.3%} · side {esc(fc.side.value)}")
    status = "ACTIONABLE" if fc.is_actionable else "NOT ACTIONABLE"
    lines.append(f"⚡ Status: {esc(status)}")
    if fc.rejection_reasons:
        lines.append("Reasons: " + esc(", ".join(fc.rejection_reasons)))
    return "\n".join(lines)


def format_decision(d: Decision, dry_run: bool = True) -> str:
    prefix = paper_prefix(dry_run)
    sig = d.signal
    lines = [
        f"{prefix}<b>{esc(d.outcome.value)}</b> · {esc(sig.strategy)}",
        f"Market: {esc(sig.market_id)}",
        f"Side: {esc(sig.side.value)} · Size: ${d.final_size_usd:.2f}",
        f"Score: {d.trace.score:.1f} · Edge: {sig.edge:+.3f} (z={sig.edge_zscore:+.2f})",
    ]
    if d.trace.reasons:
        lines.append("Reasons: " + esc(" | ".join(d.trace.reasons)))
    return "\n".join(lines)


def format_trade(t: Trade, dry_run: bool = True) -> str:
    prefix = paper_prefix(dry_run)
    return (
        f"{prefix}<b>Trade</b> {esc(t.id[:8])} · {esc(t.strategy)}\n"
        f"{esc(t.market_id)} · {esc(t.side.value)} · ${t.size_usd:.2f} @ {t.entry_price:.3f}\n"
        f"Status: {esc(t.status.value)} · PnL: ${t.pnl:+.2f}"
    )


def format_status(snapshot: dict) -> str:
    dry_run = snapshot.get("dry_run", True)
    mode = "📋 PAPER" if dry_run else "💸 LIVE"
    lines = [
        f"<b>APEX Status</b> · {esc(mode)}",
        f"Bankroll: ${snapshot.get('bankroll', 0):.2f}",
        f"Peak: ${snapshot.get('peak_bankroll', 0):.2f}",
        f"Exposure: ${snapshot.get('total_exposure', 0):.2f}",
        f"Positions: {snapshot.get('position_count', 0)}",
        f"Wins/Losses: {snapshot.get('wins', 0)}/{snapshot.get('losses', 0)}",
        f"Daily DD: {snapshot.get('daily_drawdown', 0):.2%}",
        f"Peak DD: {snapshot.get('drawdown_from_peak', 0):.2%}",
    ]
    if snapshot.get("killed"):
        lines.append(f"🛑 <b>KILLED</b>: {esc(snapshot.get('kill_reason', ''))}")
    elif snapshot.get("paused"):
        lines.append(f"⏸ <b>PAUSED</b>: {esc(snapshot.get('pause_reason', ''))}")
    return "\n".join(lines)


def format_positions(positions: list) -> str:
    if not positions:
        return "No open positions."
    lines = ["<b>Open Positions</b>"]
    for p in positions:
        lines.append(
            f"{esc(p.market_id[:10])} · {esc(p.side.value)} · "
            f"{p.contracts:.2f} @ {p.avg_entry_price:.3f} · PnL: ${p.unrealized_pnl:+.2f}"
        )
    return "\n".join(lines)


def format_pnl(realized: float, unrealized: float, bankroll: float) -> str:
    total = realized + unrealized
    return (
        f"<b>P&amp;L</b>\n"
        f"Realized: ${realized:+.2f}\n"
        f"Unrealized: ${unrealized:+.2f}\n"
        f"Total: ${total:+.2f}\n"
        f"Bankroll: ${bankroll:.2f}"
    )


def format_help() -> str:
    return (
        "<b>APEX Commands</b>\n"
        "/start /help /status /health\n"
        "/markets /scan /predict &lt;q&gt; /signals\n"
        "/bet &lt;ticker&gt; &lt;YES|NO&gt; &lt;$&gt;\n"
        "/positions /orders /fills\n"
        "/pnl /bankroll /exposure\n"
        "/risk /diagnostics /logs\n"
        "/models /calibration /clv /forecast_history\n"
        "/heat /arb /costs\n"
        "/setstop &lt;ticker&gt; &lt;s%&gt; [t%] [tr%]\n"
        "/hedge &lt;ticker&gt; [pct]\n"
        "/pause /resume /kill /cancel_all\n"
        "/paper_on /paper_off /smoke"
    )
