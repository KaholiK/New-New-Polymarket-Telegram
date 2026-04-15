"""Tests for slippage — correct dimensions (price_diff × contracts, NOT × USD)."""

from __future__ import annotations

import pytest

from apex.core.models import OrderBook, OrderBookLevel
from apex.execution.slippage import (
    post_trade_slippage,
    pre_trade_estimate,
    profit_gate_after_slippage,
)


def _book(asks: list[tuple[float, float]]) -> OrderBook:
    return OrderBook(
        token_id="t",
        asks=[OrderBookLevel(price=p, size=s) for p, s in asks],
    )


def test_pre_trade_estimate_fill_single_level():
    book = _book([(0.5, 100)])
    est = pre_trade_estimate(book, "BUY", 50)
    assert est.estimated_fill_price == 0.5
    assert est.filled_contracts == 50
    assert est.slippage_price == 0.0
    assert est.slippage_usd == 0.0


def test_slippage_scales_with_contracts_not_usd():
    """Regression: slippage_usd = price_diff × contracts. Doubling contracts doubles cost."""
    book = _book([(0.50, 100), (0.55, 100)])
    est_100 = pre_trade_estimate(book, "BUY", 100)  # fills 100 at 0.50 → no slippage
    est_150 = pre_trade_estimate(book, "BUY", 150)  # walks into 0.55 level
    assert est_100.slippage_usd == 0.0
    assert est_150.slippage_usd > 0.0
    # Price diff ≈ 0.0167, total fill 150 → slip_usd ≈ 2.5
    assert est_150.slippage_usd < 10.0  # small dollar cost, NOT $75 (= price_diff × 150 × 0.50 if incorrect)


def test_post_trade_slippage_positive_for_worse_fill():
    # BUY limit 0.50, filled at 0.52, 100 contracts → $2 slippage
    slip = post_trade_slippage(limit_price=0.50, avg_fill_price=0.52, contracts=100, side="BUY")
    assert slip == pytest.approx(2.0, abs=1e-6)


def test_post_trade_slippage_zero_better_fill():
    slip = post_trade_slippage(limit_price=0.50, avg_fill_price=0.48, contracts=100, side="BUY")
    assert slip == 0.0


def test_post_trade_slippage_sell():
    slip = post_trade_slippage(limit_price=0.50, avg_fill_price=0.48, contracts=100, side="SELL")
    assert slip == pytest.approx(2.0, abs=1e-6)


def test_profit_gate_passes():
    assert profit_gate_after_slippage(estimated_ev=2.0, slippage_usd=0.5, min_profit=1.0)


def test_profit_gate_fails():
    assert not profit_gate_after_slippage(estimated_ev=1.2, slippage_usd=0.5, min_profit=1.0)


def test_profit_gate_exact_threshold():
    assert profit_gate_after_slippage(estimated_ev=1.5, slippage_usd=0.5, min_profit=1.0)
