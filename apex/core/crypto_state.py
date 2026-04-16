"""In-memory crypto market state — populated by engine background jobs.

Stores the latest price, 24h change, klines, and Fear & Greed reading per tracked
asset so Telegram commands can respond instantly without hitting external APIs.
Each update stamps a ``fetched_at`` monotonic timestamp so we can surface
staleness in ``/status`` and crypto dashboards.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class CoinSnapshot:
    asset: str
    symbol: str
    price_usd: float
    change_24h_pct: float | None = None
    fetched_at: float = 0.0

    @property
    def age_seconds(self) -> float:
        if self.fetched_at == 0.0:
            return float("inf")
        return time.monotonic() - self.fetched_at


@dataclass
class CryptoState:
    prices: dict[str, CoinSnapshot] = field(default_factory=dict)
    klines: dict[tuple[str, str], list[dict[str, Any]]] = field(default_factory=dict)
    klines_fetched_at: dict[tuple[str, str], float] = field(default_factory=dict)
    fear_greed: dict[str, Any] = field(default_factory=dict)
    fear_greed_fetched_at: float = 0.0

    def update_price(self, asset: str, data: dict[str, Any]) -> None:
        """Store a fresh price payload from CoinGecko."""
        if not data or data.get("price_usd") is None:
            return
        snap = CoinSnapshot(
            asset=data.get("asset", asset),
            symbol=data.get("symbol", asset).lower(),
            price_usd=float(data["price_usd"]),
            change_24h_pct=(
                float(data["change_24h_pct"])
                if data.get("change_24h_pct") is not None
                else None
            ),
            fetched_at=time.monotonic(),
        )
        # Index by ticker (btc) so commands can look up by short name.
        self.prices[snap.symbol.lower()] = snap
        # Also store by CoinGecko id (bitcoin) for predict flows.
        self.prices[snap.asset.lower()] = snap

    def update_klines(
        self, asset: str, interval: str, bars: list[dict[str, Any]]
    ) -> None:
        if not bars:
            return
        self.klines[(asset.lower(), interval)] = bars
        self.klines_fetched_at[(asset.lower(), interval)] = time.monotonic()

    def get_klines(self, asset: str, interval: str = "1h") -> list[dict[str, Any]]:
        return self.klines.get((asset.lower(), interval), [])

    def set_fear_greed(self, data: dict[str, Any]) -> None:
        if not data:
            return
        self.fear_greed = data
        self.fear_greed_fetched_at = time.monotonic()

    def get_fear_greed_value(self, default: int = 50) -> int:
        try:
            return int(self.fear_greed.get("value", default))
        except (TypeError, ValueError):
            return default

    @property
    def fear_greed_age_seconds(self) -> float:
        if self.fear_greed_fetched_at == 0.0:
            return float("inf")
        return time.monotonic() - self.fear_greed_fetched_at

    def get_price(self, asset: str) -> CoinSnapshot | None:
        return self.prices.get(asset.lower())

    def top_coins(self, n: int = 10) -> list[CoinSnapshot]:
        """Distinct coins sorted by recency (symbol-keyed snapshots only)."""
        seen: set[str] = set()
        result: list[CoinSnapshot] = []
        for key, snap in self.prices.items():
            # Pick the short-symbol entries (e.g., "btc") to avoid duplicates
            # from the dual (symbol + coingecko-id) indexing.
            if snap.symbol.lower() != key:
                continue
            if snap.symbol in seen:
                continue
            seen.add(snap.symbol)
            result.append(snap)
        # Stable order: largest price first as a rough proxy for "majors".
        result.sort(key=lambda s: s.price_usd, reverse=True)
        return result[:n]
