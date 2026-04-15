"""Tests for catalog mapper — especially the Thunder/under regression."""

from __future__ import annotations

from apex.core.models import MarketType, Sport
from apex.market.catalog_mapper import (
    detect_league,
    detect_market_type,
    detect_sport,
    map_catalog,
)


class TestDetectSport:
    def test_nba_keyword(self):
        assert detect_sport("NBA Lakers vs Celtics") == Sport.NBA

    def test_nfl_keyword(self):
        assert detect_sport("NFL Cowboys vs Eagles") == Sport.NFL

    def test_unknown(self):
        assert detect_sport("Will it rain?") == Sport.UNKNOWN

    def test_prefer_tags(self):
        assert detect_sport("Some question", tags=["NBA"]) == Sport.NBA

    def test_none_tags_safe(self):
        # Gamma tags are often None — must not crash
        assert detect_sport("NBA something", tags=None) == Sport.NBA

    def test_empty_text(self):
        assert detect_sport("") == Sport.UNKNOWN


class TestDetectMarketType:
    def test_thunder_is_moneyline_not_total(self):
        # THE regression: "Oklahoma City Thunder" contains "under" as a substring.
        # Without \b word boundaries, this misclassifies as TOTAL.
        assert detect_market_type("Oklahoma City Thunder vs Lakers") == MarketType.MONEYLINE

    def test_thunder_moneyline_alt(self):
        assert detect_market_type("Will Thunder beat Lakers") == MarketType.MONEYLINE

    def test_real_total_over(self):
        assert detect_market_type("Over 220.5 total points") == MarketType.TOTAL

    def test_real_total_under(self):
        assert detect_market_type("Under 45 total runs") == MarketType.TOTAL

    def test_spread(self):
        assert detect_market_type("Lakers -5.5 spread") == MarketType.SPREAD

    def test_prop(self):
        assert detect_market_type("LeBron over 25.5 points") in (MarketType.PROP, MarketType.TOTAL)

    def test_moneyline_vs(self):
        assert detect_market_type("Lakers vs Celtics") == MarketType.MONEYLINE

    def test_moneyline_at(self):
        assert detect_market_type("Lakers @ Celtics") == MarketType.MONEYLINE

    def test_blank(self):
        assert detect_market_type("") == MarketType.OTHER

    def test_other_text(self):
        # No recognizable pattern
        assert detect_market_type("Random question about nothing") == MarketType.OTHER


class TestMapCatalog:
    def test_full_mapping_nba(self):
        info = map_catalog("NBA Lakers vs Celtics moneyline")
        assert info.sport == Sport.NBA
        assert info.league == "NBA"
        assert info.market_type == MarketType.MONEYLINE
        assert info.confidence > 0.5

    def test_confidence_bump_for_canonical_teams(self):
        info_good = map_catalog("NBA Lakers vs Celtics")
        info_bad = map_catalog("NBA made-up-team vs other-team")
        assert info_good.confidence >= info_bad.confidence

    def test_none_tags_no_crash(self):
        info = map_catalog("NBA Lakers vs Celtics", tags=None)
        assert info.sport == Sport.NBA

    def test_unknown_sport_zero_league(self):
        info = map_catalog("Will it rain?")
        assert info.sport == Sport.UNKNOWN
        assert info.league == ""

    def test_thunder_title_regression(self):
        # Full integration: OKC Thunder moneyline must NOT be classified as TOTAL
        info = map_catalog("NBA Thunder vs Lakers")
        assert info.market_type == MarketType.MONEYLINE
        assert info.sport == Sport.NBA


def test_detect_league_mapping():
    assert detect_league(Sport.NBA) == "NBA"
    assert detect_league(Sport.NFL) == "NFL"
    assert detect_league(Sport.UNKNOWN) == ""
