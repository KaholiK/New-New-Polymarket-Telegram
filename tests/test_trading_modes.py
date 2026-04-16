"""Tests for trading modes + performance tracker + category detection."""

from __future__ import annotations

from apex.core.performance_tracker import PerformanceTracker
from apex.core.trading_modes import (
    TradingMode,
    format_modes_list,
    get_mode_rules,
    passes_mode_gate,
)
from apex.market.categories import Category, detect_category, is_crypto_category, is_sports_category

# ---- Trading modes ----

def test_all_9_modes_exist():
    assert len(TradingMode) == 9


def test_safe_mode_strictest():
    rules = get_mode_rules(TradingMode.SAFE)
    assert rules.min_claude_score == 9
    assert rules.min_edge_zscore == 3.0


def test_aggressive_mode_loosest():
    rules = get_mode_rules(TradingMode.AGGRESSIVE)
    assert rules.min_claude_score == 6
    assert rules.min_edge_zscore == 1.3


def test_passes_safe_mode():
    ok, reasons = passes_mode_gate(TradingMode.SAFE, "high", 3.5, 9)
    assert ok
    assert not reasons


def test_rejects_safe_mode_low_score():
    ok, reasons = passes_mode_gate(TradingMode.SAFE, "high", 3.5, 7)
    assert not ok
    assert any("claude_score" in r for r in reasons)


def test_rejects_safe_mode_low_confidence():
    ok, reasons = passes_mode_gate(TradingMode.SAFE, "medium", 3.5, 9)
    assert not ok


def test_high_risk_reward_price_gate():
    ok, _ = passes_mode_gate(TradingMode.HIGH_RISK_REWARD, "medium", 2.0, 8, market_price=0.10)
    assert ok
    ok2, reasons2 = passes_mode_gate(TradingMode.HIGH_RISK_REWARD, "medium", 2.0, 8, market_price=0.50)
    assert not ok2
    assert any("price" in r for r in reasons2)


def test_format_modes_list():
    text = format_modes_list(TradingMode.BALANCED)
    assert "BALANCED" in text
    assert "SAFE" in text
    assert "👉" in text  # active mode marker


# ---- Performance tracker ----

def test_record_and_win_rate():
    pt = PerformanceTracker()
    for _ in range(7):
        pt.record("balanced", "NBA", "24h", won=True, pnl=1.0)
    for _ in range(3):
        pt.record("balanced", "NBA", "24h", won=False, pnl=-1.0)
    s = pt.mode_summary()
    assert s["balanced"]["trades"] == 10
    assert "70" in s["balanced"]["win_rate"]  # 70%


def test_auto_downgrade():
    pt = PerformanceTracker()
    # 30 losses in a row → should trigger downgrade
    for _ in range(35):
        pt.record("balanced", "NBA", "24h", won=False, pnl=-1.0)
    new = pt.check_auto_downgrade(TradingMode.BALANCED)
    assert new == TradingMode.CONSERVATIVE


def test_no_downgrade_when_winning():
    pt = PerformanceTracker()
    for _ in range(35):
        pt.record("balanced", "NBA", "24h", won=True, pnl=1.0)
    assert pt.check_auto_downgrade(TradingMode.BALANCED) is None


def test_best_setups():
    pt = PerformanceTracker()
    for _ in range(15):
        pt.record("safe", "NHL", "weekly", won=True, pnl=2.0)
    for _ in range(15):
        pt.record("aggressive", "NBA", "1h", won=False, pnl=-1.0)
    best = pt.best_setups(1)
    assert len(best) >= 1
    assert "NHL" in best[0][0]


# ---- Category detection ----

def test_detect_nba():
    assert detect_category("Will the Lakers win the NBA Finals?") == Category.NBA


def test_detect_crypto():
    assert detect_category("Will Bitcoin hit $100,000?") == Category.CRYPTO


def test_detect_f1():
    assert detect_category("Will Max Verstappen win the F1 Championship?") == Category.F1


def test_detect_tennis():
    assert detect_category("Will Djokovic win Wimbledon?") == Category.TENNIS


def test_detect_politics():
    assert detect_category("Will Trump win the 2028 presidential election?") == Category.POLITICS


def test_detect_epl():
    assert detect_category("Will Arsenal win the Premier League?") == Category.EPL


def test_is_sports():
    assert is_sports_category(Category.NBA)
    assert is_sports_category(Category.F1)
    assert not is_sports_category(Category.CRYPTO)
    assert not is_sports_category(Category.POLITICS)


def test_is_crypto():
    assert is_crypto_category(Category.CRYPTO)
    assert not is_crypto_category(Category.NBA)


def test_unknown_text():
    cat = detect_category("What is the meaning of life?")
    assert cat == Category.OTHER
