"""Place, cancel, replace via CLOB or DryRunExchange.

In paper mode: routes every order to DryRunExchange.
In live mode: uses py-clob-client SDK (guarded — wrapper returns rejected order if SDK missing).

Debit happens at placement (bug ledger): bankroll is debited when the order is placed,
NOT only on fill. This avoids over-committing capital.
"""

from __future__ import annotations

import uuid

from apex.config import get_settings
from apex.core.models import Decision, Order, OrderBook, OrderStatus, Side
from apex.core.state import BotState
from apex.execution.dry_run_exchange import DryRunExchange
from apex.execution.fill_tracker import FillTracker
from apex.utils.logger import get_logger

logger = get_logger(__name__)


class OrderManager:
    def __init__(
        self,
        state: BotState,
        dry_run_exchange: DryRunExchange,
        fill_tracker: FillTracker,
    ) -> None:
        self.state = state
        self.dry = dry_run_exchange
        self.fills = fill_tracker

    async def place_from_decision(
        self,
        decision: Decision,
        token_id: str,
        book: OrderBook | None = None,
    ) -> Order:
        """Convert an APPROVE / APPROVE_REDUCED decision into an Order and place it."""
        s = get_settings()
        sig = decision.signal
        side: Side = sig.side
        price = sig.forecast.market_price if sig.forecast else 0.5
        size_usd = decision.final_size_usd
        contracts = size_usd / max(0.001, price)

        order = Order(
            id=uuid.uuid4().hex,
            market_id=sig.market_id,
            token_id=token_id,
            side=side,
            price=price,
            size_usd=size_usd,
            contracts=contracts,
            status=OrderStatus.PENDING,
            strategy=sig.strategy,
            signal_id=f"{sig.strategy}:{sig.market_id}",
            dry_run=s.dry_run,
        )

        # Debit on placement (bug ledger)
        debited = await self.state.debit(size_usd, reason=f"place_order:{sig.strategy}")
        if not debited:
            order.status = OrderStatus.REJECTED
            logger.warning("order rejected: debit failed size=$%.2f", size_usd)
            return order

        if s.dry_run:
            self.fills.register_order(order)
            return await self.dry.place(order, book)

        # Live mode: py-clob-client SDK. If not installed, fail closed.
        try:
            from py_clob_client.client import ClobClient  # noqa: F401  # type: ignore
        except ImportError:
            logger.error("live mode requested but py_clob_client not installed — rejecting")
            order.status = OrderStatus.REJECTED
            # Refund the debit
            await self.state.credit(size_usd, reason="live_unavailable_refund")
            return order

        # Actual live placement would happen here with the SDK. Do NOT hallucinate methods
        # without verification. Mark as FAILED for now so the operator is aware.
        logger.error("live order placement requires SDK integration — not yet verified")
        order.status = OrderStatus.FAILED
        await self.state.credit(size_usd, reason="live_not_implemented_refund")
        return order

    async def cancel(self, order_id: str) -> bool:
        s = get_settings()
        if s.dry_run:
            return await self.dry.cancel(order_id)
        return False

    async def cancel_all(self) -> int:
        s = get_settings()
        if s.dry_run:
            return await self.dry.cancel_all()
        return 0
