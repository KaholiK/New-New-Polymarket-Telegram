"""Halt trading when any critical source exceeds freshness threshold."""

from __future__ import annotations

from apex.config import get_settings
from apex.data.source_health import SourceHealthTracker


def stale_sources(tracker: SourceHealthTracker) -> list[str]:
    """Return names of sources that are stale per config thresholds."""
    s = get_settings()
    limits = {
        "polymarket": s.polymarket_max_age,
        "odds": s.odds_max_age,
        "injuries": s.injury_max_age,
        "news": s.news_max_age,
    }
    stale: list[str] = []
    for name, limit in limits.items():
        age = tracker.age(name)
        if age == float("inf"):
            # never polled — if critical and we've been running, it's stale
            if name in ("polymarket", "odds"):
                stale.append(name)
        elif age > limit:
            stale.append(name)
    return stale
