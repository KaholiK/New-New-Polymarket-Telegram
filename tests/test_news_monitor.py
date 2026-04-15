"""Tests for news monitor — SHA256 fingerprinting."""

from __future__ import annotations

from apex.data.news_monitor import NewsMonitor, news_fingerprint, parse_news


def test_fingerprint_stable():
    f1 = news_fingerprint("Lakers sign MVP", "2026-04-15T12:00:00+00:00")
    f2 = news_fingerprint("Lakers sign MVP", "2026-04-15T12:00:00+00:00")
    assert f1 == f2


def test_fingerprint_different():
    f1 = news_fingerprint("Lakers sign MVP", "t1")
    f2 = news_fingerprint("Celtics sign MVP", "t1")
    assert f1 != f2


def test_fingerprint_case_insensitive():
    f1 = news_fingerprint("LAKERS SIGN MVP", "t")
    f2 = news_fingerprint("Lakers sign MVP", "t")
    assert f1 == f2


def test_parse_news_empty():
    assert parse_news({}, "NBA") == []
    assert parse_news(None, "NBA") == []  # type: ignore


def test_parse_news_basic():
    raw = {
        "articles": [
            {
                "headline": "Star Player Injured",
                "description": "Will miss 2-4 weeks",
                "published": "2026-04-15T08:00:00Z",
            }
        ]
    }
    items = parse_news(raw, "NBA")
    assert len(items) == 1
    assert items[0].headline == "Star Player Injured"
    assert items[0].fingerprint


def test_filter_new_dedup():
    mon = NewsMonitor()
    raw = {"articles": [{"headline": "H1", "published": "2026-04-15T08:00:00Z"}]}
    items = parse_news(raw, "NBA")
    first = mon.filter_new(items)
    second = mon.filter_new(items)
    assert len(first) == 1
    assert len(second) == 0  # same fingerprint, dedup'd
