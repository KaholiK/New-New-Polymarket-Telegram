"""Crypto momentum model.

Indicators calculated from raw klines (list of dicts with open/high/low/close/volume):
  - RSI 14-period
  - MACD (12, 26, 9)
  - Multi-timeframe returns: 1h / 4h / 24h / 7d

The model answers: "given *current_price* and a *target_price* to be reached within
*timeframe_hours*, how probable is it that price will touch/exceed *target_price*?"

Upside target  → bullish signals increase probability.
Downside target → bearish signals increase probability.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from apex.core.models import ModelEstimate
from apex.utils.logger import get_logger
from apex.utils.math_utils import clamp_prob

logger = get_logger(__name__)

MODEL_NAME = "crypto_momentum"

# RSI thresholds
RSI_OVERBOUGHT = 70.0
RSI_OVERSOLD = 30.0

# MACD periods
MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9


# ---------- indicator helpers ----------

def _ema(values: np.ndarray, period: int) -> np.ndarray:
    """Exponential moving average (standard EMA, not SMA seeded)."""
    if len(values) == 0:
        return np.array([])
    alpha = 2.0 / (period + 1)
    ema = np.empty_like(values, dtype=float)
    ema[0] = values[0]
    for i in range(1, len(values)):
        ema[i] = alpha * values[i] + (1.0 - alpha) * ema[i - 1]
    return ema


def _rsi(closes: np.ndarray, period: int = 14) -> float | None:
    """RSI of most-recent bar.  Returns None when insufficient data."""
    if len(closes) < period + 1:
        return None
    deltas = np.diff(closes[-(period + 1):])
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)
    avg_gain = gains.mean()
    avg_loss = losses.mean()
    if avg_loss == 0.0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def _macd(closes: np.ndarray) -> tuple[float, float] | None:
    """Return (macd_line, signal_line) for the last bar.

    Returns None when insufficient data.
    """
    min_len = MACD_SLOW + MACD_SIGNAL
    if len(closes) < min_len:
        return None
    ema_fast = _ema(closes, MACD_FAST)
    ema_slow = _ema(closes, MACD_SLOW)
    macd_line = ema_fast - ema_slow
    signal_line = _ema(macd_line, MACD_SIGNAL)
    return float(macd_line[-1]), float(signal_line[-1])


def _period_return(closes: np.ndarray, n_bars: int) -> float | None:
    """Return over the last *n_bars*.  None when insufficient data."""
    if len(closes) < n_bars + 1:
        return None
    return float(closes[-1] / closes[-(n_bars + 1)] - 1.0)


# ---------- main predict ----------

def predict(
    klines: list[dict[str, Any]],
    current_price: float,
    target_price: float,
    timeframe: str = "1h",
) -> ModelEstimate:
    """Produce a ModelEstimate for hitting *target_price* within *timeframe*.

    Parameters
    ----------
    klines:
        List of dicts with keys ``open``, ``high``, ``low``, ``close``, ``volume``.
        Expected to be 1-hour bars (the most granular data we fetch from Binance).
    current_price:
        Current mid-price of the asset.
    target_price:
        The market's price target (question resolves YES if price >= target).
    timeframe:
        Human-readable timeframe string, e.g. ``"1h"``, ``"4h"``, ``"24h"``, ``"7d"``.
        Used only for returning an informative factor string.
    """
    # ---- graceful degradation ----
    if not klines or current_price <= 0:
        logger.warning("crypto_momentum: empty klines or bad price, returning neutral")
        return ModelEstimate(
            model_name=MODEL_NAME,
            probability=0.5,
            uncertainty=0.25,
            confidence=0.1,
            factors=["no_data"],
        )

    closes = np.array([float(k["close"]) for k in klines], dtype=float)
    if len(closes) < 2:
        return ModelEstimate(
            model_name=MODEL_NAME,
            probability=0.5,
            uncertainty=0.25,
            confidence=0.1,
            factors=["insufficient_data"],
        )

    upside = target_price >= current_price

    # ---- RSI ----
    rsi = _rsi(closes)
    rsi_signal = 0.0  # positive = bullish
    rsi_factors: list[str] = []
    if rsi is not None:
        if rsi > RSI_OVERBOUGHT:
            rsi_signal = -0.15  # overbought → bearish
            rsi_factors.append(f"RSI={rsi:.1f} overbought")
        elif rsi < RSI_OVERSOLD:
            rsi_signal = 0.10  # oversold → reversal likely bullish
            rsi_factors.append(f"RSI={rsi:.1f} oversold")
        else:
            rsi_signal = 0.05 if rsi < 55 else 0.0
            rsi_factors.append(f"RSI={rsi:.1f} neutral")

    # ---- MACD ----
    macd_result = _macd(closes)
    macd_signal = 0.0
    macd_factors: list[str] = []
    if macd_result is not None:
        macd_line, sig_line = macd_result
        if macd_line > sig_line:
            macd_signal = 0.10  # bullish crossover
            macd_factors.append(f"MACD={macd_line:.4f} bullish")
        elif macd_line < sig_line:
            macd_signal = -0.10  # bearish
            macd_factors.append(f"MACD={macd_line:.4f} bearish")

    # ---- multi-timeframe returns ----
    ret_1h = _period_return(closes, 1)
    ret_4h = _period_return(closes, 4)
    ret_24h = _period_return(closes, 24)
    ret_7d = _period_return(closes, 168)  # 7d × 24h

    return_signal = 0.0
    return_factors: list[str] = []
    for label, ret in [("1h", ret_1h), ("4h", ret_4h), ("24h", ret_24h), ("7d", ret_7d)]:
        if ret is None:
            continue
        return_factors.append(f"ret_{label}={ret*100:.2f}%")
        # weight recent returns more heavily
        weight = {"1h": 0.4, "4h": 0.3, "24h": 0.2, "7d": 0.1}.get(label, 0.1)
        return_signal += weight * math.tanh(ret * 10)  # tanh keeps it in (-1, 1)

    # ---- combine signals ----
    # Total raw score in roughly (-0.35, +0.35)
    total_signal = rsi_signal + macd_signal + return_signal * 0.3

    # For an upside target, positive signals → higher prob; for downside, flip.
    if not upside:
        total_signal = -total_signal

    base_prob = 0.5 + total_signal
    prob = clamp_prob(base_prob)

    # Confidence scales with data richness
    n_indicators = sum([rsi is not None, macd_result is not None, ret_24h is not None])
    confidence = min(0.8, 0.3 + n_indicators * 0.15)
    uncertainty = max(0.05, 0.25 - n_indicators * 0.05)

    factors = (
        [f"target={'above' if upside else 'below'}_current tf={timeframe}"]
        + rsi_factors
        + macd_factors
        + return_factors
    )

    return ModelEstimate(
        model_name=MODEL_NAME,
        probability=prob,
        uncertainty=uncertainty,
        confidence=confidence,
        factors=factors,
    )
