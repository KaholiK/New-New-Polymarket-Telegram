"""Store every odds snapshot in SQLite for CLV + backtesting."""

from __future__ import annotations

from apex.core.models import OddsSnapshot
from apex.storage.db import Database


class HistoricalOddsStore:
    def __init__(self, db: Database) -> None:
        self.db = db

    async def record(self, snap: OddsSnapshot) -> None:
        await self.db.record_odds(
            {
                "event_id": snap.event_id,
                "source": snap.bookmaker,
                "home_odds": snap.home_odds,
                "away_odds": snap.away_odds,
                "home_implied_prob": snap.home_implied_prob,
                "away_implied_prob": snap.away_implied_prob,
                "fetched_at": snap.fetched_at.isoformat(),
            }
        )

    async def record_batch(self, snaps: list[OddsSnapshot]) -> int:
        count = 0
        for s in snaps:
            await self.record(s)
            count += 1
        return count
