"""Tests for The Odds API ingestion + parsing."""

from __future__ import annotations

from apex.data.odds_ingestor import BOOKMAKER_WEIGHTS, book_weight, parse_odds_events


def test_book_weight_sharp():
    assert book_weight("pinnacle") == BOOKMAKER_WEIGHTS["pinnacle"]
    assert book_weight("circa") == BOOKMAKER_WEIGHTS["circa"]


def test_book_weight_default():
    assert book_weight("random_book_xyz") == BOOKMAKER_WEIGHTS["default"]


def test_book_weight_case_insensitive():
    assert book_weight("Pinnacle") == book_weight("pinnacle")


def test_book_weight_empty():
    assert book_weight("") == BOOKMAKER_WEIGHTS["default"]


def test_parse_odds_events_basic():
    raw = [
        {
            "id": "evt1",
            "home_team": "Lakers",
            "away_team": "Celtics",
            "commence_time": "2026-04-15T23:00:00Z",
            "bookmakers": [
                {
                    "key": "pinnacle",
                    "markets": [
                        {
                            "key": "h2h",
                            "outcomes": [
                                {"name": "Lakers", "price": 2.0},
                                {"name": "Celtics", "price": 2.0},
                            ],
                        }
                    ],
                }
            ],
        }
    ]
    snaps = parse_odds_events(raw, "NBA")
    assert len(snaps) == 1
    assert snaps[0].home_team == "Lakers"
    assert snaps[0].home_odds == 2.0


def test_parse_odds_events_empty():
    assert parse_odds_events([], "NBA") == []


def test_parse_odds_events_missing_outcomes():
    raw = [
        {
            "id": "evt1",
            "home_team": "Lakers",
            "away_team": "Celtics",
            "bookmakers": [
                {
                    "key": "pinnacle",
                    "markets": [{"key": "h2h", "outcomes": [{"name": "Lakers", "price": 2.0}]}],
                }
            ],
        }
    ]
    snaps = parse_odds_events(raw, "NBA")
    assert snaps == []  # can't form full snapshot with one side


def test_parse_odds_events_invalid_price():
    raw = [
        {
            "id": "evt1",
            "home_team": "A",
            "away_team": "B",
            "bookmakers": [
                {
                    "key": "x",
                    "markets": [
                        {
                            "key": "h2h",
                            "outcomes": [
                                {"name": "A", "price": 0.9},
                                {"name": "B", "price": 2.0},
                            ],
                        }
                    ],
                }
            ],
        }
    ]
    # Price <= 1.0 is filtered
    snaps = parse_odds_events(raw, "NBA")
    assert snaps == []


def test_parse_odds_events_non_list_input():
    assert parse_odds_events({}, "NBA") == []
    assert parse_odds_events(None, "NBA") == []  # type: ignore
