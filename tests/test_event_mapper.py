"""Tests for event mapper — fuzzy matching markets to ESPN events."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from apex.core.models import Market, Sport
from apex.market.event_mapper import EspnEvent, map_market_to_event


def _market(home: str, away: str, when: datetime, sport: Sport = Sport.NBA) -> Market:
    return Market(
        condition_id="cid",
        question=f"{home} vs {away}",
        sport=sport,
        league=sport.value if sport != Sport.UNKNOWN else "",
        home_team=home,
        away_team=away,
        yes_token_id="t1",
        no_token_id="t2",
        end_date=when,
    )


def _event(home: str, away: str, when: datetime, sport: Sport = Sport.NBA, status: str = "scheduled") -> EspnEvent:
    return EspnEvent(
        event_id=f"evt_{home}_{away}",
        sport=sport,
        league=sport.value,
        home_team=home,
        away_team=away,
        start_time=when,
        status=status,
    )


def test_exact_match():
    t = datetime.now(UTC) + timedelta(hours=3)
    m = _market("Los Angeles Lakers", "Boston Celtics", t)
    ev = _event("Los Angeles Lakers", "Boston Celtics", t)
    res = map_market_to_event(m, [ev])
    assert res.event_id == ev.event_id
    assert res.confidence > 0.9


def test_swapped_home_away():
    t = datetime.now(UTC) + timedelta(hours=3)
    m = _market("Lakers", "Celtics", t)
    ev = _event("Celtics", "Lakers", t)
    res = map_market_to_event(m, [ev])
    # Swapped orientation should still match
    assert res.event_id == ev.event_id


def test_unknown_sport():
    t = datetime.now(UTC) + timedelta(hours=3)
    m = _market("A", "B", t, sport=Sport.UNKNOWN)
    ev = _event("A", "B", t, sport=Sport.UNKNOWN)
    res = map_market_to_event(m, [ev])
    assert res.event_id is None


def test_missing_teams():
    t = datetime.now(UTC) + timedelta(hours=3)
    m = Market(condition_id="x", question="?", sport=Sport.NBA, yes_token_id="y", no_token_id="n", end_date=t)
    ev = _event("Lakers", "Celtics", t)
    res = map_market_to_event(m, [ev])
    assert res.event_id is None


def test_past_window():
    now = datetime.now(UTC)
    m = _market("Lakers", "Celtics", now + timedelta(days=10))
    ev = _event("Lakers", "Celtics", now)
    res = map_market_to_event(m, [ev], time_window_hours=12)
    # Out of window → no match
    assert res.event_id is None


def test_final_status_skipped():
    t = datetime.now(UTC) + timedelta(hours=3)
    m = _market("Lakers", "Celtics", t)
    ev = _event("Lakers", "Celtics", t, status="final")
    res = map_market_to_event(m, [ev])
    assert res.event_id is None


def test_postponed_skipped():
    t = datetime.now(UTC) + timedelta(hours=3)
    m = _market("Lakers", "Celtics", t)
    ev = _event("Lakers", "Celtics", t, status="postponed")
    res = map_market_to_event(m, [ev])
    assert res.event_id is None


def test_multiple_candidates_picks_best():
    t = datetime.now(UTC) + timedelta(hours=3)
    m = _market("Los Angeles Lakers", "Boston Celtics", t)
    ev_bad = _event("Warriors", "Celtics", t)
    ev_good = _event("Lakers", "Celtics", t)
    res = map_market_to_event(m, [ev_bad, ev_good])
    assert res.event_id == ev_good.event_id


def test_weak_match_below_threshold():
    t = datetime.now(UTC) + timedelta(hours=3)
    m = _market("Lakers", "Celtics", t)
    ev = _event("CompletelyDifferent", "Other", t)
    res = map_market_to_event(m, [ev])
    # Confidence will be low
    assert res.confidence < 0.7
