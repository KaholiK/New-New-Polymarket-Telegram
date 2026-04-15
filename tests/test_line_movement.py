"""Tests for line movement tracker."""

from __future__ import annotations

from datetime import UTC, datetime

from apex.core.models import MarketType, OddsSnapshot
from apex.data.line_movement import LineMovementTracker


def _snap(book: str, home_p: float, away_p: float, event_id: str = "e1") -> OddsSnapshot:
    return OddsSnapshot(
        event_id=event_id,
        bookmaker=book,
        sport="NBA",
        home_team="A",
        away_team="B",
        home_odds=1.0 / home_p,
        away_odds=1.0 / away_p,
        home_implied_prob=home_p,
        away_implied_prob=away_p,
        market_type=MarketType.MONEYLINE,
        fetched_at=datetime.now(UTC),
    )


def test_first_ingest_no_moves():
    t = LineMovementTracker()
    moves = t.ingest([_snap("pinnacle", 0.52, 0.50)])
    assert moves == []


def test_detects_change():
    t = LineMovementTracker()
    t.ingest([_snap("pinnacle", 0.52, 0.50)])
    moves = t.ingest([_snap("pinnacle", 0.55, 0.47)])
    assert len(moves) == 1
    assert moves[0].side == "home"
    assert moves[0].delta_prob > 0


def test_no_change_below_threshold():
    t = LineMovementTracker()
    t.ingest([_snap("pinnacle", 0.52, 0.50)])
    moves = t.ingest([_snap("pinnacle", 0.521, 0.499)])  # tiny
    assert moves == []
