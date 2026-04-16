"""SportsDataIO client — player stats, team stats, schedules, injuries.

SportsDataIO has dozens of endpoints; this wrapper exposes the small subset we
actually enrich the forecaster context with:

    GET /v3/{sport}/scores/json/AreAnyGamesInProgress
    GET /v3/{sport}/scores/json/GamesByDate/{date}
    GET /v3/{sport}/stats/json/PlayerSeasonStats/{season}
    GET /v3/{sport}/scores/json/TeamSeasonStats/{season}
    GET /v3/{sport}/scores/json/Injuries

`sport` maps to SportsDataIO's URL slug: nba, nfl, mlb, nhl.

Caching:
- scores (live games) → 5 minute TTL
- stats (season) → 1 hour TTL
- injuries → 10 minute TTL

Key is passed as an `Ocp-Apim-Subscription-Key` header. If the key is missing,
every method returns an empty list without raising — the rest of the pipeline
degrades gracefully.
"""

from __future__ import annotations

import time
from datetime import UTC
from typing import Any

import httpx

from apex.utils.logger import get_logger
from apex.utils.retry import async_retry

logger = get_logger(__name__)

BASE = "https://api.sportsdata.io/v3"

# (sport_slug) mapping — keep in sync with SPORT_KEY_MAP in apex/data/odds_ingestor.py
SPORT_SLUG = {
    "NBA": "nba",
    "NFL": "nfl",
    "MLB": "mlb",
    "NHL": "nhl",
}


class _TTLCache:
    """Tiny per-key TTL cache so hot paths don't re-hit the API."""

    def __init__(self) -> None:
        self._store: dict[str, tuple[float, Any]] = {}

    def get(self, key: str) -> Any:
        item = self._store.get(key)
        if item is None:
            return None
        expiry, val = item
        if time.monotonic() > expiry:
            self._store.pop(key, None)
            return None
        return val

    def set(self, key: str, value: Any, ttl_seconds: float) -> None:
        self._store[key] = (time.monotonic() + ttl_seconds, value)

    def clear(self) -> None:
        self._store.clear()


class SportsDataClient:
    def __init__(
        self,
        api_key: str,
        client: httpx.AsyncClient | None = None,
        timeout: float = 15.0,
    ) -> None:
        self.api_key = (api_key or "").strip()
        self._client = client or httpx.AsyncClient(
            timeout=timeout,
            headers={"User-Agent": "APEX/0.1"},
        )
        self._owns_client = client is None
        self._cache = _TTLCache()

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    @async_retry(attempts=3, base_delay=1.0, max_delay=8.0, exceptions=(httpx.HTTPError,))
    async def _get(self, path: str) -> Any:
        url = f"{BASE}{path}"
        r = await self._client.get(url, headers={"Ocp-Apim-Subscription-Key": self.api_key})
        r.raise_for_status()
        return r.json()

    async def _cached_get(self, path: str, ttl: float) -> Any:
        if not self.enabled:
            return None
        cached = self._cache.get(path)
        if cached is not None:
            return cached
        try:
            data = await self._get(path)
        except httpx.HTTPError as exc:
            logger.warning("sportsdata GET %s failed: %s", path, exc)
            return None
        if data is not None:
            self._cache.set(path, data, ttl)
        return data

    # ------------------- public API -------------------

    async def any_games_in_progress(self, sport: str) -> bool | None:
        slug = SPORT_SLUG.get(sport.upper())
        if not slug:
            return None
        data = await self._cached_get(f"/{slug}/scores/json/AreAnyGamesInProgress", ttl=300)
        if isinstance(data, bool):
            return data
        return None

    async def games_by_date(self, sport: str, date_str: str) -> list[dict[str, Any]]:
        """date_str in YYYY-MM-DD. Returns list of game dicts or []."""
        slug = SPORT_SLUG.get(sport.upper())
        if not slug:
            return []
        data = await self._cached_get(f"/{slug}/scores/json/GamesByDate/{date_str}", ttl=300)
        return data if isinstance(data, list) else []

    async def player_season_stats(self, sport: str, season: int | str) -> list[dict[str, Any]]:
        slug = SPORT_SLUG.get(sport.upper())
        if not slug:
            return []
        data = await self._cached_get(
            f"/{slug}/stats/json/PlayerSeasonStats/{season}", ttl=3600
        )
        return data if isinstance(data, list) else []

    async def team_season_stats(self, sport: str, season: int | str) -> list[dict[str, Any]]:
        slug = SPORT_SLUG.get(sport.upper())
        if not slug:
            return []
        data = await self._cached_get(
            f"/{slug}/scores/json/TeamSeasonStats/{season}", ttl=3600
        )
        return data if isinstance(data, list) else []

    async def injuries(self, sport: str) -> list[dict[str, Any]]:
        slug = SPORT_SLUG.get(sport.upper())
        if not slug:
            return []
        data = await self._cached_get(f"/{slug}/scores/json/Injuries", ttl=600)
        return data if isinstance(data, list) else []

    # ------------------- enrichment helpers -------------------

    async def team_context(self, sport: str, team_name: str) -> dict[str, Any]:
        """Collect a condensed team snapshot for the Claude prompt.

        Silently degrades: every failure maps to an empty dict so the caller can
        merge it into a broader context without branching.
        """
        if not self.enabled or not team_name:
            return {}
        from datetime import datetime

        year = datetime.now(UTC).year
        # SportsDataIO uses the season-end year for NBA/NHL/MLB; the API accepts both
        # the integer year and a "2026REG" format. Try the plain year first.
        teams = await self.team_season_stats(sport, year)
        team_rec: dict[str, Any] = {}
        if teams:
            nm = team_name.lower()
            for t in teams:
                name = (t.get("Name") or t.get("FullName") or "").lower()
                city = (t.get("City") or "").lower()
                if nm in name or nm in f"{city} {name}" or name in nm:
                    team_rec = t
                    break
        return {
            "team": team_name,
            "wins": team_rec.get("Wins"),
            "losses": team_rec.get("Losses"),
            "points_per_game": team_rec.get("PointsPerGameFor") or team_rec.get("Points"),
            "points_against_per_game": team_rec.get("PointsPerGameAgainst"),
            "conference_rank": team_rec.get("ConferenceRank"),
            "division_rank": team_rec.get("DivisionRank"),
        }
