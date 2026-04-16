"""Trading modes — 9 risk/reward profiles the operator selects via /mode.

Each mode defines thresholds for edge, confidence, Claude score, and trade frequency.
The meta-decision engine consults the active mode before approving any trade.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from apex.utils.logger import get_logger

logger = get_logger(__name__)


class TradingMode(str, Enum):
    SAFE = "safe"
    CONSERVATIVE = "conservative"
    BALANCED = "balanced"
    SCALPING = "scalping"
    SWING = "swing"
    LONGTERM = "longterm"
    AGGRESSIVE = "aggressive"
    HIGH_RISK_REWARD = "high_risk_reward"
    MED_RISK_LOW_REWARD = "med_risk_low_reward"


@dataclass(frozen=True)
class ModeRules:
    name: str
    min_confidence: str  # "high", "medium", "low"
    min_edge_zscore: float
    min_claude_score: int  # 1-10
    description: str
    expected_trades_per_day: str
    target_win_rate: str
    max_claude_calls_per_day: int = 200
    # Price range filter for HIGH_RISK_REWARD / MED_RISK_LOW_REWARD
    price_range: tuple[float, float] | None = None
    # Timeframe preference
    preferred_timeframes: list[str] = field(default_factory=list)
    # Warning shown on activation
    warning: str = ""


MODE_RULES: dict[TradingMode, ModeRules] = {
    TradingMode.SAFE: ModeRules(
        name="SAFE",
        min_confidence="high",
        min_edge_zscore=3.0,
        min_claude_score=9,
        description="Only the absolute best setups. 3+ models must agree within 2%.",
        expected_trades_per_day="0-2",
        target_win_rate="65-72%",
        max_claude_calls_per_day=999,
    ),
    TradingMode.CONSERVATIVE: ModeRules(
        name="CONSERVATIVE",
        min_confidence="high",
        min_edge_zscore=2.5,
        min_claude_score=8,
        description="Strong setups only. High confidence required.",
        expected_trades_per_day="1-3",
        target_win_rate="60-68%",
    ),
    TradingMode.BALANCED: ModeRules(
        name="BALANCED",
        min_confidence="medium",
        min_edge_zscore=1.8,
        min_claude_score=7,
        description="Default mode. Good balance of volume and quality.",
        expected_trades_per_day="4-7",
        target_win_rate="55-62%",
    ),
    TradingMode.SCALPING: ModeRules(
        name="SCALPING",
        min_confidence="medium",
        min_edge_zscore=1.5,
        min_claude_score=6,
        description="Short timeframe focus (1h-4h crypto, live sports). Tight stops.",
        expected_trades_per_day="8-15",
        target_win_rate="52-58%",
        preferred_timeframes=["1h", "4h", "12h"],
    ),
    TradingMode.SWING: ModeRules(
        name="SWING",
        min_confidence="medium",
        min_edge_zscore=2.0,
        min_claude_score=7,
        description="Multi-day holds. Daily/weekly markets only.",
        expected_trades_per_day="2-5",
        target_win_rate="58-65%",
        preferred_timeframes=["24h", "3d", "weekly"],
    ),
    TradingMode.LONGTERM: ModeRules(
        name="LONGTERM",
        min_confidence="high",
        min_edge_zscore=2.0,
        min_claude_score=8,
        description="Monthly/quarterly/EOY markets. Patient capital.",
        expected_trades_per_day="0.1-0.3 (1-2/week)",
        target_win_rate="60-70%",
        preferred_timeframes=["monthly", "quarterly", "yearly"],
    ),
    TradingMode.AGGRESSIVE: ModeRules(
        name="AGGRESSIVE",
        min_confidence="medium",
        min_edge_zscore=1.3,
        min_claude_score=6,
        description="Higher volume, higher risk. More losing trades expected.",
        expected_trades_per_day="12-20",
        target_win_rate="50-56%",
        max_claude_calls_per_day=50,
        warning="WARNING: This mode will produce more losing trades. Only use when bankroll allows for variance.",
    ),
    TradingMode.HIGH_RISK_REWARD: ModeRules(
        name="HIGH_RISK_REWARD",
        min_confidence="medium",
        min_edge_zscore=1.5,
        min_claude_score=7,
        description="Only markets at <20¢ or >80¢ for 5x+ payout potential.",
        expected_trades_per_day="1-3",
        target_win_rate="40-50% (high payout multiplier)",
        price_range=(0.0, 0.20),
    ),
    TradingMode.MED_RISK_LOW_REWARD: ModeRules(
        name="MED_RISK_LOW_REWARD",
        min_confidence="high",
        min_edge_zscore=1.5,
        min_claude_score=7,
        description="Only 40-60¢ range markets. High confidence, lower volatility.",
        expected_trades_per_day="3-6",
        target_win_rate="60-65%",
        price_range=(0.40, 0.60),
    ),
}


def get_mode_rules(mode: TradingMode) -> ModeRules:
    return MODE_RULES[mode]


def passes_mode_gate(
    mode: TradingMode,
    confidence: str,
    edge_zscore: float,
    claude_score: int,
    market_price: float = 0.5,
) -> tuple[bool, list[str]]:
    """Check whether a candidate passes the active mode's gates.

    Returns (passes, rejection_reasons).
    """
    rules = MODE_RULES[mode]
    reasons: list[str] = []

    # Confidence gate
    conf_rank = {"high": 3, "medium": 2, "low": 1, "no_opinion": 0}
    required = conf_rank.get(rules.min_confidence, 2)
    actual = conf_rank.get(confidence, 0)
    if actual < required:
        reasons.append(f"confidence_{confidence}_below_{rules.min_confidence}")

    # Edge z-score gate
    if abs(edge_zscore) < rules.min_edge_zscore:
        reasons.append(f"edge_zscore_{edge_zscore:.2f}_below_{rules.min_edge_zscore}")

    # Claude score gate
    if claude_score < rules.min_claude_score:
        reasons.append(f"claude_score_{claude_score}_below_{rules.min_claude_score}")

    # Price range gate (for HIGH_RISK_REWARD / MED_RISK_LOW_REWARD)
    if rules.price_range:
        lo, hi = rules.price_range
        # For HIGH_RISK_REWARD, price must be < lo OR > (1-lo) for either side to be cheap
        if mode == TradingMode.HIGH_RISK_REWARD:
            if not (market_price <= hi or market_price >= (1.0 - hi)):
                reasons.append(f"price_{market_price:.2f}_not_in_extreme_range")
        else:
            if not (lo <= market_price <= hi):
                reasons.append(f"price_{market_price:.2f}_outside_{lo}-{hi}")

    return (len(reasons) == 0, reasons)


def format_modes_list(active_mode: TradingMode) -> str:
    """Format all modes for /modes command."""
    lines = ["<b>Trading Modes</b>"]
    for mode, rules in MODE_RULES.items():
        marker = "👉 " if mode == active_mode else "  "
        lines.append(
            f"{marker}<b>{rules.name}</b>: {rules.description}\n"
            f"    Edge≥{rules.min_edge_zscore} · Claude≥{rules.min_claude_score}/10 · "
            f"~{rules.expected_trades_per_day}/day · WR {rules.target_win_rate}"
        )
    return "\n".join(lines)
