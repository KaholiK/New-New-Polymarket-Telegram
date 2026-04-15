"""Poll ESPN for final scores, update Elo + calibration."""

from __future__ import annotations

from apex.data.score_feed import GameResult, ScoreFeed
from apex.storage.db import Database
from apex.utils.logger import get_logger

logger = get_logger(__name__)


class ResultsTracker:
    def __init__(self, feed: ScoreFeed, db: Database) -> None:
        self.feed = feed
        self.db = db

    async def poll_finals(self, sports: list[str]) -> list[GameResult]:
        finals: list[GameResult] = []
        for sport in sports:
            rows = await self.feed.fetch_finals(sport)
            for r in rows:
                # Dedup: skip if already recorded
                existing = await self.db.get_result(r.event_id)
                if existing is not None:
                    continue
                await self.db.record_result(
                    {
                        "event_id": r.event_id,
                        "sport": r.sport,
                        "league": r.league,
                        "home_team": r.home_team,
                        "away_team": r.away_team,
                        "home_score": r.home_score,
                        "away_score": r.away_score,
                        "winner": r.winner,
                        "completed_at": r.completed_at.isoformat(),
                    }
                )
                finals.append(r)
        if finals:
            logger.info("results: ingested %d new finals", len(finals))
        return finals
