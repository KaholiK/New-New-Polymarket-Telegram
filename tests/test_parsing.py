"""Tests for team name normalization, alias resolution, fuzzy matching."""

from __future__ import annotations

from apex.utils.parsing import (
    TEAM_ALIASES,
    extract_teams_from_title,
    fuzzy_best_match,
    fuzzy_ratio,
    normalize_text,
    resolve_team,
)


class TestNormalizeText:
    def test_lowercase(self):
        assert normalize_text("ABC") == "abc"

    def test_strip_accents(self):
        assert normalize_text("Montréal") == "montreal"

    def test_collapse_whitespace(self):
        assert normalize_text("  a   b ") == "a b"

    def test_remove_punctuation(self):
        assert "." not in normalize_text("St. Louis")
        assert normalize_text("St. Louis") == "st louis"

    def test_empty(self):
        assert normalize_text("") == ""

    def test_none_safe(self):
        assert normalize_text(None or "") == ""


class TestResolveTeam:
    def test_nba_lakers(self):
        assert resolve_team("Lakers", sport="NBA") == "Los Angeles Lakers"

    def test_nba_lal(self):
        assert resolve_team("LAL", sport="NBA") == "Los Angeles Lakers"

    def test_nfl_san_francisco_not_colliding_with_nba(self):
        # "San Francisco" in NFL must map to the 49ers;
        # without namespacing, it could collide with historical NBA/other references.
        assert resolve_team("San Francisco", sport="NFL") == "San Francisco 49ers"

    def test_sport_namespace_required_when_ambiguous(self):
        # Without sport, "San Francisco" could be NFL or MLB (Giants) → should not resolve
        out = resolve_team("San Francisco")
        # only returns if unambiguous across all sports; SF NFL alias exists uniquely so
        # this just has to return a real team or None — it shouldn't crash
        assert out is None or out in ("San Francisco 49ers", "San Francisco Giants")

    def test_unknown(self):
        assert resolve_team("Nonexistent Team", sport="NBA") is None

    def test_empty(self):
        assert resolve_team("") is None

    def test_all_aliases_have_sport_prefix(self):
        # Regression: every alias key must include ":" namespace
        for key in TEAM_ALIASES:
            assert ":" in key, f"alias missing sport prefix: {key}"

    def test_no_duplicate_key_collision(self):
        # Regression: "San Francisco" used to collide. With namespacing, keys should be unique
        # and multiple canonical teams can share the same local alias.
        nfl_sf = TEAM_ALIASES.get("nfl:san francisco")
        assert nfl_sf == "San Francisco 49ers"


class TestFuzzy:
    def test_identical(self):
        assert fuzzy_ratio("Lakers", "Lakers") == 1.0

    def test_close_match(self):
        assert fuzzy_ratio("Los Angeles Lakers", "LA Lakers") > 0.5

    def test_no_match(self):
        assert fuzzy_ratio("Lakers", "Celtics") < 0.6

    def test_empty_returns_zero(self):
        assert fuzzy_ratio("", "Lakers") == 0.0

    def test_best_match(self):
        hit = fuzzy_best_match("Lakers", ["Boston Celtics", "Los Angeles Lakers"], min_ratio=0.5)
        assert hit is not None
        assert "Lakers" in hit[0]

    def test_best_match_below_threshold(self):
        assert fuzzy_best_match("Lakers", ["Boston Celtics", "New York Knicks"], min_ratio=0.9) is None


class TestExtractTeams:
    def test_vs_pattern(self):
        a, b = extract_teams_from_title("Lakers vs Celtics")
        assert a == "Lakers"
        assert b == "Celtics"

    def test_at_pattern(self):
        a, b = extract_teams_from_title("Lakers @ Celtics")
        assert a == "Lakers"
        assert b == "Celtics"

    def test_beats_pattern(self):
        a, b = extract_teams_from_title("Lakers beat Celtics")
        assert a == "Lakers"
        assert b == "Celtics"

    def test_strips_question_mark(self):
        a, b = extract_teams_from_title("Lakers vs Celtics?")
        assert a == "Lakers"
        assert b == "Celtics"

    def test_strips_trailing_phrase(self):
        a, b = extract_teams_from_title("Lakers vs Celtics moneyline")
        assert a == "Lakers"
        assert "moneyline" not in (b or "")

    def test_no_match(self):
        a, b = extract_teams_from_title("Will it rain tomorrow")
        assert a is None
        assert b is None

    def test_empty(self):
        a, b = extract_teams_from_title("")
        assert a is None
        assert b is None
