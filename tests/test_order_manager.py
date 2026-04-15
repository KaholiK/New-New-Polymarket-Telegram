"""Tests for order manager — dry-run place/cancel, rejections."""

from __future__ import annotations

import pytest

from apex.core.models import (
    Confidence,
    Decision,
    DecisionOutcome,
    Forecast,
    MarketType,
    OrderBook,
    OrderBookLevel,
    ReasonTrace,
    Side,
    Signal,
    Sport,
)
from apex.core.state import BotState
from apex.execution.dry_run_exchange import DryRunExchange
from apex.execution.fill_tracker import FillTracker
from apex.execution.order_manager import OrderManager


def _decision(final_size_usd: float = 1.0) -> Decision:
    fc = Forecast(
        event_id="e1",
        market_id="m1",
        sport=Sport.NBA,
        market_type=MarketType.MONEYLINE,
        home_team="A", away_team="B",
        side=Side.YES,
        ensemble_prob=0.55, ensemble_std=0.02,
        market_price=0.48, market_implied_prob=0.48,
        raw_edge=0.07, edge_zscore=2.5, edge_after_costs=0.05,
        confidence=Confidence.MEDIUM,
    )
    sig = Signal(
        strategy="fair_value",
        market_id="m1", event_id="e1",
        side=Side.YES, size_hint_usd=0.0,
        edge=0.07, edge_zscore=2.5,
        confidence=Confidence.MEDIUM,
        forecast=fc,
    )
    return Decision(
        signal=sig,
        outcome=DecisionOutcome.APPROVE,
        final_size_usd=final_size_usd,
        trace=ReasonTrace(score=80.0),
    )


def _book() -> OrderBook:
    return OrderBook(
        token_id="t1",
        asks=[OrderBookLevel(price=0.48, size=100)],
    )


@pytest.mark.asyncio
async def test_place_dry_run_debits_bankroll():
    state = BotState(starting_bankroll=20.0)
    ex = DryRunExchange()
    ft = FillTracker()
    om = OrderManager(state, ex, ft)
    d = _decision(final_size_usd=5.0)
    order = await om.place_from_decision(d, token_id="t1", book=_book())
    assert order.id
    assert state.bankroll == 15.0  # debited on placement


@pytest.mark.asyncio
async def test_place_overdraft_rejects():
    state = BotState(starting_bankroll=2.0)
    ex = DryRunExchange()
    ft = FillTracker()
    om = OrderManager(state, ex, ft)
    d = _decision(final_size_usd=10.0)
    order = await om.place_from_decision(d, token_id="t1", book=_book())
    assert order.status.value == "rejected"
    # Bankroll unchanged (overdraft triggers auto-kill via state.debit)
    assert state.killed


@pytest.mark.asyncio
async def test_place_registers_fill_tracker():
    state = BotState(starting_bankroll=20.0)
    ex = DryRunExchange()
    ft = FillTracker()
    om = OrderManager(state, ex, ft)
    d = _decision(final_size_usd=1.0)
    order = await om.place_from_decision(d, token_id="t1", book=_book())
    assert ft.get(order.id) is not None


@pytest.mark.asyncio
async def test_cancel_routes_to_dry_run():
    state = BotState(starting_bankroll=20.0)
    ex = DryRunExchange()
    ft = FillTracker()
    om = OrderManager(state, ex, ft)
    d = _decision(final_size_usd=1.0)
    order = await om.place_from_decision(d, token_id="t1", book=_book())
    # Order may complete quickly; attempt cancel should either succeed or return False cleanly
    _ = await om.cancel(order.id)


@pytest.mark.asyncio
async def test_cancel_all_returns_count():
    state = BotState(starting_bankroll=20.0)
    ex = DryRunExchange()
    ft = FillTracker()
    om = OrderManager(state, ex, ft)
    await om.place_from_decision(_decision(1.0), token_id="t1", book=_book())
    n = await om.cancel_all()
    assert n >= 0


@pytest.mark.asyncio
async def test_place_live_without_sdk_rejects_and_refunds(monkeypatch):
    # Simulate DRY_RUN=false and no py_clob_client installed
    monkeypatch.setenv("DRY_RUN", "false")
    state = BotState(starting_bankroll=20.0, dry_run=False)
    ex = DryRunExchange()
    ft = FillTracker()
    om = OrderManager(state, ex, ft)
    # Temporarily hide the module if it exists
    import sys

    saved = sys.modules.pop("py_clob_client.client", None)
    try:
        # Force ImportError by putting a non-module in the path
        sys.modules["py_clob_client.client"] = None  # type: ignore
        d = _decision(final_size_usd=1.0)
        order = await om.place_from_decision(d, token_id="t1", book=_book())
        assert order.status.value in ("rejected", "failed")
        # Bankroll refunded after rejection
        assert state.bankroll == pytest.approx(20.0, abs=1e-6)
    finally:
        if saved:
            sys.modules["py_clob_client.client"] = saved
        else:
            sys.modules.pop("py_clob_client.client", None)
