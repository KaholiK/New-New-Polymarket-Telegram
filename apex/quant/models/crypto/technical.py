"""Crypto technical analysis model.

Indicators:
  - Simple Moving Averages: SMA 20, 50, 200
  - Support / resistance detection from recent swing highs/lows
  - Trend detection (price above/below 50 SMA)
  - Breakout detection (price crosses above resistance or below support)

The model answers: given current technicals, how likely is *target_price*
reachable from *current_price* within *timeframe_hours*?
"""

from __future__ import annotations

from typing import Any

import numpy as np

from apex.core.models import ModelEstimate
from apex.utils.logger import get_logger
from apex.utils.math_utils import clamp_prob

logger = get_logger(__name__)

MODEL_NAME = "crypto_technical"

SMA_PERIODS = (20, 50, 200)
SWING_LOOKBACK = 20   # bars used to detect swing highs/lows
BREAKOUT_MARGIN = 0.005  # 0.5% above/below S/R counts as a breakout


# ---------- indicator helpers ----------

def _sma(closes: np.ndarray, period: int) -> float | None:
    """Simple moving average of the last *period* closes.  None when insufficient."""
    if len(closes) < period:
        return None
    return float(np.mean(closes[-period:]))


def _detect_support_resistance(
    klines: list[dict[str, Any]],
    lookback: int = SWING_LOOKBACK,
) -> tuple[float | None, float | None]:
    """Identify the nearest support and resistance levels from recent swing points.

    A swing high is a candle whose ``high`` is higher than its two neighbours.
    A swing low is a candle whose ``low`` is lower than its two neighbours.

    Returns (support_level, resistance_level) — both can be None if insufficient data.
    """
    if len(klines) < lookback + 2:
        return None, None

    recent = klines[-lookback:]
    swing_highs: list[float] = []
    swing_lows: list[float] = []

    for i in range(1, len(recent) - 1):
        h = float(recent[i]["high"])
        lo = float(recent[i]["low"])
        if h > float(recent[i - 1]["high"]) and h > float(recent[i + 1]["high"]):
            swing_highs.append(h)
        if lo < float(recent[i - 1]["low"]) and lo < float(recent[i + 1]["low"]):
            swing_lows.append(lo)

    resistance = max(swing_highs) if swing_highs else None
    support = min(swing_lows) if swing_lows else None
    return support, resistance


def _trend(current_price: float, sma50: float | None) -> str:
    """Return 'bullish', 'bearish', or 'neutral' based on price vs SMA-50."""
    if sma50 is None:
        return "neutral"
    if current_price > sma50 * 1.005:
        return "bullish"
    if current_price < sma50 * 0.995:
        return "bearish"
    return "neutral"


def _breakout(
    current_price: float,
    support: float | None,
    resistance: float | None,
    margin: float = BREAKOUT_MARGIN,
) -> str:
    """Classify breakout state: 'above_resistance', 'below_support', or 'ranging'."""
    if resistance is not None and current_price > resistance * (1.0 + margin):
        return "above_resistance"
    if support is not None and current_price < support * (1.0 - margin):
        return "below_support"
    return "ranging"


# ---------- main predict ----------

def predict(
    klines: list[dict[str, Any]],
    current_price: float,
    target_price: float,
    timeframe_hours: float = 24.0,
) -> ModelEstimate:
    """Estimate probability of reaching *target_price* from technical structure.

    Parameters
    ----------
    klines:
        Hourly OHLCV bars (dicts with open/high/low/close/volume keys).
    current_price:
        Current mid-price.
    target_price:
        Price level the market question resolves around.
    timeframe_hours:
        Hours until resolution — longer timeframes give more weight to trend
        alignment and less to short-term support/resistance.
    """
    if not klines or current_price <= 0:
        logger.warning("crypto_technical: empty klines or bad price, returning neutral")
        return ModelEstimate(
            model_name=MODEL_NAME,
            probability=0.5,
            uncertainty=0.25,
            confidence=0.1,
            factors=["no_data"],
        )

    closes = np.array([float(k["close"]) for k in klines], dtype=float)
    if len(closes) < 3:
        return ModelEstimate(
            model_name=MODEL_NAME,
            probability=0.5,
            uncertainty=0.25,
            confidence=0.1,
            factors=["insufficient_data"],
        )

    upside = target_price >= current_price
    factors: list[str] = [
        f"target={'above' if upside else 'below'}_current tf={timeframe_hours:.0f}h"
    ]

    # ---- SMAs ----
    sma20 = _sma(closes, 20)
    sma50 = _sma(closes, 50)
    sma200 = _sma(closes, 200)

    sma_signal = 0.0
    available = 0

    if sma20 is not None:
        available += 1
        factors.append(f"SMA20={sma20:.4f}")
        if current_price > sma20:
            sma_signal += 0.05
        else:
            sma_signal -= 0.05

    if sma50 is not None:
        available += 1
        factors.append(f"SMA50={sma50:.4f}")
        if current_price > sma50:
            sma_signal += 0.08
        else:
            sma_signal -= 0.08

    if sma200 is not None:
        available += 1
        factors.append(f"SMA200={sma200:.4f}")
        # Golden cross / death cross context
        if current_price > sma200:
            sma_signal += 0.07
            factors.append("price_above_SMA200(bullish_LT)")
        else:
            sma_signal -= 0.07
            factors.append("price_below_SMA200(bearish_LT)")

    # ---- trend ----
    trend = _trend(current_price, sma50)
    factors.append(f"trend={trend}")

    trend_signal = 0.0
    if trend == "bullish":
        trend_signal = 0.10
    elif trend == "bearish":
        trend_signal = -0.10

    # ---- support / resistance ----
    support, resistance = _detect_support_resistance(klines)
    sr_signal = 0.0

    if support is not None:
        dist_to_support_pct = (current_price - support) / current_price
        factors.append(f"support={support:.4f} ({dist_to_support_pct:.2%} below)")

    if resistance is not None:
        dist_to_resist_pct = (resistance - current_price) / current_price
        factors.append(f"resistance={resistance:.4f} ({dist_to_resist_pct:.2%} above)")

    # For upside target: having room before resistance is bearish for reaching it,
    # being near resistance is slightly bullish (can break through)
    if upside and resistance is not None:
        dist_pct = (resistance - current_price) / current_price
        if dist_pct < 0.02:
            # Very near resistance — breakout possible
            sr_signal = 0.05
            factors.append("near_resistance(potential_breakout)")
        elif target_price > resistance:
            # Target is beyond resistance — harder to reach
            sr_signal = -0.08
            factors.append("target_beyond_resistance(headwind)")
    elif not upside and support is not None:
        dist_pct = (current_price - support) / current_price
        if dist_pct < 0.02:
            # Very near support — breakdown possible
            sr_signal = 0.05
            factors.append("near_support(potential_breakdown)")
        elif target_price < support:
            # Target is below support — harder to reach
            sr_signal = -0.08
            factors.append("target_below_support(headwind)")

    # ---- breakout state ----
    breakout = _breakout(current_price, support, resistance)
    factors.append(f"breakout={breakout}")

    breakout_signal = 0.0
    if upside and breakout == "above_resistance":
        breakout_signal = 0.12  # momentum continuation
        factors.append("breakout_above_resistance(bullish)")
    elif not upside and breakout == "below_support":
        breakout_signal = 0.12  # breakdown continuation
        factors.append("breakdown_below_support(bearish_for_price)")
    elif upside and breakout == "below_support":
        breakout_signal = -0.10  # below support — upside target harder
    elif not upside and breakout == "above_resistance":
        breakout_signal = -0.10  # above resistance — downside target harder

    # ---- timeframe adjustment ----
    # Longer timeframes give more weight to trend, less to short-term S/R noise
    tf_trend_weight = min(1.0, timeframe_hours / 168.0)  # 1.0 at 7d
    tf_sr_weight = max(0.0, 1.0 - tf_trend_weight)

    total_signal = (
        sma_signal * 0.30
        + trend_signal * (0.25 + 0.15 * tf_trend_weight)
        + sr_signal * (0.20 * tf_sr_weight + 0.05)
        + breakout_signal * (0.15 + 0.10 * tf_sr_weight)
    )

    # For downside targets, bullish technicals are bearish for probability
    if not upside:
        total_signal = -total_signal

    base_prob = 0.5 + clamp_prob(0.5 + total_signal) - 0.5
    prob = clamp_prob(base_prob)

    confidence = min(0.75, 0.2 + available * 0.15 + (0.1 if support is not None else 0.0))
    uncertainty = max(0.05, 0.22 - available * 0.04)

    return ModelEstimate(
        model_name=MODEL_NAME,
        probability=prob,
        uncertainty=uncertainty,
        confidence=confidence,
        factors=factors,
    )
