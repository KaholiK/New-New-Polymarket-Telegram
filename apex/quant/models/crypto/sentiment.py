"""Crypto sentiment model.

Inputs:
  - Fear & Greed index (0-100) from alternative.me
  - Optional recent news headlines (list of strings)

Contrarian logic:
  - Extreme Fear (<25)   → contrarian buy signal  → bullish for upside targets
  - Extreme Greed (>75)  → contrarian sell signal → bearish for upside targets
  - Neutral (25-75)      → weak directional signal based on index level

News headline scanning looks for positive/negative keywords and adjusts the
probability slightly. The sentiment model is intentionally lower-confidence than
momentum/volatility because crowd sentiment is a lagging and noisy signal.

model_name = "crypto_sentiment"
"""

from __future__ import annotations

from apex.core.models import ModelEstimate
from apex.utils.logger import get_logger
from apex.utils.math_utils import clamp_prob

logger = get_logger(__name__)

MODEL_NAME = "crypto_sentiment"

# Fear & Greed thresholds
EXTREME_FEAR_THRESHOLD = 25
EXTREME_GREED_THRESHOLD = 75
FEAR_THRESHOLD = 40
GREED_THRESHOLD = 60

# Positive / negative headline keywords (lower-cased)
_BULLISH_KEYWORDS = frozenset({
    "surge", "soar", "rally", "bullish", "breakout", "adoption",
    "partnership", "etf approved", "institutional", "buy", "upgrade",
    "record", "milestone", "growth", "launch", "listing",
})
_BEARISH_KEYWORDS = frozenset({
    "crash", "plunge", "bearish", "sell", "ban", "hack", "exploit",
    "fraud", "scam", "regulation", "fine", "lawsuit", "warning",
    "downgrade", "delist", "collapse", "liquidation", "fear",
})


def _score_headlines(headlines: list[str]) -> float:
    """Return a sentiment score in [-1, +1] from headline keyword scanning.

    +1 = very bullish, -1 = very bearish, 0 = neutral.
    """
    if not headlines:
        return 0.0

    total = 0.0
    for hl in headlines:
        hl_lower = hl.lower()
        bull_hits = sum(1 for kw in _BULLISH_KEYWORDS if kw in hl_lower)
        bear_hits = sum(1 for kw in _BEARISH_KEYWORDS if kw in hl_lower)
        total += bull_hits - bear_hits

    # Normalise: assume a headline scoring +/-3 saturates the signal
    normalised = total / max(len(headlines) * 3, 1)
    return max(-1.0, min(1.0, normalised))


def predict(
    fear_greed: int,
    current_price: float,
    target_price: float,
    headlines: list[str] | None = None,
) -> ModelEstimate:
    """Produce a sentiment-based ModelEstimate for reaching *target_price*.

    Parameters
    ----------
    fear_greed:
        Fear & Greed index value 0-100.  0 = extreme fear, 100 = extreme greed.
    current_price:
        Current mid-price of the asset.
    target_price:
        Price the Polymarket question resolves around.
    headlines:
        Optional list of recent news headline strings for additional context.

    Returns
    -------
    ModelEstimate
        Probability of YES (price reaches target), with confidence reflecting
        that sentiment is a soft signal.
    """
    # ---- validate / graceful fallback ----
    if current_price <= 0:
        logger.warning("crypto_sentiment: bad current_price %s, returning neutral", current_price)
        return ModelEstimate(
            model_name=MODEL_NAME,
            probability=0.5,
            uncertainty=0.20,
            confidence=0.1,
            factors=["no_data"],
        )

    upside = target_price >= current_price
    fg = max(0, min(100, int(fear_greed)))
    factors: list[str] = [f"fear_greed={fg}", f"target={'above' if upside else 'below'}_current"]

    # ---- Fear & Greed contrarian signal ----
    # The contrarian effect: extreme readings mean the crowd is all-in one direction,
    # which historically precedes reversals.
    fg_signal = 0.0
    if fg < EXTREME_FEAR_THRESHOLD:
        # Extreme fear → contrarian bullish (expect bounce)
        intensity = (EXTREME_FEAR_THRESHOLD - fg) / EXTREME_FEAR_THRESHOLD
        fg_signal = 0.15 * intensity
        factors.append(f"extreme_fear({fg})_contrarian_bullish")
    elif fg > EXTREME_GREED_THRESHOLD:
        # Extreme greed → contrarian bearish (expect pullback)
        intensity = (fg - EXTREME_GREED_THRESHOLD) / (100 - EXTREME_GREED_THRESHOLD)
        fg_signal = -0.15 * intensity
        factors.append(f"extreme_greed({fg})_contrarian_bearish")
    elif fg < FEAR_THRESHOLD:
        # Mild fear — slight bullish bias
        intensity = (FEAR_THRESHOLD - fg) / (FEAR_THRESHOLD - EXTREME_FEAR_THRESHOLD)
        fg_signal = 0.06 * intensity
        factors.append(f"fear({fg})_mild_bullish")
    elif fg > GREED_THRESHOLD:
        # Mild greed — slight bearish bias
        intensity = (fg - GREED_THRESHOLD) / (EXTREME_GREED_THRESHOLD - GREED_THRESHOLD)
        fg_signal = -0.06 * intensity
        factors.append(f"greed({fg})_mild_bearish")
    else:
        factors.append(f"neutral_fg({fg})")

    # ---- News headline signal ----
    headline_score = _score_headlines(headlines or [])
    headline_signal = headline_score * 0.08  # max ±0.08 contribution
    if headlines:
        polarity = "positive" if headline_score > 0.1 else ("negative" if headline_score < -0.1 else "neutral")
        factors.append(f"news_sentiment={polarity}({headline_score:.2f})")

    # ---- combine signals ----
    total_signal = fg_signal + headline_signal

    # For downside target, bullish sentiment is bearish for probability of reaching it
    if not upside:
        total_signal = -total_signal

    prob = clamp_prob(0.5 + total_signal)

    # Sentiment is inherently noisy → modest confidence and higher uncertainty
    has_headlines = bool(headlines)
    confidence = 0.45 if has_headlines else 0.35
    uncertainty = 0.12 if has_headlines else 0.15

    return ModelEstimate(
        model_name=MODEL_NAME,
        probability=prob,
        uncertainty=uncertainty,
        confidence=confidence,
        factors=factors,
    )
