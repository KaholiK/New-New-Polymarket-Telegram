"""Tests for orderbook parsing, fill estimation, slippage dimension check."""

from __future__ import annotations

import pytest

from apex.core.models import OrderBook, OrderBookLevel
from apex.market.orderbook import (
    estimate_fill_price,
    parse_book,
    slippage_estimate,
    total_depth_at_price,
)


def _book(bids: list[tuple[float, float]], asks: list[tuple[float, float]]) -> OrderBook:
    return OrderBook(
        token_id="t1",
        bids=[OrderBookLevel(price=p, size=s) for p, s in bids],
        asks=[OrderBookLevel(price=p, size=s) for p, s in asks],
    )


def test_parse_book_basic():
    raw = {
        "bids": [{"price": "0.47", "size": "100"}, {"price": "0.46", "size": "200"}],
        "asks": [{"price": "0.49", "size": "100"}, {"price": "0.50", "size": "200"}],
        "token_id": "tok",
    }
    ob = parse_book(raw)
    assert ob.best_bid == 0.47
    assert ob.best_ask == 0.49
    assert abs(ob.spread - 0.02) < 1e-6


def test_parse_book_empty():
    ob = parse_book(None)
    assert ob.bids == []
    assert ob.asks == []


def test_parse_book_bad_levels_skipped():
    raw = {"bids": [{"price": "bad", "size": "10"}], "asks": []}
    ob = parse_book(raw)
    assert ob.bids == []


def test_fill_price_single_level():
    ob = _book([], [(0.50, 100)])
    avg, filled = estimate_fill_price(ob, "BUY", 50)
    assert avg == 0.50
    assert filled == 50


def test_fill_price_walks_levels():
    ob = _book([], [(0.50, 100), (0.52, 100)])
    avg, filled = estimate_fill_price(ob, "BUY", 150)
    # 100 at 0.50 + 50 at 0.52 = 50 + 26 = 76 / 150 ≈ 0.5067
    assert filled == 150
    assert avg == pytest.approx(76.0 / 150.0, abs=1e-6)


def test_fill_price_partial_depth():
    ob = _book([], [(0.50, 100)])
    avg, filled = estimate_fill_price(ob, "BUY", 200)
    assert filled == 100  # only 100 available


def test_fill_price_zero_size():
    ob = _book([], [(0.50, 100)])
    avg, filled = estimate_fill_price(ob, "BUY", 0)
    assert filled == 0


def test_fill_price_empty_book():
    ob = _book([], [])
    avg, filled = estimate_fill_price(ob, "BUY", 100)
    assert filled == 0


def test_fill_price_sell_side():
    ob = _book([(0.50, 100)], [])
    avg, filled = estimate_fill_price(ob, "SELL", 50)
    assert avg == 0.50
    assert filled == 50


def test_total_depth_at_price():
    ob = _book([], [(0.50, 100), (0.52, 100), (0.55, 200)])
    assert total_depth_at_price(ob, "BUY", price_cap=0.52) == 200


def test_slippage_returns_price_difference_not_usd():
    """Regression: slippage must return a PRICE difference, not a USD amount.

    If the formula were 'price_diff * usd' (the prior bug), the returned value
    would scale with trade size in USD. This test checks the value stays a tight
    small price number.
    """
    ob = _book([], [(0.50, 100), (0.55, 100)])
    # Request 150 contracts → avg = (100*0.50 + 50*0.55)/150 = 0.5167
    # reference = best_ask = 0.50. Slippage = 0.0167
    sl = slippage_estimate(ob, "BUY", 150)
    assert 0 < sl < 0.05  # small price number, NOT $75 (which is 0.5*150)
    assert sl == pytest.approx(0.01667, abs=1e-3)


def test_slippage_zero_when_first_level_suffices():
    ob = _book([], [(0.50, 100)])
    sl = slippage_estimate(ob, "BUY", 50)
    assert sl == 0.0


def test_slippage_empty_book():
    ob = _book([], [])
    assert slippage_estimate(ob, "BUY", 10) == 0.0


def test_fill_price_dimensional_invariant():
    """Fill price computed as total_usd / total_contracts, never / size_usd.

    If fill price were computed as total_cost / size_usd, it would return ~1.0 always,
    which was the prior bug. This test confirms the correct formula produces a value
    strictly less than the highest level price and strictly greater than the lowest.
    """
    ob = _book([], [(0.30, 100), (0.70, 100)])
    avg, filled = estimate_fill_price(ob, "BUY", 200)
    assert filled == 200
    assert 0.30 < avg < 0.70
    assert avg == pytest.approx(0.50, abs=1e-6)
