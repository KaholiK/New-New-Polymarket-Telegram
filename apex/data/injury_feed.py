"""ESPN injury endpoint polling."""

from __future__ import annotations

from typing import Any

import httpx

from apex.core.models import InjuryNote
from apex.utils.logger import get_logger
from apex.utils.retry import async_retry
from apex.utils.time_utils import utc_now

logger = get_logger(__name__)

# Correct ESPN injury endpoint
INJURY_URL_FMT = "https://site.api.espn.com/apis/site/v2/sports/{sport}/{league}/injuries"

SPORT_LEAGUE_MAP = {
    "NBA": ("basketball", "nba"),
    "NFL": ("football", "nfl"),
    "MLB": ("baseball", "mlb"),
    "NHL": ("hockey", "nhl"),
}


class InjuryFeed:
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

    async def fetch_injuries(self, sport: str) -> list[InjuryNote]:
        sl = SPORT_LEAGUE_MAP.get(sport.upper())
        if not sl:
            return []
        url = INJURY_URL_FMT.format(sport=sl[0], league=sl[1])
        try:
            data = await self._get(url)
        except httpx.HTTPError as exc:
            logger.warning("injuries fetch failed for %s: %s", sport, exc)
            return []
        return parse_injuries(data)


def parse_injuries(raw: Any) -> list[InjuryNote]:
    out: list[InjuryNote] = []
    if not isinstance(raw, dict):
        return out
    teams = raw.get("injuries") or raw.get("teams") or []
    if not isinstance(teams, list):
        return out
    for team_block in teams:
        if not isinstance(team_block, dict):
            continue
        team_name = ""
        tm = team_block.get("team") or team_block.get("displayName")
        if isinstance(tm, dict):
            team_name = str(tm.get("displayName") or tm.get("name") or "")
        elif isinstance(tm, str):
            team_name = tm
        items = team_block.get("injuries") or []
        if not isinstance(items, list):
            continue
        for it in items:
            if not isinstance(it, dict):
                continue
            athlete = it.get("athlete") or {}
            player = str(athlete.get("displayName") or athlete.get("fullName") or "") if isinstance(athlete, dict) else ""
            position = ""
            if isinstance(athlete, dict):
                pos = athlete.get("position")
                if isinstance(pos, dict):
                    position = str(pos.get("abbreviation") or pos.get("name") or "")
                elif isinstance(pos, str):
                    position = pos
            status = str(it.get("status") or it.get("type") or "").upper()
            desc = str(it.get("shortComment") or it.get("longComment") or "")
            out.append(
                InjuryNote(
                    event_id="",
                    team=team_name,
                    player=player,
                    position=position,
                    status=normalize_injury_status(status),
                    description=desc,
                    fetched_at=utc_now(),
                )
            )
    return out


def normalize_injury_status(raw: str) -> str:
    if not raw:
        return ""
    up = raw.upper()
    if "OUT" in up:
        return "OUT"
    if "DOUBTFUL" in up:
        return "DOUBTFUL"
    if "QUESTIONABLE" in up:
        return "QUESTIONABLE"
    if "PROBABLE" in up:
        return "PROBABLE"
    if "DAY" in up:
        return "DAY-TO-DAY"
    return up
