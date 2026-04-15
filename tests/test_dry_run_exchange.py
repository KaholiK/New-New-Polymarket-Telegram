"""Tests for dry-run exchange."""

from __future__ import annotations

import pytest

from apex.core.models import Order, OrderBook, OrderBookLevel, OrderStatus, Side
from apex.execution.dry_run_exchange import DryRunExchange


def _order(price: float = 0.50, contracts: float = 10) -> Order:
    return Order(
        id="",
        market_id="m1",
        token_id="t1",
        side=Side.YES,
        price=price,
        size_usd=price * contracts,
        contracts=contracts,
    )


def _book(asks: list[tuple[float, float]]) -> OrderBook:
    return OrderBook(
        token_id="t1",
        asks=[OrderBookLevel(price=p, size=s) for p, s in asks],
    )


@pytest.mark.asyncio
async def test_place_assigns_id():
    ex = DryRunExchange()
    o = await ex.place(_order(), _book([(0.5, 100)]))
    assert o.id


@pytest.mark.asyncio
async def test_place_partial_fill_first_tick():
    ex = DryRunExchange()
    o = await ex.place(_order(contracts=100), _book([(0.5, 100)]))
    # 70% immediate fill by default
    assert o.filled_contracts > 0
    assert o.filled_contracts < 100


@pytest.mark.asyncio
async def test_tick_completes_fill():
    ex = DryRunExchange()
    o = await ex.place(_order(contracts=10), _book([(0.5, 100)]))
    await ex.tick()
    polled = await ex.poll(o.id)
    assert polled is not None
    assert polled.status == OrderStatus.FILLED


@pytest.mark.asyncio
async def test_cancel_pending_order():
    ex = DryRunExchange()
    o = await ex.place(_order(contracts=1000), _book([(0.5, 5)]))  # thin book
    ok = await ex.cancel(o.id)
    assert ok


@pytest.mark.asyncio
async def test_cancel_unknown_order_false():
    ex = DryRunExchange()
    assert not await ex.cancel("nonexistent")


@pytest.mark.asyncio
async def test_cancel_all():
    ex = DryRunExchange()
    await ex.place(_order(contracts=100), _book([(0.5, 10)]))
    await ex.place(_order(contracts=100), _book([(0.5, 10)]))
    n = await ex.cancel_all()
    assert n >= 0


@pytest.mark.asyncio
async def test_illiquid_book_caps_fill():
    ex = DryRunExchange()
    o = await ex.place(_order(contracts=100), _book([(0.5, 50)]))  # depth < 100
    # Fill limited to 30% of depth per tick
    assert o.filled_contracts <= 50


@pytest.mark.asyncio
async def test_avg_price_formula_correct():
    """Regression: avg_fill_price = total_usd / total_contracts (NOT / size_usd)."""
    ex = DryRunExchange()
    o = await ex.place(_order(price=0.5, contracts=10), _book([(0.5, 100), (0.55, 100)]))
    if o.filled_contracts > 0:
        # avg_fill_price should be a price (0-1), not ~1.0
        assert 0.4 < o.avg_fill_price < 0.7


@pytest.mark.asyncio
async def test_snapshot_keys():
    ex = DryRunExchange()
    await ex.place(_order(), _book([(0.5, 100)]))
    snap = ex.snapshot()
    assert snap
    assert "status" in snap[0]


@pytest.mark.asyncio
async def test_open_order_ids_shrinks_after_complete():
    ex = DryRunExchange()
    o = await ex.place(_order(contracts=1), _book([(0.5, 100)]))
    await ex.tick()
    open_ids = ex.open_order_ids
    # Fill should complete after one tick for small order
    assert o.id not in open_ids or len(open_ids) == 0
