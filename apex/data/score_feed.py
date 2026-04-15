"""ESPN scoreboard — live scores + final results."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

import httpx

from apex.core.models import Sport
from apex.market.event_mapper import EspnEvent
from apex.utils.logger import get_logger
from apex.utils.retry import async_retry
from apex.utils.time_utils import parse_iso, utc_now

logger = get_logger(__name__)

SCOREBOARD_URL = "https://site.api.espn.com/apis/site/v2/sports/{sport}/{league}/scoreboard"

SPORT_LEAGUE_MAP = {
    "NBA": ("basketball", "nba"),
    "NFL": ("football", "nfl"),
    "MLB": ("baseball", "mlb"),
    "NHL": ("hockey", "nhl"),
}


@dataclass
class GameResult:
    event_id: str
    sport: str
    league: str
    home_team: str
    away_team: str
    home_score: int
    away_score: int
    winner: str
    status: str
    completed_at: datetime


class ScoreFeed:
    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client or httpx.AsyncClient(timeout=15.0, headers={"User-Agent": "APEX/0.1"})
        self._owns_client = client is None

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    @async_retry(attempts=3, base_delay=1.0, max_delay=8.0, exceptions=(httpx.HTTPError,))
    async def _get(self, url: str) -> Any:
        r = await self._client.get(url)
        r.raise_for_status()
        return r.json()

    async def fetch_scoreboard(self, sport: str) -> list[EspnEvent]:
        sl = SPORT_LEAGUE_MAP.get(sport.upper())
        if not sl:
            return []
        url = SCOREBOARD_URL.format(sport=sl[0], league=sl[1])
        try:
            data = await self._get(url)
        except httpx.HTTPError as exc:
            logger.warning("scoreboard fetch failed for %s: %s", sport, exc)
            return []
        return parse_events(data, sport, sl[1].upper())

    async def fetch_finals(self, sport: str) -> list[GameResult]:
        sl = SPORT_LEAGUE_MAP.get(sport.upper())
        if not sl:
            return []
        url = SCOREBOARD_URL.format(sport=sl[0], league=sl[1])
        try:
            data = await self._get(url)
        except httpx.HTTPError as exc:
            logger.warning("finals fetch failed for %s: %s", sport, exc)
            return []
        return parse_finals(data, sport, sl[1].upper())


def parse_events(raw: Any, sport: str, league: str) -> list[EspnEvent]:
    try:
        sport_enum = Sport(sport.upper())
    except ValueError:
        sport_enum = Sport.UNKNOWN
    out: list[EspnEvent] = []
    if not isinstance(raw, dict):
        return out
    events = raw.get("events") or []
    if not isinstance(events, list):
        return out
    for ev in events:
        if not isinstance(ev, dict):
            continue
        event_id = str(ev.get("id") or "")
        start = parse_iso(str(ev.get("date") or "")) or utc_now()
        comps = ev.get("competitions") or []
        if not comps:
            continue
        comp = comps[0]
        if not isinstance(comp, dict):
            continue
        status_obj = comp.get("status") or {}
        state = ""
        if isinstance(status_obj, dict):
            typ = status_obj.get("type") or {}
            if isinstance(typ, dict):
                state = str(typ.get("state") or "").lower()
        teams = comp.get("competitors") or []
        home = away = ""
        for t in teams:
            if not isinstance(t, dict):
                continue
            tm = t.get("team") or {}
            name = tm.get("displayName") if isinstance(tm, dict) else ""
            if t.get("homeAway") == "home":
                home = str(name or "")
            elif t.get("homeAway") == "away":
                away = str(name or "")
        if not event_id or not home or not away:
            continue
        out.append(
            EspnEvent(
                event_id=event_id,
                sport=sport_enum,
                league=league,
                home_team=home,
                away_team=away,
                start_time=start,
                status=map_status(state),
            )
        )
    return out


def parse_finals(raw: Any, sport: str, league: str) -> list[GameResult]:
    out: list[GameResult] = []
    if not isinstance(raw, dict):
        return out
    events = raw.get("events") or []
    if not isinstance(events, list):
        return out
    for ev in events:
        if not isinstance(ev, dict):
            continue
        event_id = str(ev.get("id") or "")
        comps = ev.get("competitions") or []
        if not comps:
            continue
        comp = comps[0]
        if not isinstance(comp, dict):
            continue
        status_obj = comp.get("status") or {}
        state = ""
        if isinstance(status_obj, dict):
            typ = status_obj.get("type") or {}
            if isinstance(typ, dict):
                state = str(typ.get("state") or "").lower()
        if state != "post":
            continue
        teams = comp.get("competitors") or []
        home = away = ""
        home_score = away_score = 0
        for t in teams:
            if not isinstance(t, dict):
                continue
            tm = t.get("team") or {}
            name = tm.get("displayName") if isinstance(tm, dict) else ""
            try:
                score = int(float(t.get("score") or 0))
            except (ValueError, TypeError):
                score = 0
            if t.get("homeAway") == "home":
                home = str(name or "")
                home_score = score
            elif t.get("homeAway") == "away":
                away = str(name or "")
                away_score = score
        if not event_id or not home or not away:
            continue
        winner = home if home_score > away_score else (away if away_score > home_score else "")
        out.append(
            GameResult(
                event_id=event_id,
                sport=sport,
                league=league,
                home_team=home,
                away_team=away,
                home_score=home_score,
                away_score=away_score,
                winner=winner,
                status="final",
                completed_at=utc_now(),
            )
        )
    return out


def map_status(state: str) -> str:
    if state == "pre":
        return "scheduled"
    if state == "in":
        return "in_progress"
    if state == "post":
        return "final"
    return state or "scheduled"
