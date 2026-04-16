"""Crypto ensemble: combines momentum, volatility, technical and sentiment models.

Timeframe-aware weights:
  Short  (1–4 h):   momentum 0.35, volatility 0.30, technical 0.20, sentiment 0.15
  Medium (12–24 h): momentum 0.25, volatility 0.25, technical 0.30, sentiment 0.20
  Long   (3 d+):    momentum 0.15, volatility 0.20, technical 0.35, sentiment 0.30

The combined probability is produced via ``geometric_mean_odds`` (log-linear pool)
which is consistent with the rest of the APEX quant pipeline.

The public entry-point is ``predict()``, which is synchronous — callers are expected
to have already fetched klines, current_price, target_price and fear_greed via the
async ``CryptoClient`` before invoking this function.
"""

from __future__ import annotations

import math
from typing import Any

from apex.core.models import Confidence, ModelEstimate
from apex.quant.models.crypto import momentum as _momentum_mod
from apex.quant.models.crypto import sentiment as _sentiment_mod
from apex.quant.models.crypto import technical as _technical_mod
from apex.quant.models.crypto import volatility as _volatility_mod
from apex.utils.logger import get_logger
from apex.utils.math_utils import clamp_prob, geometric_mean_odds

logger = get_logger(__name__)

# ---------- weight tables ----------

# (momentum, volatility, technical, sentiment)
_SHORT_WEIGHTS = (0.35, 0.30, 0.20, 0.15)   # 1–4 h
_MEDIUM_WEIGHTS = (0.25, 0.25, 0.30, 0.20)  # 12–24 h
_LONG_WEIGHTS = (0.15, 0.20, 0.35, 0.30)    # 3 d+  (72 h+)

SHORT_UPPER_HOURS = 4.0
MEDIUM_LOWER_HOURS = 12.0
MEDIUM_UPPER_HOURS = 24.0
LONG_LOWER_HOURS = 72.0


def _select_weights(timeframe_hours: float) -> tuple[float, float, float, float]:
    """Return (momentum_w, volatility_w, technical_w, sentiment_w) for the timeframe."""
    if timeframe_hours <= SHORT_UPPER_HOURS:
        return _SHORT_WEIGHTS
    if timeframe_hours <= MEDIUM_UPPER_HOURS:
        # Interpolate between short and medium
        t = (timeframe_hours - SHORT_UPPER_HOURS) / (MEDIUM_UPPER_HOURS - SHORT_UPPER_HOURS)
        return tuple(
            s * (1 - t) + m * t
            for s, m in zip(_SHORT_WEIGHTS, _MEDIUM_WEIGHTS)
        )  # type: ignore[return-value]
    if timeframe_hours < LONG_LOWER_HOURS:
        # Interpolate between medium and long
        t = (timeframe_hours - MEDIUM_UPPER_HOURS) / (LONG_LOWER_HOURS - MEDIUM_UPPER_HOURS)
        return tuple(
            med * (1 - t) + lng * t
            for med, lng in zip(_MEDIUM_WEIGHTS, _LONG_WEIGHTS)
        )  # type: ignore[return-value]
    return _LONG_WEIGHTS


def _classify_confidence(
    n_models: int,
    disagreement: float,
) -> Confidence:
    """Simple confidence classification for crypto ensemble."""
    if n_models == 0:
        return Confidence.NO_OPINION
    if n_models >= 3 and disagreement < 0.05:
        return Confidence.HIGH
    if n_models >= 2 and disagreement < 0.10:
        return Confidence.MEDIUM
    if disagreement > 0.12:
        return Confidence.LOW
    return Confidence.LOW


# ---------- public API ----------

def predict(
    asset: str,
    timeframe_hours: float,
    klines: list[dict[str, Any]],
    current_price: float,
    target_price: float,
    fear_greed: int = 50,
    headlines: list[str] | None = None,
    timeframe_label: str = "",
) -> dict[str, Any]:
    """Run all crypto models and return a combined forecast dict.

    Parameters
    ----------
    asset:
        Asset name/ticker string (informational only, used in the returned dict).
    timeframe_hours:
        Hours until the question resolves.  Drives weight selection.
    klines:
        List of OHLCV dicts from ``CryptoClient.get_klines()``.  May be empty —
        all models degrade gracefully.
    current_price:
        Current mid-price of the asset.
    target_price:
        Price level the Polymarket question resolves around.
    fear_greed:
        Fear & Greed index value 0-100 (default 50 = neutral).
    headlines:
        Optional list of recent news headline strings for sentiment model.
    timeframe_label:
        Human-readable label for the timeframe, e.g. ``"24h"`` (informational).

    Returns
    -------
    dict with keys:
        ``ensemble_prob``   – float, combined probability (0-1)
        ``ensemble_std``    – float, disagreement across models
        ``confidence``      – Confidence enum value
        ``model_estimates`` – dict[str, ModelEstimate]
        ``weights``         – dict[str, float] of applied weights
        ``key_factors``     – list[str] of notable factors
        ``asset``           – str
        ``timeframe_hours`` – float
        ``current_price``   – float
        ``target_price``    – float
    """
    tf_label = timeframe_label or f"{timeframe_hours:.0f}h"

    # ---- run each model ----
    mom_est: ModelEstimate = _momentum_mod.predict(
        klines=klines,
        current_price=current_price,
        target_price=target_price,
        timeframe=tf_label,
    )

    vol_est: ModelEstimate = _volatility_mod.predict(
        klines=klines,
        current_price=current_price,
        target_price=target_price,
        timeframe_hours=timeframe_hours,
    )

    tech_est: ModelEstimate = _technical_mod.predict(
        klines=klines,
        current_price=current_price,
        target_price=target_price,
        timeframe_hours=timeframe_hours,
    )

    sent_est: ModelEstimate = _sentiment_mod.predict(
        fear_greed=fear_greed,
        current_price=current_price,
        target_price=target_price,
        headlines=headlines,
    )

    estimates: dict[str, ModelEstimate] = {
        "crypto_momentum": mom_est,
        "crypto_volatility": vol_est,
        "crypto_technical": tech_est,
        "crypto_sentiment": sent_est,
    }

    # ---- select weights for timeframe ----
    w_mom, w_vol, w_tech, w_sent = _select_weights(timeframe_hours)
    weights = {
        "crypto_momentum": w_mom,
        "crypto_volatility": w_vol,
        "crypto_technical": w_tech,
        "crypto_sentiment": w_sent,
    }

    # ---- log-linear pool ----
    model_order = ["crypto_momentum", "crypto_volatility", "crypto_technical", "crypto_sentiment"]
    probs = [estimates[name].probability for name in model_order]
    ws = [weights[name] for name in model_order]

    ensemble_prob = geometric_mean_odds(probs, ws)

    # ---- disagreement ----
    mean_p = sum(probs) / len(probs)
    variance = sum((p - mean_p) ** 2 for p in probs) / len(probs)
    disagreement = math.sqrt(variance)

    # ---- confidence ----
    # Count how many models have non-trivial data (confidence > 0.2)
    n_useful = sum(1 for est in estimates.values() if est.confidence > 0.2)
    confidence = _classify_confidence(n_useful, disagreement)

    # ---- gather key factors ----
    key_factors: list[str] = [
        f"ensemble={ensemble_prob:.3f} disagreement={disagreement:.3f}",
        f"timeframe={tf_label} asset={asset}",
    ]
    for name, est in estimates.items():
        if est.factors:
            key_factors.append(f"[{name}] {est.factors[0]}")

    logger.debug(
        "crypto_ensemble: asset=%s tf=%s prob=%.3f disagreement=%.3f",
        asset, tf_label, ensemble_prob, disagreement,
    )

    return {
        "ensemble_prob": clamp_prob(ensemble_prob),
        "ensemble_std": disagreement,
        "confidence": confidence,
        "model_estimates": estimates,
        "weights": weights,
        "key_factors": key_factors,
        "asset": asset,
        "timeframe_hours": timeframe_hours,
        "current_price": current_price,
        "target_price": target_price,
    }
