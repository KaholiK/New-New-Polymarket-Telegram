"""Stop-loss / take-profit / trailing-stop rules."""

from __future__ import annotations

from dataclasses import dataclass

from apex.core.models import Position, Side


@dataclass
class StopRule:
    market_id: str
    side: Side
    stop_loss_pct: float | None = None
    take_profit_pct: float | None = None
    trailing_stop_pct: float | None = None
    high_water_mark: float = 0.0

    @property
    def active(self) -> bool:
        return any(x is not None for x in (self.stop_loss_pct, self.take_profit_pct, self.trailing_stop_pct))


@dataclass
class StopFire:
    market_id: str
    reason: str  # stop_loss | take_profit | trailing_stop
    current_price: float
    entry_price: float


class StopManager:
    def __init__(self) -> None:
        self._rules: dict[str, StopRule] = {}

    def key(self, market_id: str, side: Side) -> str:
        return f"{market_id}:{side.value}"

    def set_rule(
        self,
        market_id: str,
        side: Side,
        stop_loss_pct: float | None = None,
        take_profit_pct: float | None = None,
        trailing_stop_pct: float | None = None,
    ) -> StopRule:
        rule = StopRule(
            market_id=market_id,
            side=side,
            stop_loss_pct=stop_loss_pct,
            take_profit_pct=take_profit_pct,
            trailing_stop_pct=trailing_stop_pct,
        )
        self._rules[self.key(market_id, side)] = rule
        return rule

    def remove(self, market_id: str, side: Side) -> None:
        self._rules.pop(self.key(market_id, side), None)

    def evaluate(self, positions: list[Position], prices: dict[str, float]) -> list[StopFire]:
        """Walk each position and check against its rule. Returns fires to trigger."""
        fires: list[StopFire] = []
        for pos in positions:
            key = self.key(pos.market_id, pos.side)
            rule = self._rules.get(key)
            if rule is None or not rule.active:
                continue
            current = prices.get(pos.market_id)
            if current is None:
                continue
            entry = pos.avg_entry_price
            if entry <= 0:
                continue

            # P&L direction depends on side
            if pos.side == Side.YES:
                change = (current - entry) / entry
                # Update high-water for trailing
                if rule.trailing_stop_pct is not None and current > rule.high_water_mark:
                    rule.high_water_mark = current
            else:
                change = (entry - current) / entry
                if rule.trailing_stop_pct is not None and current < rule.high_water_mark or rule.high_water_mark == 0:
                    rule.high_water_mark = current

            # Take-profit
            if rule.take_profit_pct is not None and change >= rule.take_profit_pct:
                fires.append(StopFire(pos.market_id, "take_profit", current, entry))
                continue
            # Stop-loss
            if rule.stop_loss_pct is not None and change <= -rule.stop_loss_pct:
                fires.append(StopFire(pos.market_id, "stop_loss", current, entry))
                continue
            # Trailing stop
            if rule.trailing_stop_pct is not None and rule.high_water_mark > 0:
                if pos.side == Side.YES:
                    retrace = (rule.high_water_mark - current) / rule.high_water_mark
                else:
                    retrace = (current - rule.high_water_mark) / max(0.001, rule.high_water_mark)
                if retrace >= rule.trailing_stop_pct:
                    fires.append(StopFire(pos.market_id, "trailing_stop", current, entry))

        return fires

    def rules(self) -> dict[str, StopRule]:
        return dict(self._rules)
