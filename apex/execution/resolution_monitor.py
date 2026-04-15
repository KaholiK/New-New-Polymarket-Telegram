"""Poll Gamma for market resolution (YES/NO/INVALID), settle P&L."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from apex.core.models import Side, Trade, TradeStatus
from apex.core.state import BotState
from apex.market.polymarket_client import PolymarketClient
from apex.storage.db import Database
from apex.utils.logger import get_logger
from apex.utils.time_utils import utc_now

logger = get_logger(__name__)


@dataclass
class ResolutionOutcome:
    market_id: str
    resolution: str  # "YES", "NO", "INVALID"
    settled_at: Any = None


def parse_resolution(market_data: dict[str, Any]) -> ResolutionOutcome | None:
    """Determine YES/NO/INVALID from a Gamma market dict.

    Heuristics:
      - closed=True AND outcomePrices contains one near 1.00 and one near 0.00.
      - If both near 0.5 after close → INVALID.
    """
    import json

    if not isinstance(market_data, dict):
        return None
    condition_id = str(market_data.get("conditionId") or "")
    if not condition_id:
        return None
    closed = market_data.get("closed")
    if not closed:
        return None
    raw_prices = market_data.get("outcomePrices")
    if isinstance(raw_prices, str):
        try:
            prices = json.loads(raw_prices)
        except (ValueError, TypeError):
            return None
    elif isinstance(raw_prices, list):
        prices = raw_prices
    else:
        return None
    try:
        yes_final = float(prices[0])
        no_final = float(prices[1])
    except (ValueError, TypeError, IndexError):
        return None
    if yes_final > 0.95 and no_final < 0.05:
        return ResolutionOutcome(market_id=condition_id, resolution="YES", settled_at=utc_now())
    if no_final > 0.95 and yes_final < 0.05:
        return ResolutionOutcome(market_id=condition_id, resolution="NO", settled_at=utc_now())
    # INVALID: Polymarket reports both sides ≈0.5 when a market is voided.
    # Use a tight tolerance so near-close outcomes like (0.6, 0.4) do not trip.
    if abs(yes_final - 0.5) < 0.02 and abs(no_final - 0.5) < 0.02:
        return ResolutionOutcome(market_id=condition_id, resolution="INVALID", settled_at=utc_now())
    return None


class ResolutionMonitor:
    def __init__(
        self,
        client: PolymarketClient,
        db: Database,
        state: BotState,
    ) -> None:
        self.client = client
        self.db = db
        self.state = state
        self._resolved: set[str] = set()

    async def check_and_settle(self, open_trades: list[Trade]) -> list[tuple[Trade, ResolutionOutcome]]:
        """For each open trade, poll Gamma for its market and settle if resolved."""
        settled: list[tuple[Trade, ResolutionOutcome]] = []
        for t in open_trades:
            if t.market_id in self._resolved:
                continue
            data = await self.client.get_market(t.market_id)
            if not data:
                continue
            outcome = parse_resolution(data)
            if outcome is None:
                continue
            self._resolved.add(outcome.market_id)
            await self._settle_trade(t, outcome)
            settled.append((t, outcome))
        return settled

    async def _settle_trade(self, trade: Trade, outcome: ResolutionOutcome) -> None:
        """Apply P&L and update trade status."""
        won: bool | None = None
        payout = 0.0
        if outcome.resolution == "INVALID":
            # Refund cost basis
            payout = trade.size_usd
            trade.status = TradeStatus.RESOLVED_INVALID
            trade.pnl = 0.0
        elif (trade.side == Side.YES and outcome.resolution == "YES") or (
            trade.side == Side.NO and outcome.resolution == "NO"
        ):
            payout = trade.filled_qty * 1.0  # $1 per winning contract
            trade.status = TradeStatus.RESOLVED_WIN
            trade.pnl = payout - trade.size_usd
            won = True
        else:
            # Position worthless
            payout = 0.0
            trade.status = TradeStatus.RESOLVED_LOSS
            trade.pnl = -trade.size_usd
            won = False

        trade.resolved_at = outcome.settled_at

        await self.state.credit(payout, reason=f"settle:{outcome.resolution}")
        await self.state.apply_realized_pnl(trade.pnl, won=won)
        await self.db.update_trade(
            trade.id,
            status=trade.status.value,
            pnl=trade.pnl,
            resolved_at=trade.resolved_at.isoformat() if trade.resolved_at else None,
        )
        logger.info(
            "settled trade %s: outcome=%s pnl=$%.2f",
            trade.id,
            outcome.resolution,
            trade.pnl,
        )
