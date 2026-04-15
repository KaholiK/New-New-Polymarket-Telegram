"""Tests for market discovery, including the clobTokenIds JSON-string edge case."""

from __future__ import annotations

from apex.market.discovery import (
    _parse_clob_token_ids,
    _parse_outcome_prices,
    market_from_gamma,
)


class TestParseClobTokenIds:
    def test_json_encoded_string(self):
        # The most common live format from Gamma
        a, b = _parse_clob_token_ids('["tok_yes", "tok_no"]')
        assert a == "tok_yes"
        assert b == "tok_no"

    def test_native_list(self):
        a, b = _parse_clob_token_ids(["tok_yes", "tok_no"])
        assert a == "tok_yes"
        assert b == "tok_no"

    def test_none(self):
        a, b = _parse_clob_token_ids(None)
        assert a == ""
        assert b == ""

    def test_empty_string(self):
        a, b = _parse_clob_token_ids("")
        assert a == ""
        assert b == ""

    def test_malformed_string(self):
        a, b = _parse_clob_token_ids("not valid json[")
        assert a == ""
        assert b == ""

    def test_single_token(self):
        a, b = _parse_clob_token_ids('["only_one"]')
        assert a == "only_one"
        assert b == ""

    def test_empty_list(self):
        a, b = _parse_clob_token_ids([])
        assert a == ""
        assert b == ""

    def test_json_encoded_numeric_tokens(self):
        # Some Polymarket tokens are long numeric strings
        a, b = _parse_clob_token_ids('["11111111", "22222222"]')
        assert a == "11111111"
        assert b == "22222222"


class TestParseOutcomePrices:
    def test_json_string(self):
        a, b = _parse_outcome_prices('["0.48", "0.52"]')
        assert abs(a - 0.48) < 1e-6
        assert abs(b - 0.52) < 1e-6

    def test_list_of_floats(self):
        a, b = _parse_outcome_prices([0.48, 0.52])
        assert a == 0.48

    def test_none(self):
        a, b = _parse_outcome_prices(None)
        assert a == 0.5
        assert b == 0.5

    def test_malformed(self):
        a, b = _parse_outcome_prices("bad[")
        assert a == 0.5


class TestMarketFromGamma:
    def test_complete_market(self):
        raw = {
            "conditionId": "0xabc",
            "question": "Will Lakers beat Celtics?",
            "clobTokenIds": '["tok1", "tok2"]',
            "outcomePrices": '["0.48", "0.52"]',
            "volume": 50000,
            "liquidity": 2000,
            "endDate": "2026-04-15T23:00:00Z",
            "acceptingOrders": True,
            "tags": ["NBA"],
        }
        m = market_from_gamma(raw)
        assert m is not None
        assert m.condition_id == "0xabc"
        assert m.yes_token_id == "tok1"
        assert m.yes_price == 0.48
        assert m.accepting_orders is True

    def test_missing_tokens_returns_none(self):
        raw = {"conditionId": "x", "question": "Lakers vs Celtics"}
        m = market_from_gamma(raw)
        assert m is None

    def test_none_tags_handled(self):
        # Gamma's tags field is often None on live data — must not crash
        raw = {
            "conditionId": "0xdef",
            "question": "NBA Lakers vs Celtics moneyline",
            "clobTokenIds": '["tok1", "tok2"]',
            "tags": None,
        }
        m = market_from_gamma(raw)
        assert m is not None
        assert m.tags == []

    def test_non_dict_input(self):
        assert market_from_gamma("not a dict") is None  # type: ignore
        assert market_from_gamma(None) is None  # type: ignore

    def test_missing_condition_id(self):
        raw = {"question": "Foo", "clobTokenIds": '["a","b"]'}
        assert market_from_gamma(raw) is None
