"""The Odds API — fetch multi-book odds, normalize format.

Uses &oddsFormat=decimal per the bug ledger (default is American and would mis-parse).
"""

from __future__ import annotations

from typing import Any

import httpx

from apex.core.models import MarketType, OddsSnapshot
from apex.utils.logger import get_logger
from apex.utils.math_utils import clamp_prob, implied_prob_from_decimal
from apex.utils.retry import async_retry
from apex.utils.time_utils import parse_iso, utc_now

logger = get_logger(__name__)

BASE = "https://api.the-odds-api.com/v4"

SPORT_KEY_MAP = {
    "NFL": "americanfootball_nfl",
    "NBA": "basketball_nba",
    "MLB": "baseball_mlb",
    "NHL": "icehockey_nhl",
    "UFC": "mma_mixed_martial_arts",
    "MLS": "soccer_usa_mls",
}


# Sharp-book weights for consensus builder
BOOKMAKER_WEIGHTS = {
    "pinnacle": 3.0,
    "circa": 2.5,
    "betcme": 2.0,
    "bookmaker": 1.5,
    "caesars": 1.0,
    "draftkings": 1.0,
    "fanduel": 1.0,
    "betmgm": 1.0,
    "pointsbet": 1.0,
    "barstool": 0.8,
    "default": 1.0,
}


def book_weight(name: str) -> float:
    key = (name or "").lower().replace(" ", "").replace("-", "")
    return BOOKMAKER_WEIGHTS.get(key, BOOKMAKER_WEIGHTS["default"])


class OddsIngestor:
    def __init__(
        self,
        api_key: str,
        client: httpx.AsyncClient | None = None,
        timeout: float = 15.0,
    ) -> None:
        self.api_key = api_key
        self._client = client or httpx.AsyncClient(timeout=timeout, headers={"User-Agent": "APEX/0.1"})
        self._owns_client = client is None

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    @async_retry(attempts=3, base_delay=1.0, max_delay=8.0, exceptions=(httpx.HTTPError,))
    async def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        full_params = dict(params or {})
        full_params["apiKey"] = self.api_key
        # CRITICAL: always request decimal format; default is American
        full_params.setdefault("oddsFormat", "decimal")
        full_params.setdefault("regions", "us")
        r = await self._client.get(f"{BASE}{path}", params=full_params)
        r.raise_for_status()
        return r.json()

    async def fetch_odds(self, sport: str, markets: str = "h2h") -> list[OddsSnapshot]:
        """Fetch moneyline (h2h) odds for a sport. Returns per-bookmaker snapshots."""
        if not self.api_key or self.api_key == "test_odds_key":
            # No real key → skip silently (test/paper environment)
            return []
        sport_key = SPORT_KEY_MAP.get(sport.upper(), sport.lower())
        try:
            data = await self._get(f"/sports/{sport_key}/odds/", {"markets": markets})
        except httpx.HTTPError as exc:
            logger.warning("odds fetch failed for %s: %s", sport, exc)
            return []
        return parse_odds_events(data, sport)


def parse_odds_events(events: Any, sport: str) -> list[OddsSnapshot]:
    """Parse /v4/sports/{sport}/odds response into flat OddsSnapshot list."""
    out: list[OddsSnapshot] = []
    if not isinstance(events, list):
        return out
    for ev in events:
        if not isinstance(ev, dict):
            continue
        event_id = str(ev.get("id") or "")
        home = str(ev.get("home_team") or "")
        away = str(ev.get("away_team") or "")
        bookmakers = ev.get("bookmakers") or []
        if not isinstance(bookmakers, list):
            continue
        fetched = parse_iso(str(ev.get("commence_time") or "")) or utc_now()
        for bm in bookmakers:
            if not isinstance(bm, dict):
                continue
            bm_key = str(bm.get("key") or "")
            markets = bm.get("markets") or []
            for mk in markets:
                if not isinstance(mk, dict):
                    continue
                if mk.get("key") != "h2h":
                    continue
                outcomes = mk.get("outcomes") or []
                home_odds: float | None = None
                away_odds: float | None = None
                for o in outcomes:
                    if not isinstance(o, dict):
                        continue
                    name = str(o.get("name") or "")
                    try:
                        price = float(o.get("price") or 0)
                    except (ValueError, TypeError):
                        continue
                    if price <= 1.0:
                        continue
                    if name == home:
                        home_odds = price
                    elif name == away:
                        away_odds = price
                if home_odds and away_odds:
                    out.append(
                        OddsSnapshot(
                            event_id=event_id,
                            bookmaker=bm_key,
                            sport=sport,
                            home_team=home,
                            away_team=away,
                            home_odds=home_odds,
                            away_odds=away_odds,
                            home_implied_prob=clamp_prob(implied_prob_from_decimal(home_odds)),
                            away_implied_prob=clamp_prob(implied_prob_from_decimal(away_odds)),
                            market_type=MarketType.MONEYLINE,
                            fetched_at=fetched,
                        )
                    )
    return out
