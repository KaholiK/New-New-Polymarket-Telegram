"""Tests for the Claude analyzer.

We don't hit the real Anthropic API — we inject a fake `_client` with a stubbed
`messages.create` coroutine so we can exercise prompt assembly, response parsing,
cost tracking, and cap enforcement deterministically.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import pytest

from apex.core.models import Market, MarketType, Sport
from apex.quant.calibration.cost_tracker import CostTracker
from apex.quant.models.claude_analyzer import ClaudeAnalyzer, _parse_json


def _market() -> Market:
    return Market(
        condition_id="cond_x",
        question="Will the Lakers beat the Celtics on Nov 1?",
        sport=Sport.NBA,
        market_type=MarketType.MONEYLINE,
        home_team="Los Angeles Lakers",
        away_team="Boston Celtics",
        yes_token_id="y",
        no_token_id="n",
        yes_price=0.45,
        no_price=0.55,
        volume=125000,
        liquidity=8000,
        end_date=datetime.now(UTC),
    )


@dataclass
class _FakeUsage:
    input_tokens: int
    output_tokens: int


@dataclass
class _FakeContentBlock:
    type: str
    text: str


@dataclass
class _FakeResponse:
    content: list
    usage: _FakeUsage


class _FakeMessages:
    def __init__(self, payload: str, in_tok=700, out_tok=120):
        self.payload = payload
        self.in_tok = in_tok
        self.out_tok = out_tok
        self.last_kwargs: dict | None = None

    async def create(self, **kwargs):
        self.last_kwargs = kwargs
        return _FakeResponse(
            content=[_FakeContentBlock(type="text", text=self.payload)],
            usage=_FakeUsage(input_tokens=self.in_tok, output_tokens=self.out_tok),
        )


class _FakeClient:
    def __init__(self, messages):
        self.messages = messages


class _FailingMessages:
    async def create(self, **kwargs):
        raise RuntimeError("simulated API outage")


# ---------- _parse_json ----------


def test_parse_json_pure_object():
    j = _parse_json('{"a": 1}')
    assert j == {"a": 1}


def test_parse_json_with_surrounding_text():
    j = _parse_json('here is the answer {"a": 2, "b": 3} done.')
    assert j == {"a": 2, "b": 3}


def test_parse_json_empty():
    assert _parse_json("") is None


def test_parse_json_bad_payload():
    assert _parse_json("not json and no braces") is None


# ---------- analyzer behavior ----------


@pytest.mark.asyncio
async def test_disabled_without_key():
    tracker = CostTracker(db=None, daily_cap_usd=1.0)
    a = ClaudeAnalyzer(api_key="", model="claude-sonnet-4-20250514", cost_tracker=tracker)
    assert not a.enabled
    est = await a.analyze(_market(), ensemble_prob_before=0.5, basic_factors=[])
    assert est is None


@pytest.mark.asyncio
async def test_parses_valid_response():
    tracker = CostTracker(db=None, daily_cap_usd=1.0)
    a = ClaudeAnalyzer(api_key="dummy", model="claude-sonnet-4-20250514", cost_tracker=tracker)
    # Swap in fake client
    payload = (
        '{"home_win_probability": 0.58, "confidence": "medium", '
        '"uncertainty": 0.04, "key_factors": ["rest advantage","starter back"], '
        '"reasoning": "Lakers well-rested, starter returning."}'
    )
    a._client = _FakeClient(_FakeMessages(payload))
    est = await a.analyze(_market(), ensemble_prob_before=0.5, basic_factors=["elo+15"])
    assert est is not None
    assert est.model_name == "claude"
    assert abs(est.probability - 0.58) < 1e-6
    assert est.confidence == pytest.approx(0.65, abs=1e-6)
    assert any("rest" in f for f in est.factors)
    # Cost was tracked
    assert tracker.today_cost() > 0


@pytest.mark.asyncio
async def test_api_error_returns_none_and_records_failure():
    tracker = CostTracker(db=None, daily_cap_usd=1.0)
    a = ClaudeAnalyzer(api_key="dummy", model="claude-sonnet-4-20250514", cost_tracker=tracker)
    a._client = _FakeClient(_FailingMessages())
    est = await a.analyze(_market(), ensemble_prob_before=0.5, basic_factors=[])
    assert est is None


@pytest.mark.asyncio
async def test_cap_blocks_call():
    # Cap so small that even the pre-call estimate exceeds it.
    tracker = CostTracker(db=None, daily_cap_usd=0.000001)
    a = ClaudeAnalyzer(api_key="dummy", model="claude-sonnet-4-20250514", cost_tracker=tracker)
    payload = '{"home_win_probability": 0.6, "confidence": "high"}'
    fake = _FakeMessages(payload)
    a._client = _FakeClient(fake)
    est = await a.analyze(_market(), ensemble_prob_before=0.5, basic_factors=[])
    assert est is None
    # The API should not have been invoked (no kwargs captured).
    assert fake.last_kwargs is None


@pytest.mark.asyncio
async def test_prompt_contains_market_and_price():
    tracker = CostTracker(db=None, daily_cap_usd=1.0)
    a = ClaudeAnalyzer(api_key="dummy", model="claude-sonnet-4-20250514", cost_tracker=tracker)
    payload = '{"home_win_probability": 0.5, "confidence": "low"}'
    fake = _FakeMessages(payload)
    a._client = _FakeClient(fake)
    m = _market()
    await a.analyze(m, ensemble_prob_before=0.5, basic_factors=["elo+15"])
    assert fake.last_kwargs is not None
    user_content = fake.last_kwargs["messages"][0]["content"]
    assert m.question in user_content
    assert "0.45" in user_content  # Polymarket YES price appears in context
    # System prompt uses prompt caching
    sys_block = fake.last_kwargs["system"][0]
    assert sys_block["cache_control"]["type"] == "ephemeral"


@pytest.mark.asyncio
async def test_malformed_response_returns_none():
    tracker = CostTracker(db=None, daily_cap_usd=1.0)
    a = ClaudeAnalyzer(api_key="dummy", model="claude-sonnet-4-20250514", cost_tracker=tracker)
    a._client = _FakeClient(_FakeMessages("sorry I can't help"))
    est = await a.analyze(_market(), ensemble_prob_before=0.5, basic_factors=[])
    assert est is None
