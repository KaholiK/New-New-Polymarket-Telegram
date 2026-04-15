"""Tests for Telegram formatters — HTML escape, mobile layout, paper/live distinction."""

from __future__ import annotations

from apex.core.models import (
    Confidence,
    Decision,
    DecisionOutcome,
    Forecast,
    MarketType,
    Position,
    ReasonTrace,
    Side,
    Signal,
    Sport,
    Trade,
    TradeStatus,
)
from apex.telegram.formatters import (
    esc,
    format_decision,
    format_forecast,
    format_help,
    format_pnl,
    format_positions,
    format_status,
    format_trade,
    paper_prefix,
)
from apex.telegram.keyboards import parse_callback


def test_esc_escapes_html():
    assert esc("<script>") == "&lt;script&gt;"
    assert esc('a"b') == "a&quot;b"


def test_esc_handles_none():
    assert esc(None) == ""


def test_esc_handles_int():
    assert esc(42) == "42"


def test_paper_prefix_present():
    assert "📋" in paper_prefix(True)


def test_paper_prefix_absent():
    assert paper_prefix(False) == ""


def test_format_forecast_contains_teams():
    fc = Forecast(
        event_id="e", market_id="m",
        sport=Sport.NBA, market_type=MarketType.MONEYLINE,
        home_team="<Lakers>",
        away_team="Celtics",
        side=Side.YES,
        ensemble_prob=0.55, market_price=0.48,
        confidence=Confidence.MEDIUM,
    )
    out = format_forecast(fc)
    # HTML-escaped team name
    assert "&lt;Lakers&gt;" in out
    assert "Celtics" in out


def test_format_decision_has_side_and_strategy():
    fc = Forecast(
        event_id="e", market_id="m",
        sport=Sport.NBA, market_type=MarketType.MONEYLINE,
        home_team="A", away_team="B", side=Side.YES,
    )
    sig = Signal(
        strategy="fair_value", market_id="m", event_id="e",
        side=Side.YES, size_hint_usd=0.0,
        edge=0.05, edge_zscore=2.0, confidence=Confidence.MEDIUM,
        forecast=fc,
    )
    d = Decision(
        signal=sig,
        outcome=DecisionOutcome.APPROVE,
        final_size_usd=1.0,
        trace=ReasonTrace(score=80.0),
    )
    out = format_decision(d, dry_run=True)
    assert "APPROVE" in out
    assert "fair_value" in out
    assert "📋" in out


def test_format_decision_live_no_paper_prefix():
    fc = Forecast(event_id="e", market_id="m", sport=Sport.NBA, market_type=MarketType.MONEYLINE, home_team="A", away_team="B", side=Side.YES)
    sig = Signal(strategy="s", market_id="m", event_id="e", side=Side.YES, size_hint_usd=0.0, edge=0.0, edge_zscore=0.0, confidence=Confidence.LOW, forecast=fc)
    d = Decision(signal=sig, outcome=DecisionOutcome.APPROVE, final_size_usd=1.0, trace=ReasonTrace(score=50.0))
    out = format_decision(d, dry_run=False)
    assert "📋" not in out


def test_format_trade_includes_status():
    t = Trade(id="trade123", market_id="m", side=Side.YES, size_usd=1.0, entry_price=0.5, status=TradeStatus.RESOLVED_WIN)
    out = format_trade(t, dry_run=True)
    assert "resolved_win" in out.lower() or "RESOLVED_WIN" in out.upper()


def test_format_status_paper():
    snap = {"dry_run": True, "bankroll": 20.0, "peak_bankroll": 20.0, "paused": False, "killed": False}
    out = format_status(snap)
    assert "PAPER" in out


def test_format_status_live():
    snap = {"dry_run": False, "bankroll": 20.0, "peak_bankroll": 20.0}
    out = format_status(snap)
    assert "LIVE" in out


def test_format_status_killed():
    snap = {"dry_run": True, "bankroll": 5.0, "killed": True, "kill_reason": "<bad>"}
    out = format_status(snap)
    assert "KILLED" in out
    # reason is escaped
    assert "&lt;bad&gt;" in out


def test_format_positions_empty():
    assert "No open positions" in format_positions([])


def test_format_positions_has_side():
    p = Position(
        market_id="m1" * 5, token_id="t", side=Side.YES,
        contracts=10, avg_entry_price=0.5, cost_basis_usd=5.0,
        unrealized_pnl=1.0,
    )
    out = format_positions([p])
    assert "YES" in out


def test_format_pnl_contains_numbers():
    out = format_pnl(1.5, 0.5, 20.0)
    assert "+1.50" in out or "1.50" in out


def test_format_help_non_empty():
    assert len(format_help()) > 50


def test_parse_callback_simple():
    action, verb, payload = parse_callback("confirm|kill|foo")
    assert action == "confirm"
    assert verb == "kill"
    assert payload == "foo"


def test_parse_callback_handles_colon_in_payload():
    # Polymarket condition IDs may contain colons if prefixed. The rsplit/split logic
    # should preserve the full payload.
    action, verb, payload = parse_callback("confirm|bet|abc:123:def")
    assert action == "confirm"
    assert verb == "bet"
    assert payload == "abc:123:def"


def test_parse_callback_empty():
    assert parse_callback("") == ("", "", "")


def test_parse_callback_short():
    a, v, p = parse_callback("cancel")
    assert a == "cancel"
    assert v == ""
    assert p == ""
