"""Tests for time utilities."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from apex.utils.time_utils import (
    age_seconds,
    format_duration,
    freshness_score,
    is_fresh,
    minutes_until,
    parse_iso,
    seconds_until,
    to_utc,
    utc_now,
)


def test_utc_now_aware():
    assert utc_now().tzinfo is not None


def test_to_utc_naive():
    naive = datetime(2026, 1, 1, 12, 0, 0)
    out = to_utc(naive)
    assert out.tzinfo == UTC


def test_age_seconds_positive():
    past = utc_now() - timedelta(seconds=30)
    assert age_seconds(past) == pytest.approx(30.0, abs=1.0)


def test_is_fresh_true():
    past = utc_now() - timedelta(seconds=10)
    assert is_fresh(past, 60)


def test_is_fresh_false():
    past = utc_now() - timedelta(seconds=100)
    assert not is_fresh(past, 60)


def test_seconds_until_future():
    future = utc_now() + timedelta(minutes=5)
    assert seconds_until(future) == pytest.approx(300, abs=2)


def test_minutes_until_future():
    future = utc_now() + timedelta(minutes=5)
    assert minutes_until(future) == pytest.approx(5, abs=0.1)


def test_parse_iso_with_z():
    dt = parse_iso("2026-04-15T12:00:00Z")
    assert dt is not None
    assert dt.tzinfo is not None


def test_parse_iso_invalid():
    assert parse_iso("not a date") is None
    assert parse_iso("") is None


def test_freshness_score_fresh():
    assert freshness_score(0, 300) == 1.0


def test_freshness_score_expired():
    assert freshness_score(300, 300) == 0.0


def test_freshness_score_half():
    assert freshness_score(150, 300) == 0.5


def test_format_duration_seconds():
    assert format_duration(45) == "45s"


def test_format_duration_minutes():
    assert "m" in format_duration(125)


def test_format_duration_hours():
    assert "h" in format_duration(4000)
