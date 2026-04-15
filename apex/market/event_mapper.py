"""Fuzzy-match Polymarket markets to ESPN scoreboard events."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from apex.core.models import Market, Sport
from apex.utils.parsing import fuzzy_ratio, normalize_text
from apex.utils.time_utils import to_utc


@dataclass
class EspnEvent:
    event_id: str
    sport: Sport
    league: str
    home_team: str
    away_team: str
    start_time: object  # datetime
    status: str = ""  # scheduled, in_progress, final, postponed


@dataclass
class MappingResult:
    event_id: str | None
    confidence: float
    reason: str = ""


def _team_match_score(market_team: str | None, event_team: str) -> float:
    """Symmetric fuzzy match score; higher is better."""
    if not market_team or not event_team:
        return 0.0
    # Exact on normalized
    if normalize_text(market_team) == normalize_text(event_team):
        return 1.0
    r = fuzzy_ratio(market_team, event_team)
    # Substring bonus
    nm = normalize_text(market_team)
    ne = normalize_text(event_team)
    if nm and ne and (nm in ne or ne in nm):
        r = max(r, 0.8)
    return r


def map_market_to_event(
    market: Market,
    candidates: list[EspnEvent],
    time_window_hours: float = 48.0,
) -> MappingResult:
    """Find best ESPN event match for a market.

    Criteria:
      - Must match sport
      - Must be within time_window_hours of market.end_date
      - Best combined team-match score across both home & away
      - Min confidence 0.70 to be considered a match (caller enforces)
    """
    if market.sport == Sport.UNKNOWN:
        return MappingResult(None, 0.0, "sport_unknown")
    if not market.home_team or not market.away_team:
        return MappingResult(None, 0.0, "teams_missing")

    best: MappingResult = MappingResult(None, 0.0, "no_candidates")
    for ev in candidates:
        if ev.sport != market.sport:
            continue
        if market.end_date and hasattr(ev.start_time, "astimezone"):
            delta = abs((to_utc(market.end_date) - to_utc(ev.start_time)).total_seconds())
            if delta > time_window_hours * 3600:
                continue
        if ev.status in ("final", "postponed"):
            continue
        # Match both orderings (home/away may differ between sources)
        direct = (
            _team_match_score(market.home_team, ev.home_team)
            + _team_match_score(market.away_team, ev.away_team)
        ) / 2.0
        swapped = (
            _team_match_score(market.home_team, ev.away_team)
            + _team_match_score(market.away_team, ev.home_team)
        ) / 2.0
        score = max(direct, swapped)
        if score > best.confidence:
            best = MappingResult(ev.event_id, score, "match" if score >= 0.7 else "weak_match")

    return best


def filter_candidates_by_time(
    candidates: list[EspnEvent], now, window: timedelta = timedelta(hours=48)
) -> list[EspnEvent]:
    out = []
    for ev in candidates:
        if not hasattr(ev.start_time, "astimezone"):
            continue
        delta = abs((to_utc(ev.start_time) - to_utc(now)).total_seconds())
        if delta <= window.total_seconds():
            out.append(ev)
    return out
