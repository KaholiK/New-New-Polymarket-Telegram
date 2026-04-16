"""Tests for crypto models: momentum, volatility, technical, sentiment, ensemble."""

from __future__ import annotations

import numpy as np
import pytest

from apex.quant.crypto_ensemble import predict as ensemble_predict
from apex.quant.models.crypto.momentum import predict as momentum_predict
from apex.quant.models.crypto.sentiment import predict as sentiment_predict
from apex.quant.models.crypto.volatility import predict as volatility_predict


def _fake_klines(n: int = 100, base_price: float = 50000.0) -> list[dict]:
    rng = np.random.default_rng(42)
    klines = []
    price = base_price
    for i in range(n):
        change = rng.normal(0, price * 0.01)
        o = price
        h = price + abs(rng.normal(0, price * 0.005))
        lo = price - abs(rng.normal(0, price * 0.005))
        c = price + change
        vol = rng.uniform(100, 10000)
        klines.append({"time": 1700000000 + i * 3600, "open": o, "high": h, "low": lo, "close": c, "volume": vol})
        price = c
    return klines


# ---- Momentum ----

def test_momentum_returns_estimate():
    klines = _fake_klines()
    est = momentum_predict(klines, 50000.0, 55000.0, timeframe="24h")
    assert est.model_name == "crypto_momentum"
    assert 0.001 <= est.probability <= 0.999
    assert est.factors


def test_momentum_empty_klines():
    est = momentum_predict([], 50000.0, 55000.0, timeframe="24h")
    assert est.probability == pytest.approx(0.5, abs=0.1)


# ---- Volatility ----

def test_volatility_returns_estimate():
    klines = _fake_klines()
    est = volatility_predict(klines, 50000.0, 55000.0, timeframe_hours=24)
    assert est.model_name == "crypto_volatility"
    assert 0.001 <= est.probability <= 0.999


def test_volatility_empty_klines():
    est = volatility_predict([], 50000.0, 55000.0, timeframe_hours=24)
    assert est.probability == pytest.approx(0.5, abs=0.1)


# ---- Sentiment ----

def test_sentiment_extreme_fear_bullish():
    est = sentiment_predict(10, 50000.0, 55000.0)
    assert est.model_name == "crypto_sentiment"
    assert est.probability >= 0.5


def test_sentiment_extreme_greed_bearish():
    est = sentiment_predict(90, 50000.0, 55000.0)
    assert est.probability <= 0.55


def test_sentiment_neutral():
    est = sentiment_predict(50, 50000.0, 55000.0)
    assert abs(est.probability - 0.5) < 0.15


# ---- Ensemble ----

def test_ensemble_combines_models():
    klines = _fake_klines()
    result = ensemble_predict(
        asset="bitcoin",
        timeframe_hours=24,
        klines=klines,
        current_price=50000.0,
        target_price=55000.0,
        fear_greed=45,
    )
    assert "ensemble_prob" in result
    assert "model_estimates" in result
    assert 0.001 <= result["ensemble_prob"] <= 0.999
    assert len(result["model_estimates"]) >= 3


def test_ensemble_short_timeframe_weights():
    klines = _fake_klines()
    result = ensemble_predict(
        asset="bitcoin",
        timeframe_hours=1,
        klines=klines,
        current_price=50000.0,
        target_price=50500.0,
        fear_greed=50,
    )
    assert result["weights"]["crypto_momentum"] > result["weights"]["crypto_sentiment"]


def test_ensemble_long_timeframe_weights():
    klines = _fake_klines()
    result = ensemble_predict(
        asset="bitcoin",
        timeframe_hours=168,
        klines=klines,
        current_price=50000.0,
        target_price=60000.0,
        fear_greed=50,
    )
    assert result["weights"]["crypto_technical"] > result["weights"]["crypto_momentum"]
