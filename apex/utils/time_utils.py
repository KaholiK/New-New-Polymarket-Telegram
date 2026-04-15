"""Timezone handling, freshness calculation, game-start proximity helpers."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta


def utc_now() -> datetime:
    return datetime.now(UTC)


def to_utc(dt: datetime) -> datetime:
    """Normalize any datetime to UTC."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def age_seconds(ts: datetime, now: datetime | None = None) -> float:
    """Seconds since ts. Negative if ts is in the future."""
    now = now or utc_now()
    return (to_utc(now) - to_utc(ts)).total_seconds()


def is_fresh(ts: datetime, max_age_seconds: float, now: datetime | None = None) -> bool:
    return age_seconds(ts, now) <= max_age_seconds


def seconds_until(ts: datetime, now: datetime | None = None) -> float:
    """Seconds until ts (negative if past)."""
    now = now or utc_now()
    return (to_utc(ts) - to_utc(now)).total_seconds()


def minutes_until(ts: datetime, now: datetime | None = None) -> float:
    return seconds_until(ts, now) / 60.0


def parse_iso(s: str) -> datetime | None:
    """Parse ISO-8601 including Z suffix; return None on failure."""
    if not s:
        return None
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return to_utc(datetime.fromisoformat(s))
    except (ValueError, TypeError):
        return None


def freshness_score(age_s: float, max_age_s: float) -> float:
    """Linear freshness score in [0, 1]. 0s old → 1.0, max_age_s → 0.0."""
    if max_age_s <= 0:
        return 1.0 if age_s <= 0 else 0.0
    return max(0.0, min(1.0, 1.0 - age_s / max_age_s))


def format_duration(seconds: float) -> str:
    """Human-readable duration: 65s → '1m 5s'."""
    if seconds < 0:
        return f"-{format_duration(-seconds)}"
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    minutes, sec = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m {sec}s"
    hours, minutes = divmod(minutes, 60)
    if hours < 24:
        return f"{hours}h {minutes}m"
    days, hours = divmod(hours, 24)
    return f"{days}d {hours}h"


def day_bucket_utc(dt: datetime | None = None) -> str:
    """ISO date string (UTC) for bucketing daily P&L etc."""
    dt = to_utc(dt or utc_now())
    return dt.strftime("%Y-%m-%d")


def within(ts: datetime, window: timedelta, now: datetime | None = None) -> bool:
    """True if ts is within `window` of now (past or future)."""
    now = now or utc_now()
    return abs((to_utc(now) - to_utc(ts)).total_seconds()) <= window.total_seconds()
