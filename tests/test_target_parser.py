"""Price-target extractor for crypto market titles."""

from __future__ import annotations

import pytest

from apex.telegram.commands import _extract_target_from_title


@pytest.mark.parametrize(
    "title,expected",
    [
        ("Will BTC hit $110,000 by June?", 110_000),
        ("ETH above $4K by Q3?", 4_000),
        ("SOL reach 200 by end of year", 200),
        ("Bitcoin above $100K in 2026?", 100_000),
        ("Dogecoin to 1$ by 2026", 1.0),
        ("no numbers here", None),
    ],
)
def test_extract_target(title: str, expected: float | None) -> None:
    got = _extract_target_from_title(title)
    if expected is None:
        assert got is None
    else:
        assert got == pytest.approx(expected)


def test_year_alone_does_not_match() -> None:
    # A bare "2025" should be rejected as a year (it's in the year range, no $/k/m).
    assert _extract_target_from_title("BTC forecast 2025") is None
