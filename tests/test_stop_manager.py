"""Tests for stop manager — SL/TP/trailing."""

from __future__ import annotations

from apex.core.models import Position, Side
from apex.execution.stop_manager import StopManager


def _pos(market: str = "m1", side: Side = Side.YES, entry: float = 0.50, contracts: float = 10) -> Position:
    return Position(
        market_id=market,
        token_id="t",
        side=side,
        contracts=contracts,
        avg_entry_price=entry,
        cost_basis_usd=contracts * entry,
    )


def test_no_rule_no_fire():
    sm = StopManager()
    fires = sm.evaluate([_pos()], {"m1": 0.40})
    assert fires == []


def test_stop_loss_fires():
    sm = StopManager()
    sm.set_rule("m1", Side.YES, stop_loss_pct=0.10)
    fires = sm.evaluate([_pos()], {"m1": 0.44})  # 12% loss
    assert len(fires) == 1
    assert fires[0].reason == "stop_loss"


def test_take_profit_fires():
    sm = StopManager()
    sm.set_rule("m1", Side.YES, take_profit_pct=0.10)
    fires = sm.evaluate([_pos()], {"m1": 0.56})  # 12% gain
    assert len(fires) == 1
    assert fires[0].reason == "take_profit"


def test_no_fire_when_in_range():
    sm = StopManager()
    sm.set_rule("m1", Side.YES, stop_loss_pct=0.10, take_profit_pct=0.10)
    fires = sm.evaluate([_pos()], {"m1": 0.50})
    assert fires == []


def test_trailing_stop_fires_after_pullback():
    sm = StopManager()
    rule = sm.set_rule("m1", Side.YES, trailing_stop_pct=0.10)
    rule.high_water_mark = 0.60
    # Price dropped 15% from high
    fires = sm.evaluate([_pos()], {"m1": 0.51})
    assert any(f.reason == "trailing_stop" for f in fires)


def test_trailing_stop_updates_high_water():
    sm = StopManager()
    rule = sm.set_rule("m1", Side.YES, trailing_stop_pct=0.10)
    sm.evaluate([_pos()], {"m1": 0.60})
    assert rule.high_water_mark >= 0.60


def test_side_no_stop_loss():
    sm = StopManager()
    sm.set_rule("m1", Side.NO, stop_loss_pct=0.10)
    # Entry 0.50 NO, price went UP to 0.60 → we lost 20%
    fires = sm.evaluate([_pos(side=Side.NO)], {"m1": 0.60})
    assert any(f.reason == "stop_loss" for f in fires)


def test_remove_rule():
    sm = StopManager()
    sm.set_rule("m1", Side.YES, stop_loss_pct=0.10)
    sm.remove("m1", Side.YES)
    fires = sm.evaluate([_pos()], {"m1": 0.40})
    assert fires == []


def test_missing_price_safe():
    sm = StopManager()
    sm.set_rule("m1", Side.YES, stop_loss_pct=0.10)
    fires = sm.evaluate([_pos()], {})
    assert fires == []
