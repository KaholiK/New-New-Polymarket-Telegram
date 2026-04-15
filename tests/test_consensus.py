"""Tests for consensus builder — weighted vig removal."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from apex.core.models import MarketType, OddsSnapshot
from apex.data.consensus_builder import build_consensus


def _snap(book: str, home_implied: float, away_implied: float, event_id: str = "e1") -> OddsSnapshot:
    return OddsSnapshot(
        event_id=event_id,
        bookmaker=book,
        sport="NBA",
        home_team="Lakers",
        away_team="Celtics",
        home_odds=1.0 / home_implied,
        away_odds=1.0 / away_implied,
        home_implied_prob=home_implied,
        away_implied_prob=away_implied,
        market_type=MarketType.MONEYLINE,
        fetched_at=datetime.now(UTC),
    )


def test_single_book():
    snaps = [_snap("pinnacle", 0.52, 0.50)]  # with vig, sum > 1
    cons = build_consensus(snaps)
    assert "e1" in cons
    c = cons["e1"]
    # After vig removal and normalization, sum ≈ 1
    assert c.home_prob + c.away_prob == pytest.approx(1.0, abs=1e-3)


def test_sharp_book_has_more_weight():
    # Pinnacle = 3.0 weight says Lakers 0.60
    # DraftKings = 1.0 weight says Lakers 0.40
    snaps = [
        _snap("pinnacle", 0.60, 0.42),
        _snap("draftkings", 0.40, 0.62),
    ]
    cons = build_consensus(snaps)["e1"]
    # Weighted toward Pinnacle's view: should be > 0.5
    assert cons.home_prob > 0.5


def test_empty_input():
    assert build_consensus([]) == {}


def test_book_count():
    snaps = [
        _snap("pinnacle", 0.52, 0.50),
        _snap("draftkings", 0.50, 0.52),
        _snap("fanduel", 0.51, 0.51),
    ]
    cons = build_consensus(snaps)["e1"]
    assert cons.book_count == 3
    assert cons.weighted_book_count > 3.0  # Pinnacle amplifies it


def test_multiple_events_separated():
    snaps = [
        _snap("pinnacle", 0.52, 0.50, event_id="e1"),
        _snap("pinnacle", 0.30, 0.72, event_id="e2"),
    ]
    cons = build_consensus(snaps)
    assert "e1" in cons and "e2" in cons
    assert cons["e1"].home_prob > cons["e2"].home_prob
