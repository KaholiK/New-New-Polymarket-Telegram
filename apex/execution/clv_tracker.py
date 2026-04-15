"""Closing Line Value tracker — real measure of sustainable edge."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from apex.core.models import Side
from apex.storage.db import Database
from apex.utils.time_utils import utc_now


@dataclass
class CLVRecord:
    trade_id: str
    market_id: str
    side: Side
    entry_price: float
    closing_price: float
    strategy: str = ""
    sport: str = ""
    recorded_at: datetime = field(default_factory=utc_now)

    @property
    def clv(self) -> float:
        """Positive CLV = we got a better price than the close (good)."""
        if self.side == Side.YES:
            return self.closing_price - self.entry_price
        return self.entry_price - self.closing_price


class CLVTracker:
    def __init__(self, db: Database | None = None) -> None:
        self.db = db
        self._records: list[CLVRecord] = []

    async def record(
        self,
        trade_id: str,
        market_id: str,
        side: Side,
        entry_price: float,
        closing_price: float,
        strategy: str = "",
        sport: str = "",
    ) -> CLVRecord:
        rec = CLVRecord(
            trade_id=trade_id,
            market_id=market_id,
            side=side,
            entry_price=entry_price,
            closing_price=closing_price,
            strategy=strategy,
            sport=sport,
        )
        self._records.append(rec)
        if self.db is not None:
            await self.db.record_clv(
                {
                    "trade_id": trade_id,
                    "market_id": market_id,
                    "side": side.value,
                    "entry_price": entry_price,
                    "closing_price": closing_price,
                    "clv": rec.clv,
                    "strategy": strategy,
                    "sport": sport,
                    "recorded_at": rec.recorded_at.isoformat(),
                }
            )
        return rec

    def rolling_clv(self, strategy: str | None = None, n: int = 20) -> float:
        """Average CLV over last n records, optionally filtered by strategy."""
        filt = [r for r in self._records if strategy is None or r.strategy == strategy]
        if not filt:
            return 0.0
        recent = filt[-n:]
        return sum(r.clv for r in recent) / len(recent)

    def count(self, strategy: str | None = None) -> int:
        return len([r for r in self._records if strategy is None or r.strategy == strategy])

    def summary(self) -> dict:
        if not self._records:
            return {"count": 0, "avg_clv": 0.0}
        avg = sum(r.clv for r in self._records) / len(self._records)
        return {
            "count": len(self._records),
            "avg_clv": round(avg, 4),
            "positive_rate": round(sum(1 for r in self._records if r.clv > 0) / len(self._records), 3),
        }
