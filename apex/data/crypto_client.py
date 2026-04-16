"""Crypto data client — fetches from free public APIs with TTL caching.

Sources (all key-free):
  CoinGecko  — price history, current price + 24h change
  Binance    — public klines (OHLCV)
  Alternative.me — Fear & Greed index

All network calls degrade gracefully: a failure returns an empty value and logs
a warning so the rest of the pipeline is unaffected.
"""

from __future__ import annotations

import time
from typing import Any

import httpx

from apex.utils.logger import get_logger
from apex.utils.retry import async_retry

logger = get_logger(__name__)

# ---------- URL roots ----------

COINGECKO_BASE = "https://api.coingecko.com/api/v3"
BINANCE_BASE = "https://api.binance.com/api/v3"
FEAR_GREED_URL = "https://api.alternative.me/fng/?limit=1"

# ---------- Asset maps ----------

# Common short name / ticker → CoinGecko platform ID
COINGECKO_IDS: dict[str, str] = {
    "btc": "bitcoin",
    "bitcoin": "bitcoin",
    "eth": "ethereum",
    "ethereum": "ethereum",
    "sol": "solana",
    "solana": "solana",
    "xrp": "ripple",
    "ripple": "ripple",
    "doge": "dogecoin",
    "dogecoin": "dogecoin",
    "ada": "cardano",
    "cardano": "cardano",
    "avax": "avalanche-2",
    "avalanche": "avalanche-2",
    "avalanche-2": "avalanche-2",
    "link": "chainlink",
    "chainlink": "chainlink",
    "matic": "matic-network",
    "polygon": "matic-network",
    "matic-network": "matic-network",
    "dot": "polkadot",
    "polkadot": "polkadot",
    "bnb": "binancecoin",
    "binancecoin": "binancecoin",
    "trx": "tron",
    "tron": "tron",
    "ltc": "litecoin",
    "litecoin": "litecoin",
    "bch": "bitcoin-cash",
    "bitcoin-cash": "bitcoin-cash",
}

# Common short name / ticker → Binance base symbol (appended with USDT)
BINANCE_SYMBOLS: dict[str, str] = {
    "btc": "BTC",
    "bitcoin": "BTC",
    "eth": "ETH",
    "ethereum": "ETH",
    "sol": "SOL",
    "solana": "SOL",
    "xrp": "XRP",
    "ripple": "XRP",
    "doge": "DOGE",
    "dogecoin": "DOGE",
    "ada": "ADA",
    "cardano": "ADA",
    "avax": "AVAX",
    "avalanche": "AVAX",
    "avalanche-2": "AVAX",
    "link": "LINK",
    "chainlink": "LINK",
    "matic": "MATIC",
    "polygon": "MATIC",
    "matic-network": "MATIC",
    "dot": "DOT",
    "polkadot": "DOT",
    "bnb": "BNB",
    "binancecoin": "BNB",
    "trx": "TRX",
    "tron": "TRX",
    "ltc": "LTC",
    "litecoin": "LTC",
    "bch": "BCH",
    "bitcoin-cash": "BCH",
}

# TTL constants (seconds)
TTL_PRICE = 5 * 60        # 5 minutes
TTL_HISTORICAL = 15 * 60  # 15 minutes
TTL_FEAR_GREED = 60 * 60  # 1 hour


# ---------- TTL cache ----------

class _TTLCache:
    """Minimal per-key TTL cache; no external dependencies."""

    def __init__(self) -> None:
        self._store: dict[str, tuple[float, Any]] = {}

    def get(self, key: str) -> Any:
        item = self._store.get(key)
        if item is None:
            return None
        expiry, val = item
        if time.monotonic() > expiry:
            self._store.pop(key, None)
            return None
        return val

    def set(self, key: str, value: Any, ttl_seconds: float) -> None:
        self._store[key] = (time.monotonic() + ttl_seconds, value)

    def clear(self) -> None:
        self._store.clear()


# ---------- helpers ----------

def _resolve_coingecko_id(asset: str) -> str | None:
    return COINGECKO_IDS.get(asset.lower().strip())


def _resolve_binance_symbol(asset: str) -> str | None:
    base = BINANCE_SYMBOLS.get(asset.lower().strip())
    return f"{base}USDT" if base else None


# ---------- client ----------

class CryptoClient:
    """Async HTTP client for free public crypto APIs.

    Usage::

        async with CryptoClient() as client:
            price = await client.get_price("btc")
            klines = await client.get_klines("eth", interval="1h", limit=100)
            fg = await client.get_fear_greed()
    """

    def __init__(self, timeout: float = 15.0) -> None:
        self._client = httpx.AsyncClient(
            timeout=timeout,
            headers={"User-Agent": "APEX/0.1"},
            follow_redirects=True,
        )
        self._cache = _TTLCache()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> CryptoClient:
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.aclose()

    # ------------------------------------------------------------------ #
    #  Internal helpers                                                    #
    # ------------------------------------------------------------------ #

    @async_retry(attempts=3, base_delay=1.0, max_delay=8.0, exceptions=(httpx.HTTPError,))
    async def _get(self, url: str, params: dict[str, Any] | None = None) -> Any:
        r = await self._client.get(url, params=params)
        r.raise_for_status()
        return r.json()

    async def _cached_get(
        self,
        cache_key: str,
        url: str,
        params: dict[str, Any] | None,
        ttl: float,
    ) -> Any:
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached
        try:
            data = await self._get(url, params)
        except httpx.HTTPError as exc:
            logger.warning("crypto_client GET %s failed: %s", url, exc)
            return None
        except Exception as exc:  # noqa: BLE001
            logger.warning("crypto_client GET %s unexpected error: %s", url, exc)
            return None
        if data is not None:
            self._cache.set(cache_key, data, ttl)
        return data

    # ------------------------------------------------------------------ #
    #  Public API                                                          #
    # ------------------------------------------------------------------ #

    async def get_price(self, asset: str) -> dict[str, Any]:
        """Return current price and 24 h change for *asset*.

        Returns::

            {
                "asset": "bitcoin",
                "symbol": "btc",
                "price_usd": 65000.0,
                "change_24h_pct": 2.3,    # percent, may be None
            }

        Returns an empty dict on failure.
        """
        cg_id = _resolve_coingecko_id(asset)
        if not cg_id:
            logger.warning("crypto_client: unknown asset '%s'", asset)
            return {}

        cache_key = f"price:{cg_id}"
        data = await self._cached_get(
            cache_key=cache_key,
            url=f"{COINGECKO_BASE}/simple/price",
            params={
                "ids": cg_id,
                "vs_currencies": "usd",
                "include_24hr_change": "true",
            },
            ttl=TTL_PRICE,
        )
        if not data or cg_id not in data:
            return {}

        coin = data[cg_id]
        return {
            "asset": cg_id,
            "symbol": asset.lower().strip(),
            "price_usd": coin.get("usd"),
            "change_24h_pct": coin.get("usd_24h_change"),
        }

    async def get_ohlc(self, asset: str, days: int = 7) -> list[dict[str, Any]]:
        """Return daily OHLC price history from CoinGecko for *asset*.

        Each element::

            {"time": unix_ms, "price": float}

        CoinGecko's ``/market_chart`` endpoint returns a list of
        ``[unix_ms, price]`` pairs for the ``prices`` key; we reshape them.
        Returns [] on failure.
        """
        cg_id = _resolve_coingecko_id(asset)
        if not cg_id:
            logger.warning("crypto_client: unknown asset '%s'", asset)
            return []

        cache_key = f"ohlc:{cg_id}:{days}"
        data = await self._cached_get(
            cache_key=cache_key,
            url=f"{COINGECKO_BASE}/coins/{cg_id}/market_chart",
            params={"vs_currency": "usd", "days": str(days)},
            ttl=TTL_HISTORICAL,
        )
        if not data:
            return []

        prices = data.get("prices", [])
        result: list[dict[str, Any]] = []
        for entry in prices:
            if len(entry) >= 2:
                result.append({"time": entry[0], "price": float(entry[1])})
        return result

    async def get_klines(
        self,
        asset: str,
        interval: str = "1h",
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Return OHLCV klines from Binance public API for *asset*.

        Each element::

            {
                "time":   unix_ms (open time),
                "open":   float,
                "high":   float,
                "low":    float,
                "close":  float,
                "volume": float,
            }

        Returns [] on failure or unknown asset.
        """
        symbol = _resolve_binance_symbol(asset)
        if not symbol:
            logger.warning("crypto_client: no Binance symbol for '%s'", asset)
            return []

        cache_key = f"klines:{symbol}:{interval}:{limit}"
        raw = await self._cached_get(
            cache_key=cache_key,
            url=f"{BINANCE_BASE}/klines",
            params={"symbol": symbol, "interval": interval, "limit": str(limit)},
            ttl=TTL_PRICE,
        )
        if not raw:
            return []

        result: list[dict[str, Any]] = []
        for row in raw:
            # Binance kline row: [open_time, open, high, low, close, volume, ...]
            if len(row) < 6:
                continue
            try:
                result.append(
                    {
                        "time": int(row[0]),
                        "open": float(row[1]),
                        "high": float(row[2]),
                        "low": float(row[3]),
                        "close": float(row[4]),
                        "volume": float(row[5]),
                    }
                )
            except (TypeError, ValueError) as exc:
                logger.warning("crypto_client: bad kline row %s: %s", row, exc)
        return result

    async def get_fear_greed(self) -> dict[str, Any]:
        """Return the current Fear & Greed index from alternative.me.

        Returns::

            {
                "value": 45,                   # 0-100
                "classification": "Fear",      # e.g. Extreme Fear / Fear / Neutral / Greed / Extreme Greed
                "timestamp": "...",
            }

        Returns {} on failure.
        """
        cache_key = "fear_greed"
        data = await self._cached_get(
            cache_key=cache_key,
            url=FEAR_GREED_URL,
            params=None,
            ttl=TTL_FEAR_GREED,
        )
        if not data:
            return {}

        entries = data.get("data", [])
        if not entries:
            return {}

        entry = entries[0]
        try:
            return {
                "value": int(entry.get("value", 50)),
                "classification": entry.get("value_classification", "Neutral"),
                "timestamp": entry.get("timestamp"),
            }
        except (TypeError, ValueError) as exc:
            logger.warning("crypto_client: bad fear/greed response: %s", exc)
            return {}
