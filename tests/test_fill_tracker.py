"""Tests for fill tracker — partial fills, blended price."""

from __future__ import annotations

import pytest

from apex.core.models import Fill, Order, Side
from apex.execution.fill_tracker import FillAccumulator, FillTracker


def _order(oid: str = "o1", contracts: float = 100) -> Order:
    return Order(
        id=oid,
        market_id="m1",
        token_id="t1",
        side=Side.YES,
        price=0.5,
        size_usd=contracts * 0.5,
        contracts=contracts,
    )


def test_empty_accumulator():
    acc = FillAccumulator(order_id="o")
    assert acc.total_contracts == 0
    assert acc.avg_price == 0.0


def test_single_fill_blended():
    acc = FillAccumulator(order_id="o")
    acc.add(Fill(order_id="o", price=0.5, contracts=10, usd=5.0))
    assert acc.total_contracts == 10
    assert acc.avg_price == 0.5


def test_multi_fill_blended_price():
    acc = FillAccumulator(order_id="o")
    acc.add(Fill(order_id="o", price=0.50, contracts=10, usd=5.0))
    acc.add(Fill(order_id="o", price=0.52, contracts=10, usd=5.2))
    # Blended: 10.2 / 20 = 0.51
    assert acc.avg_price == pytest.approx(0.51, abs=1e-6)


def test_tracker_register_and_record():
    t = FillTracker()
    t.register_order(_order())
    acc = t.record_fill(Fill(order_id="o1", price=0.5, contracts=5, usd=2.5))
    assert acc.total_contracts == 5


def test_tracker_auto_creates_accumulator():
    t = FillTracker()
    acc = t.record_fill(Fill(order_id="unknown", price=0.5, contracts=5, usd=2.5))
    assert acc.total_contracts == 5


def test_tracker_get_none():
    t = FillTracker()
    assert t.get("o_unknown") is None


def test_tracker_all_accumulators():
    t = FillTracker()
    t.register_order(_order())
    accs = t.all_accumulators()
    assert len(accs) == 1


def test_avg_price_formula_dimensional():
    """Regression: avg = total_usd / total_contracts. Never size_usd / anything."""
    acc = FillAccumulator(order_id="o")
    acc.add(Fill(order_id="o", price=0.30, contracts=100, usd=30.0))
    acc.add(Fill(order_id="o", price=0.70, contracts=100, usd=70.0))
    # Mean price = 0.50. Using size_usd / total_contracts = 100/200 = 0.50
    # same value coincidentally but the formula still must be total_usd/contracts.
    assert 0.30 < acc.avg_price < 0.70
    assert acc.avg_price == pytest.approx(0.50, abs=1e-6)
