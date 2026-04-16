"""Polymarket discovery: pagination terminates correctly on short pages,
empty pages, and the max_pages safety cap.
"""

from __future__ import annotations

from typing import Any

import pytest

from apex.market.discovery import MarketDiscovery


class _FakeClient:
    """Replays a scripted list of pages from ``list_markets``."""

    def __init__(self, pages: list[list[dict[str, Any]]]) -> None:
        self.pages = list(pages)
        self.calls: list[dict[str, Any]] = []

    async def list_markets(self, *, closed: bool, limit: int, offset: int) -> list[dict[str, Any]]:
        self.calls.append({"closed": closed, "limit": limit, "offset": offset})
        if not self.pages:
            return []
        return self.pages.pop(0)


def _raw(condition_id: str) -> dict[str, Any]:
    return {
        "conditionId": condition_id,
        "question": f"Will {condition_id} win?",
        "clobTokenIds": f'["y_{condition_id}","n_{condition_id}"]',
        "volume": 1000.0,
        "liquidity": 100.0,
        "outcomePrices": '["0.5","0.5"]',
        "acceptingOrders": True,
    }


@pytest.mark.asyncio
async def test_short_page_terminates() -> None:
    """A page shorter than page_size ends the loop immediately."""
    client = _FakeClient([[_raw(f"m{i}") for i in range(30)]])
    disc = MarketDiscovery(client)
    await disc.scan_active_markets(max_markets=500, inter_page_delay_s=0.0)
    assert len(client.calls) == 1


@pytest.mark.asyncio
async def test_empty_page_terminates() -> None:
    client = _FakeClient([[_raw(f"a{i}") for i in range(100)], []])
    disc = MarketDiscovery(client)
    await disc.scan_active_markets(max_markets=500, inter_page_delay_s=0.0)
    assert len(client.calls) == 2  # second call returned empty → stop


@pytest.mark.asyncio
async def test_max_pages_caps_runaway() -> None:
    # 20 full pages of 100 — but max_pages=3 must cap.
    pages = [[_raw(f"p{i}_{j}") for j in range(100)] for i in range(20)]
    client = _FakeClient(pages)
    disc = MarketDiscovery(client)
    await disc.scan_active_markets(
        max_markets=10_000, max_pages=3, inter_page_delay_s=0.0
    )
    assert len(client.calls) == 3
