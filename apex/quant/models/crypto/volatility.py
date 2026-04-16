"""Crypto volatility model.

Indicators:
  - Realized volatility  — annualized std of log returns
  - ATR (Average True Range, 14-period)
  - Bollinger Band width (20-period, 2 std)

The model asks: given realized vol and ATR, how likely is *target_price*
reachable from *current_price* within *timeframe_hours*?

Intuition:
  * High vol + target within 1 ATR  → higher probability (moves happen quickly).
  * High vol + target beyond 2 ATR  → lower probability (would require an outsized move).
  * Low  vol                        → probability is anchored near 0.5 / distance ratio.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from apex.core.models import ModelEstimate
from apex.utils.logger import get_logger
from apex.utils.math_utils import clamp_prob

logger = get_logger(__name__)

MODEL_NAME = "crypto_volatility"

TRADING_HOURS_PER_YEAR = 24 * 365  # crypto trades 24/7

ATR_PERIOD = 14
BB_PERIOD = 20
BB_STD = 2.0


# ---------- indicator helpers ----------

def _realized_vol(closes: np.ndarray) -> float | None:
    """Annualized realized vol from hourly log-returns (assumes hourly bars).

    Returns None when fewer than 2 bars.
    """
    if len(closes) < 2:
        return None
    log_returns = np.diff(np.log(closes))
    if len(log_returns) == 0:
        return None
    sigma_per_bar = float(np.std(log_returns, ddof=1))
    return sigma_per_bar * math.sqrt(TRADING_HOURS_PER_YEAR)


def _atr(klines: list[dict[str, Any]], period: int = ATR_PERIOD) -> float | None:
    """Average True Range over last *period* bars.  Returns None on insufficient data."""
    if len(klines) < period + 1:
        return None
    trs: list[float] = []
    for i in range(1, len(klines)):
        high = float(klines[i]["high"])
        low = float(klines[i]["low"])
        prev_close = float(klines[i - 1]["close"])
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        trs.append(tr)
    # Use the last *period* TRs
    return float(np.mean(trs[-period:]))


def _bollinger_width(closes: np.ndarray, period: int = BB_PERIOD, n_std: float = BB_STD) -> float | None:
    """Bollinger Band width as (upper - lower) / middle.

    Returns None on insufficient data.
    """
    if len(closes) < period:
        return None
    window = closes[-period:]
    mid = float(np.mean(window))
    std = float(np.std(window, ddof=1))
    if mid == 0.0:
        return None
    upper = mid + n_std * std
    lower = mid - n_std * std
    return (upper - lower) / mid  # normalized width


# ---------- main predict ----------

def predict(
    klines: list[dict[str, Any]],
    current_price: float,
    target_price: float,
    timeframe_hours: float = 24.0,
) -> ModelEstimate:
    """Estimate probability of reaching *target_price* given volatility regime.

    Parameters
    ----------
    klines:
        Hourly OHLCV bars (list of dicts with open/high/low/close/volume).
    current_price:
        Current mid-price.
    target_price:
        Price level the question resolves around.
    timeframe_hours:
        Hours until the question resolves.
    """
    if not klines or current_price <= 0:
        logger.warning("crypto_volatility: empty klines or bad price, returning neutral")
        return ModelEstimate(
            model_name=MODEL_NAME,
            probability=0.5,
            uncertainty=0.25,
            confidence=0.1,
            factors=["no_data"],
        )

    closes = np.array([float(k["close"]) for k in klines], dtype=float)

    # ---- compute indicators ----
    rv = _realized_vol(closes)
    atr = _atr(klines)
    bb_width = _bollinger_width(closes)

    factors: list[str] = []
    available = 0

    if rv is not None:
        available += 1
        factors.append(f"realized_vol_ann={rv:.2%}")

    if atr is not None:
        available += 1
        factors.append(f"ATR={atr:.4f}")

    if bb_width is not None:
        available += 1
        factors.append(f"BB_width={bb_width:.4f}")

    if available == 0:
        return ModelEstimate(
            model_name=MODEL_NAME,
            probability=0.5,
            uncertainty=0.25,
            confidence=0.1,
            factors=["insufficient_data"],
        )

    # ---- distance from current price to target (in ATR units if available) ----
    price_move = abs(target_price - current_price)
    upside = target_price >= current_price

    # Base probability from a Gaussian random-walk approximation:
    # Expected std of price over timeframe_hours (using hourly vol)
    prob = 0.5  # default
    if rv is not None and timeframe_hours > 0:
        # Hourly sigma from annualized vol
        sigma_per_hour = rv / math.sqrt(TRADING_HOURS_PER_YEAR)
        # Std of price change over timeframe
        sigma_tf = current_price * sigma_per_hour * math.sqrt(timeframe_hours)
        if sigma_tf > 0:
            # z-score of the required move
            z = price_move / sigma_tf
            # P(|X| >= z) for a half-normal ~ survival function of N(0,1)
            # For directional target: P(X >= z) if upside, P(X <= -z) if downside
            # Simple approximation: 0.5 * erfc(z / sqrt(2))
            prob_reach = 0.5 * math.erfc(z / math.sqrt(2.0))
            prob = clamp_prob(prob_reach)
            factors.append(f"z_score={z:.2f} sigma_tf={sigma_tf:.2f}")

    # ---- ATR adjustment ----
    if atr is not None and atr > 0:
        atr_multiples = price_move / atr
        factors.append(f"move={atr_multiples:.2f}x_ATR")
        if atr_multiples <= 1.0:
            # Within 1 ATR — high vol makes this likely
            prob = clamp_prob(prob * 1.15)
        elif atr_multiples >= 2.0:
            # Beyond 2 ATR — unlikely even in high-vol environment
            prob = clamp_prob(prob * 0.75)

    # ---- Bollinger Band width context ----
    if bb_width is not None:
        if bb_width > 0.10:
            # Wide bands → high current vol, slight boost for reachability
            prob = clamp_prob(prob * 1.05)
            factors.append("BB_wide(high_vol)")
        elif bb_width < 0.02:
            # Tight bands → compression, move could go either way but not far yet
            prob = clamp_prob(prob * 0.95)
            factors.append("BB_tight(compression)")

    confidence = min(0.75, 0.3 + available * 0.15)
    uncertainty = max(0.05, 0.20 - available * 0.04)

    direction_label = "upside" if upside else "downside"
    factors.insert(0, f"target={direction_label} tf={timeframe_hours:.0f}h")

    return ModelEstimate(
        model_name=MODEL_NAME,
        probability=prob,
        uncertainty=uncertainty,
        confidence=confidence,
        factors=factors,
    )
