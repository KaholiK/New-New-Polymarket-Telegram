"""Smart retry policy for the Odds API: no retry on 401/403, retry on 429/5xx."""

from __future__ import annotations

import httpx
import pytest

from apex.data.odds_ingestor import OddsIngestor


class _FakeTransport(httpx.AsyncBaseTransport):
    """Scripted transport — each call returns the next item from ``responses``."""

    def __init__(self, responses: list[httpx.Response]) -> None:
        self.responses = list(responses)
        self.requests: list[httpx.Request] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if not self.responses:
            raise RuntimeError("no more scripted responses")
        resp = self.responses.pop(0)
        resp.request = request
        return resp


def _client(transport: _FakeTransport) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=transport)


@pytest.mark.asyncio
async def test_401_does_not_retry_and_marks_degraded() -> None:
    transport = _FakeTransport([
        httpx.Response(401, text='{"message":"Unauthorized"}'),
    ])
    ingestor = OddsIngestor("bad_key", client=_client(transport))
    snaps = await ingestor.fetch_odds("NBA")
    assert snaps == []
    # Exactly one request — no retry on auth failure.
    assert len(transport.requests) == 1
    assert ingestor.auth_failed is True
    assert ingestor.degraded is True
    assert "401" in ingestor.last_error
    await ingestor.aclose()


@pytest.mark.asyncio
async def test_degraded_short_circuits_remaining_sports() -> None:
    # Only one scripted 401 — if the ingestor did NOT short-circuit we'd get
    # an error on the second call.
    transport = _FakeTransport([httpx.Response(401, text="no")])
    ingestor = OddsIngestor("bad_key", client=_client(transport))

    first = await ingestor.fetch_odds("NBA")
    second = await ingestor.fetch_odds("NFL")
    assert first == [] and second == []
    # Only one real HTTP call — the second request was short-circuited.
    assert len(transport.requests) == 1
    await ingestor.aclose()


@pytest.mark.asyncio
async def test_429_retries_then_succeeds() -> None:
    transport = _FakeTransport([
        httpx.Response(429, text="slow down"),
        httpx.Response(200, json=[]),
    ])
    ingestor = OddsIngestor(
        "key", client=_client(transport),
        retry_attempts=3, retry_base_delay=0.0, retry_max_delay=0.0,
    )
    snaps = await ingestor.fetch_odds("NBA")
    assert snaps == []
    # 429 then 200 — both requests went out.
    assert len(transport.requests) == 2
    assert ingestor.auth_failed is False
    await ingestor.aclose()


@pytest.mark.asyncio
async def test_5xx_retries() -> None:
    transport = _FakeTransport([
        httpx.Response(503, text="bad"),
        httpx.Response(502, text="bad"),
        httpx.Response(200, json=[]),
    ])
    ingestor = OddsIngestor(
        "key", client=_client(transport),
        retry_attempts=3, retry_base_delay=0.0, retry_max_delay=0.0,
    )
    snaps = await ingestor.fetch_odds("NBA")
    assert snaps == []
    assert len(transport.requests) == 3
    await ingestor.aclose()


@pytest.mark.asyncio
async def test_validate_key_ok() -> None:
    transport = _FakeTransport([
        httpx.Response(200, json=[{"key": "basketball_nba"}, {"key": "americanfootball_nfl"}]),
    ])
    ingestor = OddsIngestor("key", client=_client(transport))
    ok, reason = await ingestor.validate_key()
    assert ok is True
    assert reason == ""
    await ingestor.aclose()


@pytest.mark.asyncio
async def test_validate_key_401() -> None:
    transport = _FakeTransport([httpx.Response(401, text="nope")])
    ingestor = OddsIngestor("bad", client=_client(transport))
    ok, reason = await ingestor.validate_key()
    assert ok is False
    assert "401" in reason
    await ingestor.aclose()


@pytest.mark.asyncio
async def test_validate_key_missing() -> None:
    ingestor = OddsIngestor("", client=httpx.AsyncClient())
    ok, reason = await ingestor.validate_key()
    assert ok is False
    assert "ODDS_API_KEY" in reason
    await ingestor.aclose()


@pytest.mark.asyncio
async def test_reset_cycle_preserves_sticky_auth_fail() -> None:
    """reset_cycle keeps auth_failed sticky so we don't flood the API."""
    transport = _FakeTransport([httpx.Response(401, text="no")])
    ingestor = OddsIngestor("bad", client=_client(transport))
    await ingestor.fetch_odds("NBA")
    assert ingestor.auth_failed is True
    ingestor.reset_cycle()
    assert ingestor.degraded is True  # still sticky because auth still failed
    await ingestor.aclose()
