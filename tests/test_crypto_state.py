"""In-memory CryptoState: price updates, klines, fear/greed."""

from __future__ import annotations

from apex.core.crypto_state import CryptoState


def test_update_price_indexes_symbol_and_coingecko_id() -> None:
    state = CryptoState()
    state.update_price("btc", {
        "asset": "bitcoin", "symbol": "btc",
        "price_usd": 100_000, "change_24h_pct": 2.5,
    })
    assert state.get_price("btc") is not None
    assert state.get_price("bitcoin") is not None
    assert state.get_price("BTC") is not None  # case-insensitive


def test_update_price_skips_empty_payload() -> None:
    state = CryptoState()
    state.update_price("btc", {})
    state.update_price("btc", {"price_usd": None})
    assert state.get_price("btc") is None


def test_fear_greed_default() -> None:
    state = CryptoState()
    assert state.get_fear_greed_value() == 50  # neutral default


def test_fear_greed_update() -> None:
    state = CryptoState()
    state.set_fear_greed({"value": 72, "classification": "Greed"})
    assert state.get_fear_greed_value() == 72
    assert state.fear_greed_age_seconds < 1.0


def test_top_coins_distinct() -> None:
    state = CryptoState()
    state.update_price("btc", {
        "asset": "bitcoin", "symbol": "btc",
        "price_usd": 100_000, "change_24h_pct": 2.0,
    })
    state.update_price("eth", {
        "asset": "ethereum", "symbol": "eth",
        "price_usd": 3_000, "change_24h_pct": 1.0,
    })
    top = state.top_coins(10)
    # Two distinct coins even though both are indexed under symbol + coingecko id.
    assert len(top) == 2
    symbols = {s.symbol for s in top}
    assert symbols == {"btc", "eth"}


def test_klines_roundtrip() -> None:
    state = CryptoState()
    bars = [{"open": 1.0, "high": 1.1, "low": 0.9, "close": 1.05, "volume": 10}]
    state.update_klines("btc", "1h", bars)
    assert state.get_klines("btc", "1h") == bars
    assert state.get_klines("btc", "4h") == []
