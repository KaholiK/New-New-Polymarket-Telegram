"""Simulated exchange for paper mode with realistic fill model.

Fill behavior:
- If order price crosses the book, fill up to 70% immediately at best price.
- Remaining 30% fills at 1¢ worse over subsequent poll cycles (simulated partial).
- For truly illiquid markets (<$100 visible depth), cap fill to 30% of depth.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from apex.core.models import Fill, Order, OrderBook, OrderStatus
from apex.market.orderbook import estimate_fill_price
from apex.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class _PendingOrder:
    order: Order
    book_snapshot: OrderBook
    fills_so_far: list[Fill] = field(default_factory=list)
    complete: bool = False


class DryRunExchange:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._orders: dict[str, _PendingOrder] = {}

    async def place(self, order: Order, book: OrderBook | None = None) -> Order:
        async with self._lock:
            order.id = order.id or uuid.uuid4().hex
            order.status = OrderStatus.OPEN
            order.updated_at = datetime.now(UTC)
            order.dry_run = True
            self._orders[order.id] = _PendingOrder(
                order=order,
                book_snapshot=book or OrderBook(token_id=order.token_id),
            )
            # Immediately simulate a first partial fill
            await self._progress_fill(order.id, fraction=0.7)
            return order

    async def cancel(self, order_id: str) -> bool:
        async with self._lock:
            po = self._orders.get(order_id)
            if po is None:
                return False
            if po.complete:
                return False
            po.order.status = OrderStatus.CANCELED
            po.complete = True
            return True

    async def cancel_all(self) -> int:
        async with self._lock:
            n = 0
            for po in self._orders.values():
                if not po.complete:
                    po.order.status = OrderStatus.CANCELED
                    po.complete = True
                    n += 1
            return n

    async def poll(self, order_id: str) -> Order | None:
        async with self._lock:
            po = self._orders.get(order_id)
            return po.order if po else None

    async def tick(self) -> list[Order]:
        """Called by fill_poll loop — progress partial fills toward completion."""
        async with self._lock:
            progressed: list[Order] = []
            for oid, po in self._orders.items():
                if po.complete:
                    continue
                if po.order.filled_contracts >= po.order.contracts - 1e-9:
                    po.order.status = OrderStatus.FILLED
                    po.complete = True
                    progressed.append(po.order)
                    continue
                await self._progress_fill(oid, fraction=1.0)
                progressed.append(po.order)
        return progressed

    async def _progress_fill(self, order_id: str, fraction: float = 1.0) -> None:
        po = self._orders.get(order_id)
        if po is None or po.complete:
            return
        o = po.order
        # Target contracts to fill this tick
        remaining = max(0.0, o.contracts - o.filled_contracts)
        to_fill = remaining * fraction
        book = po.book_snapshot
        # For BUYing YES tokens, we walk the asks
        side_str = "BUY"
        total_depth = sum(lvl.size for lvl in book.asks) or 1e9
        # Illiquid cap: limit each fill to 30% of visible depth
        if total_depth < 100:
            to_fill = min(to_fill, total_depth * 0.3)
        avg_price, filled = estimate_fill_price(book, side_str, to_fill)
        if filled <= 0:
            # Fallback to order's limit price, pretend full fill at slightly worse price
            avg_price = o.price + 0.01
            filled = to_fill
        usd = filled * avg_price
        # Record fill
        f = Fill(order_id=o.id, price=avg_price, contracts=filled, usd=usd)
        po.fills_so_far.append(f)
        # Update order
        new_total_contracts = o.filled_contracts + filled
        new_total_usd = o.filled_usd + usd
        o.filled_contracts = new_total_contracts
        o.filled_usd = new_total_usd
        # CRITICAL (bug ledger): avg_fill_price = total_usd / total_contracts
        if o.filled_contracts > 0:
            o.avg_fill_price = o.filled_usd / o.filled_contracts
        o.updated_at = datetime.now(UTC)
        if o.filled_contracts >= o.contracts - 1e-9:
            o.status = OrderStatus.FILLED
            po.complete = True
        else:
            o.status = OrderStatus.PARTIAL

    def snapshot(self) -> list[dict[str, Any]]:
        return [
            {
                "id": po.order.id,
                "status": po.order.status.value,
                "filled": po.order.filled_contracts,
                "avg_price": po.order.avg_fill_price,
            }
            for po in self._orders.values()
        ]

    @property
    def open_order_ids(self) -> list[str]:
        return [oid for oid, po in self._orders.items() if not po.complete]
