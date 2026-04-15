"""Tests for market status guard."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from apex.core.models import Market, Sport
from apex.market.status_guard import check_status, locked_markets_within


def _market(accepting=True, end_offset_hours=4.0) -> Market:
    return Market(
        condition_id="c1",
        question="q",
        sport=Sport.NBA,
        yes_token_id="y",
        no_token_id="n",
        end_date=datetime.now(UTC) + timedelta(hours=end_offset_hours),
        accepting_orders=accepting,
    )


def test_ok_market():
    assert check_status(_market()).ok


def test_not_accepting():
    r = check_status(_market(accepting=False))
    assert not r.ok
    assert "not_accepting_orders" in r.reasons


def test_past_event():
    r = check_status(_market(end_offset_hours=-1))
    assert not r.ok
    assert any("event_past" in x for x in r.reasons) or any("too_close" in x for x in r.reasons)


def test_min_minutes_to_start():
    # Market starts in 30 min; require at least 60 min buffer → fail
    r = check_status(_market(end_offset_hours=0.5), min_minutes_to_start=60)
    assert not r.ok


def test_no_tokens():
    m = Market(condition_id="c", question="q", sport=Sport.NBA, end_date=datetime.now(UTC) + timedelta(hours=2))
    r = check_status(m)
    assert not r.ok
    assert "no_tokens" in r.reasons


def test_locked_markets_within():
    soon = _market(end_offset_hours=0.2)  # 12 min out
    later = _market(end_offset_hours=4)
    locked = locked_markets_within([soon, later], timedelta(minutes=30))
    assert soon in locked
    assert later not in locked
