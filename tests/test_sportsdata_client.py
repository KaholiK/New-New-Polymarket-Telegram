"""Tests for the SportsDataIO client."""

from __future__ import annotations

import httpx
import pytest

from apex.data.sportsdata_client import SportsDataClient, _TTLCache


def test_ttl_cache_set_get():
    c = _TTLCache()
    c.set("k", "v", ttl_seconds=60)
    assert c.get("k") == "v"


def test_ttl_cache_expires():
    import time
    c = _TTLCache()
    c.set("k", "v", ttl_seconds=0.01)
    time.sleep(0.02)
    assert c.get("k") is None


def test_ttl_cache_missing():
    c = _TTLCache()
    assert c.get("missing") is None


def test_disabled_without_key():
    client = SportsDataClient(api_key="")
    assert not client.enabled


@pytest.mark.asyncio
async def test_disabled_client_returns_empty():
    client = SportsDataClient(api_key="")
    assert await client.any_games_in_progress("NBA") is None
    assert await client.games_by_date("NBA", "2026-01-01") == []
    assert await client.player_season_stats("NBA", 2026) == []
    assert await client.team_season_stats("NBA", 2026) == []
    assert await client.injuries("NBA") == []
    assert await client.team_context("NBA", "Lakers") == {}


@pytest.mark.asyncio
async def test_invalid_sport_returns_empty():
    client = SportsDataClient(api_key="fake-key")
    assert await client.games_by_date("CRICKET", "2026-01-01") == []


@pytest.mark.asyncio
async def test_http_error_returns_empty(monkeypatch):
    # Build a client with a transport that always 500s, then confirm we swallow.
    from httpx import MockTransport, Response

    async def handler(request):
        return Response(500, text="boom")

    transport = MockTransport(handler)
    inner = httpx.AsyncClient(transport=transport)
    client = SportsDataClient(api_key="fake-key", client=inner)
    try:
        result = await client.games_by_date("NBA", "2026-01-01")
        assert result == []
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_caches_successful_response():
    from httpx import MockTransport, Response

    call_count = {"n": 0}

    async def handler(request):
        call_count["n"] += 1
        return Response(200, json=[{"GameID": 1}])

    transport = MockTransport(handler)
    inner = httpx.AsyncClient(transport=transport)
    client = SportsDataClient(api_key="fake-key", client=inner)
    try:
        a = await client.games_by_date("NBA", "2026-01-01")
        b = await client.games_by_date("NBA", "2026-01-01")
        assert a == b == [{"GameID": 1}]
        assert call_count["n"] == 1  # second call served from cache
    finally:
        await client.aclose()
