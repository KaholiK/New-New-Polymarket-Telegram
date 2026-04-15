"""Parse CLOB order books, estimate fill price from depth."""

from __future__ import annotations

from typing import Any

from apex.core.models import OrderBook, OrderBookLevel


def parse_book(raw: dict[str, Any] | None, token_id: str = "") -> OrderBook:
    """Parse a Polymarket CLOB /book response into our OrderBook model.

    Gamma returns bids/asks as lists of {price, size} dicts (strings or numbers).
    Bids sorted desc by price, asks asc by price.
    """
    if not raw:
        return OrderBook(token_id=token_id)

    def to_levels(side: Any) -> list[OrderBookLevel]:
        if not isinstance(side, list):
            return []
        lvls: list[OrderBookLevel] = []
        for entry in side:
            if not isinstance(entry, dict):
                continue
            try:
                p = float(entry.get("price") or entry.get("p") or 0)
                s = float(entry.get("size") or entry.get("s") or 0)
            except (ValueError, TypeError):
                continue
            if p > 0 and s > 0:
                lvls.append(OrderBookLevel(price=p, size=s))
        return lvls

    bids = to_levels(raw.get("bids"))
    asks = to_levels(raw.get("asks"))
    bids.sort(key=lambda x: x.price, reverse=True)
    asks.sort(key=lambda x: x.price)

    tok = str(raw.get("token_id") or raw.get("asset_id") or token_id)
    return OrderBook(token_id=tok, bids=bids, asks=asks)


def estimate_fill_price(book: OrderBook, side: str, size_contracts: float) -> tuple[float, float]:
    """Walk the book to estimate weighted avg fill price + filled contracts.

    side = 'BUY' walks asks (ascending price).
    side = 'SELL' walks bids (descending price).
    Returns (avg_price, filled_contracts). If not enough depth, filled_contracts < request.
    """
    levels = book.asks if side.upper() == "BUY" else book.bids
    if not levels or size_contracts <= 0:
        return 0.0, 0.0
    remaining = size_contracts
    total_usd = 0.0
    total_contracts = 0.0
    for lvl in levels:
        take = min(remaining, lvl.size)
        if take <= 0:
            break
        total_usd += take * lvl.price
        total_contracts += take
        remaining -= take
        if remaining <= 0:
            break
    if total_contracts <= 0:
        return 0.0, 0.0
    # NOTE (bug ledger): fill price = total_usd / total_contracts, NEVER / size_usd
    avg = total_usd / total_contracts
    return avg, total_contracts


def total_depth_at_price(book: OrderBook, side: str, price_cap: float) -> float:
    """Total contracts available within price_cap on given side."""
    levels = book.asks if side.upper() == "BUY" else book.bids
    contracts = 0.0
    for lvl in levels:
        if side.upper() == "BUY" and lvl.price > price_cap:
            break
        if side.upper() == "SELL" and lvl.price < price_cap:
            break
        contracts += lvl.size
    return contracts


def slippage_estimate(book: OrderBook, side: str, size_contracts: float) -> float:
    """Price difference between best quote and avg fill. NEVER multiplied by USD.

    Regression from prior build: slippage cost = price_diff * contracts, NOT * usd.
    """
    if size_contracts <= 0:
        return 0.0
    side_u = side.upper()
    if side_u == "BUY" and not book.asks:
        return 0.0
    if side_u == "SELL" and not book.bids:
        return 0.0
    avg, filled = estimate_fill_price(book, side, size_contracts)
    if filled <= 0:
        return 0.0
    reference = book.best_ask if side_u == "BUY" else book.best_bid
    if side_u == "BUY":
        return max(0.0, avg - reference)
    return max(0.0, reference - avg)
