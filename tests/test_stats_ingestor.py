"""Tests for stats ingestor — especially NFL pointsFor/season-total handling."""

from __future__ import annotations

from apex.quant.data.stats_ingestor import off_def_ratings, parse_standings


def _nba_entry(team: str, wins: int, losses: int, avg_pf: float, avg_pa: float) -> dict:
    return {
        "team": {"displayName": team},
        "stats": [
            {"name": "wins", "value": wins},
            {"name": "losses", "value": losses},
            {"name": "gamesPlayed", "value": wins + losses},
            {"name": "avgPointsFor", "value": avg_pf},
            {"name": "avgPointsAgainst", "value": avg_pa},
        ],
    }


def _nfl_entry(team: str, wins: int, losses: int, pf_total: float, pa_total: float, games: int) -> dict:
    return {
        "team": {"displayName": team},
        "stats": [
            {"name": "wins", "value": wins},
            {"name": "losses", "value": losses},
            {"name": "gamesPlayed", "value": games},
            # NFL uses season totals, not per-game averages
            {"name": "pointsFor", "value": pf_total},
            {"name": "pointsAgainst", "value": pa_total},
        ],
    }


def test_parse_nba_standings():
    raw = {"children": [{"standings": {"entries": [_nba_entry("Lakers", 50, 32, 115.0, 110.0)]}}]}
    stats = parse_standings(raw, "NBA")
    assert len(stats) == 1
    assert stats[0].team == "Lakers"
    assert stats[0].avg_points_for == 115.0


def test_parse_nfl_uses_totals():
    # NFL season totals → must divide by games_played
    raw = {"children": [{"standings": {"entries": [_nfl_entry("49ers", 12, 5, 420.0, 340.0, 17)]}}]}
    stats = parse_standings(raw, "NFL")
    assert len(stats) == 1
    # 420 / 17 ≈ 24.7 per game
    assert abs(stats[0].avg_points_for - 420.0 / 17.0) < 0.01


def test_parse_empty():
    assert parse_standings({}, "NBA") == []
    assert parse_standings(None, "NBA") == []  # type: ignore


def test_parse_missing_team():
    raw = {"children": [{"standings": {"entries": [{"stats": []}]}}]}
    assert parse_standings(raw, "NBA") == []


def test_off_def_ratings_normalized():
    stats = parse_standings(
        {
            "children": [
                {
                    "standings": {
                        "entries": [
                            _nba_entry("A", 50, 32, 120.0, 110.0),
                            _nba_entry("B", 40, 42, 108.0, 115.0),
                        ]
                    }
                }
            ]
        },
        "NBA",
    )
    ratings = off_def_ratings(stats, "NBA")
    # A has higher offense → off rating > 100
    assert ratings["A"][0] > ratings["B"][0]


def test_off_def_ratings_empty():
    assert off_def_ratings([], "NBA") == {}
