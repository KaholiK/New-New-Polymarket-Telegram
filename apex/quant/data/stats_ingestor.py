"""ESPN standings → team OFF/DEF ratings, pace, recent record.

CRITICAL ESPN quirks (from the bug ledger):
- Correct URL is /apis/v2/sports/... NOT /apis/site/v2/sports/... for standings.
  The /site/ path returns {"fullViewLink": ...} with no data.
- NBA/MLB/NHL use `avgPointsFor` / `avgPointsAgainst` per-game averages.
- NFL uses `pointsFor` / `pointsAgainst` as SEASON TOTALS — must divide by gamesPlayed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from apex.utils.logger import get_logger
from apex.utils.retry import async_retry

logger = get_logger(__name__)

# Correct path is /apis/v2/ (not /apis/site/v2/)
STANDINGS_URL = "https://site.api.espn.com/apis/v2/sports/{sport}/{league}/standings"

SPORT_LEAGUE_MAP = {
    "NBA": ("basketball", "nba"),
    "NFL": ("football", "nfl"),
    "MLB": ("baseball", "mlb"),
    "NHL": ("hockey", "nhl"),
}

# League-average points per game (approximate, 2023-24 seasons)
LEAGUE_AVG_PPG = {
    "NBA": 115.0,
    "NFL": 22.5,
    "MLB": 4.6,
    "NHL": 3.1,
}

# Pythagorean exponents
PYTH_EXPONENT = {
    "NBA": 13.91,
    "NFL": 2.37,
    "MLB": 1.83,
    "NHL": 2.05,
}


@dataclass
class TeamStats:
    team: str
    sport: str
    wins: int
    losses: int
    games_played: int
    points_for_total: float
    points_against_total: float
    avg_points_for: float  # per game
    avg_points_against: float
    pace_factor: float = 1.0  # placeholder for future pace normalization

    @property
    def win_pct(self) -> float:
        if self.games_played == 0:
            return 0.5
        return self.wins / max(1, self.games_played)


class StatsIngestor:
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

    async def fetch_team_stats(self, sport: str) -> list[TeamStats]:
        sl = SPORT_LEAGUE_MAP.get(sport.upper())
        if not sl:
            return []
        url = STANDINGS_URL.format(sport=sl[0], league=sl[1])
        try:
            data = await self._get(url)
        except httpx.HTTPError as exc:
            logger.warning("stats fetch failed for %s: %s", sport, exc)
            return []
        return parse_standings(data, sport.upper())


def _get_stat(stats_list: Any, names: list[str]) -> float:
    """Look up the first matching stat by name from ESPN's nested stats array."""
    if not isinstance(stats_list, list):
        return 0.0
    lower_names = {n.lower() for n in names}
    for st in stats_list:
        if not isinstance(st, dict):
            continue
        name = str(st.get("name") or st.get("type") or "").lower()
        if name in lower_names:
            try:
                return float(st.get("value") or 0)
            except (ValueError, TypeError):
                return 0.0
    return 0.0


def parse_standings(raw: Any, sport: str) -> list[TeamStats]:
    out: list[TeamStats] = []
    if not isinstance(raw, dict):
        return out
    # Response shape: {children: [{standings: {entries: [...]}}, ...]}
    children = raw.get("children") or []
    entries: list[dict[str, Any]] = []
    if isinstance(children, list):
        for c in children:
            if not isinstance(c, dict):
                continue
            s = c.get("standings") or {}
            es = s.get("entries") if isinstance(s, dict) else None
            if isinstance(es, list):
                entries.extend([e for e in es if isinstance(e, dict)])
    # Some feeds place entries at top-level
    if not entries:
        top = raw.get("entries") or raw.get("standings", {}).get("entries") if raw.get("standings") else None
        if isinstance(top, list):
            entries = [e for e in top if isinstance(e, dict)]

    for e in entries:
        team_obj = e.get("team") or {}
        team_name = str(team_obj.get("displayName") or team_obj.get("name") or "")
        if not team_name:
            continue
        stats = e.get("stats") or []
        wins = int(_get_stat(stats, ["wins"]))
        losses = int(_get_stat(stats, ["losses"]))
        games = int(_get_stat(stats, ["gamesPlayed", "games", "gamesplayed"]) or (wins + losses))
        # NBA/MLB/NHL: per-game avgs. NFL: season totals — divide by games.
        avg_pf = _get_stat(stats, ["avgPointsFor"])
        avg_pa = _get_stat(stats, ["avgPointsAgainst"])
        pf_total = _get_stat(stats, ["pointsFor"])
        pa_total = _get_stat(stats, ["pointsAgainst"])
        if sport == "NFL":
            # NFL: pointsFor is the season total — compute per-game average.
            if games > 0:
                avg_pf = pf_total / games if pf_total > 0 else avg_pf
                avg_pa = pa_total / games if pa_total > 0 else avg_pa
        else:
            # If the avg fields are absent, fall back to totals/games.
            if avg_pf == 0 and pf_total > 0 and games > 0:
                avg_pf = pf_total / games
            if avg_pa == 0 and pa_total > 0 and games > 0:
                avg_pa = pa_total / games

        out.append(
            TeamStats(
                team=team_name,
                sport=sport,
                wins=wins,
                losses=losses,
                games_played=games or (wins + losses),
                points_for_total=pf_total if pf_total > 0 else avg_pf * max(1, games),
                points_against_total=pa_total if pa_total > 0 else avg_pa * max(1, games),
                avg_points_for=avg_pf,
                avg_points_against=avg_pa,
            )
        )
    return out


def off_def_ratings(stats: list[TeamStats], sport: str) -> dict[str, tuple[float, float]]:
    """Return {team: (off_rating, def_rating)} normalized to 100 = league avg.

    Convention: HIGHER off = better offense. HIGHER def = team gives up MORE points
    (weaker defense). So expected score = (own_off + opp_def) / 200 * league_avg.
    """
    if not stats:
        return {}
    avg_for = sum(s.avg_points_for for s in stats) / len(stats)
    avg_against = sum(s.avg_points_against for s in stats) / len(stats)
    if avg_for <= 0:
        avg_for = LEAGUE_AVG_PPG.get(sport, 100.0)
    if avg_against <= 0:
        avg_against = LEAGUE_AVG_PPG.get(sport, 100.0)
    out: dict[str, tuple[float, float]] = {}
    for s in stats:
        off = 100.0 * (s.avg_points_for / avg_for) if avg_for > 0 else 100.0
        # HIGHER def = worse defense (gives up more); offense scores more vs weak D.
        defn = 100.0 * (s.avg_points_against / avg_against) if avg_against > 0 else 100.0
        out[s.team] = (off, defn)
    return out
