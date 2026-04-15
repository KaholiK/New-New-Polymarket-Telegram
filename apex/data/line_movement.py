"""Track odds changes over time, detect steam moves."""

from __future__ import annotations

import collections
from dataclasses import dataclass
from datetime import datetime, timedelta

from apex.core.models import OddsSnapshot
from apex.utils.time_utils import utc_now


@dataclass
class LineMove:
    event_id: str
    bookmaker: str
    side: str  # "home" or "away"
    delta_prob: float  # positive = side lengthened (prob down)
    delta_price: float
    ts: datetime


@dataclass
class SteamMove:
    event_id: str
    side: str
    books_moved: int
    total_delta_prob: float
    window_seconds: float
    detected_at: datetime


class LineMovementTracker:
    """Ring-buffer of recent snapshots per (event, book) for detecting steam moves."""

    def __init__(self, window: timedelta = timedelta(minutes=10)) -> None:
        self.window = window
        self._history: dict[tuple[str, str], collections.deque[OddsSnapshot]] = {}

    def ingest(self, snaps: list[OddsSnapshot]) -> list[LineMove]:
        moves: list[LineMove] = []
        for s in snaps:
            key = (s.event_id, s.bookmaker)
            buf = self._history.setdefault(key, collections.deque(maxlen=20))
            prev = buf[-1] if buf else None
            buf.append(s)
            if prev is None:
                continue
            # Diff prob (signed)
            dh = s.home_implied_prob - prev.home_implied_prob
            da = s.away_implied_prob - prev.away_implied_prob
            if abs(dh) >= 0.005 or abs(da) >= 0.005:
                if abs(dh) >= abs(da):
                    moves.append(
                        LineMove(
                            event_id=s.event_id,
                            bookmaker=s.bookmaker,
                            side="home",
                            delta_prob=dh,
                            delta_price=s.home_odds - prev.home_odds,
                            ts=s.fetched_at,
                        )
                    )
                else:
                    moves.append(
                        LineMove(
                            event_id=s.event_id,
                            bookmaker=s.bookmaker,
                            side="away",
                            delta_prob=da,
                            delta_price=s.away_odds - prev.away_odds,
                            ts=s.fetched_at,
                        )
                    )
        return moves

    def detect_steam(
        self,
        min_books: int = 3,
        min_delta_prob: float = 0.02,
        window_seconds: float = 300.0,
    ) -> list[SteamMove]:
        """3+ books moving the same direction within `window_seconds`."""
        now = utc_now()
        moves_per_event: dict[tuple[str, str], list[LineMove]] = {}
        for key, buf in self._history.items():
            event_id, book = key
            if len(buf) < 2:
                continue
            last = buf[-1]
            prev = buf[0]
            if (now - last.fetched_at).total_seconds() > window_seconds:
                continue
            dh = last.home_implied_prob - prev.home_implied_prob
            da = last.away_implied_prob - prev.away_implied_prob
            if abs(dh) >= abs(da) and abs(dh) >= min_delta_prob / 3.0:
                side = "home"
                moves_per_event.setdefault((event_id, side), []).append(
                    LineMove(event_id, book, side, dh, 0.0, last.fetched_at)
                )
            elif abs(da) >= min_delta_prob / 3.0:
                side = "away"
                moves_per_event.setdefault((event_id, side), []).append(
                    LineMove(event_id, book, side, da, 0.0, last.fetched_at)
                )

        steams: list[SteamMove] = []
        for (event_id, side), moves in moves_per_event.items():
            # Same-direction filter
            same_dir = [m for m in moves if (m.delta_prob > 0) == (moves[0].delta_prob > 0)]
            if len(same_dir) < min_books:
                continue
            total = sum(abs(m.delta_prob) for m in same_dir)
            if total < min_delta_prob:
                continue
            steams.append(
                SteamMove(
                    event_id=event_id,
                    side=side,
                    books_moved=len(same_dir),
                    total_delta_prob=total,
                    window_seconds=window_seconds,
                    detected_at=now,
                )
            )
        return steams
