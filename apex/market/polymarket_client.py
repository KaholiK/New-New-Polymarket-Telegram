"""Polymarket HTTP client for Gamma (discovery) and CLOB (order book, orders).

Notes from the bug ledger:
- Gamma API returns **camelCase** keys: conditionId, clobTokenIds, endDate, acceptingOrders,
  outcomePrices, volume, liquidity.
- `clobTokenIds` is a JSON-encoded string, not a list — caller must parse with json.loads().
- `tags` is frequently None on live data.
- CLOB orders live under `/data/orders`, NOT `/orders` (which returns 405).
- Single order lookup is `/data/orders?id={id}`, NOT `/order/{id}`.
- Balances and positions are on-chain; this REST client does NOT fetch them.
"""

from __future__ import annotations

from typing import Any

import httpx

from apex.utils.logger import get_logger
from apex.utils.retry import CircuitBreaker, async_retry

logger = get_logger(__name__)

GAMMA_BASE = "https://gamma-api.polymarket.com"
CLOB_BASE = "https://clob.polymarket.com"


class PolymarketClient:
    """HTTP client for Gamma + CLOB. One shared client per bot instance."""

    def __init__(
        self,
        timeout: float = 15.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._client = client or httpx.AsyncClient(
            timeout=timeout,
            headers={"User-Agent": "APEX/0.1"},
        )
        self._owns_client = client is None
        self._gamma_breaker = CircuitBreaker("polymarket_gamma")
        self._clob_breaker = CircuitBreaker("polymarket_clob")

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    # --- Gamma: market discovery ---

    @async_retry(attempts=3, base_delay=1.0, max_delay=8.0, exceptions=(httpx.HTTPError,))
    async def _gamma_get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        url = f"{GAMMA_BASE}{path}"
        r = await self._client.get(url, params=params)
        r.raise_for_status()
        return r.json()

    async def list_markets(
        self, closed: bool = False, limit: int = 100, offset: int = 0
    ) -> list[dict[str, Any]]:
        """GET /markets — returns camelCase market dicts."""
        return await self._gamma_breaker.call(
            self._gamma_get, "/markets", {"closed": str(closed).lower(), "limit": limit, "offset": offset}
        )

    async def get_market(self, condition_id: str) -> dict[str, Any] | None:
        try:
            data = await self._gamma_breaker.call(
                self._gamma_get, f"/markets/{condition_id}", None
            )
            return data if isinstance(data, dict) else None
        except httpx.HTTPError:
            return None

    # --- CLOB: order book ---

    @async_retry(attempts=3, base_delay=1.0, max_delay=8.0, exceptions=(httpx.HTTPError,))
    async def _clob_get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        url = f"{CLOB_BASE}{path}"
        r = await self._client.get(url, params=params)
        r.raise_for_status()
        return r.json()

    async def get_book(self, token_id: str) -> dict[str, Any] | None:
        """GET /book?token_id=... — returns {'bids': [...], 'asks': [...]}."""
        try:
            return await self._clob_breaker.call(self._clob_get, "/book", {"token_id": token_id})
        except httpx.HTTPError:
            logger.warning("get_book failed for token_id=%s", token_id)
            return None

    async def get_price(self, token_id: str, side: str = "BUY") -> float | None:
        try:
            data = await self._clob_breaker.call(
                self._clob_get, "/price", {"token_id": token_id, "side": side}
            )
            if isinstance(data, dict) and "price" in data:
                return float(data["price"])
        except (httpx.HTTPError, ValueError, TypeError):
            return None
        return None

    async def get_midpoint(self, token_id: str) -> float | None:
        try:
            data = await self._clob_breaker.call(
                self._clob_get, "/midpoint", {"token_id": token_id}
            )
            if isinstance(data, dict) and "mid" in data:
                return float(data["mid"])
        except (httpx.HTTPError, ValueError, TypeError):
            return None
        return None

    # --- CLOB: orders (correct paths per bug ledger) ---

    async def list_orders(self, **params: Any) -> list[dict[str, Any]]:
        """GET /data/orders — authenticated. Returns list of open orders.

        Requires real auth headers in live mode; this wrapper returns [] on error so
        paper mode is unaffected.
        """
        try:
            data = await self._clob_breaker.call(self._clob_get, "/data/orders", params)
            if isinstance(data, list):
                return data
            if isinstance(data, dict) and "data" in data:
                return data["data"]
        except httpx.HTTPError:
            return []
        return []

    async def get_order(self, order_id: str) -> dict[str, Any] | None:
        """GET /data/orders?id={id} — single order lookup."""
        orders = await self.list_orders(id=order_id)
        if not orders:
            return None
        return orders[0]
