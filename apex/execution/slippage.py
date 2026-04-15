"""Pre-trade estimate from book depth + post-trade analysis.

CRITICAL: slippage dollar cost = price_diff × contracts. NEVER × size_usd.
"""

from __future__ import annotations

from dataclasses import dataclass

from apex.core.models import OrderBook
from apex.market.orderbook import estimate_fill_price, slippage_estimate


@dataclass
class PreTradeEstimate:
    estimated_fill_price: float
    filled_contracts: float
    slippage_price: float  # per-contract price difference vs best quote
    slippage_usd: float  # price_diff × contracts (NOT × usd)


def pre_trade_estimate(book: OrderBook, side: str, size_contracts: float) -> PreTradeEstimate:
    avg, filled = estimate_fill_price(book, side, size_contracts)
    slip_price = slippage_estimate(book, side, size_contracts)
    # Dimensional invariant: slippage cost = price_diff (per share) * total contracts.
    slip_usd = slip_price * filled
    return PreTradeEstimate(
        estimated_fill_price=avg,
        filled_contracts=filled,
        slippage_price=slip_price,
        slippage_usd=slip_usd,
    )


def post_trade_slippage(limit_price: float, avg_fill_price: float, contracts: float, side: str) -> float:
    """Realized slippage cost (USD) post-fill. Positive = paid more than expected."""
    if side.upper() == "BUY":
        diff = max(0.0, avg_fill_price - limit_price)
    else:
        diff = max(0.0, limit_price - avg_fill_price)
    return diff * max(0.0, contracts)


def profit_gate_after_slippage(
    estimated_ev: float,
    slippage_usd: float,
    min_profit: float = 1.0,
) -> bool:
    """True if expected profit net of slippage meets the floor."""
    return (estimated_ev - slippage_usd) >= min_profit
