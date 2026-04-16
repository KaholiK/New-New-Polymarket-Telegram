"""The Odds API — fetch multi-book odds, normalize format.

Uses &oddsFormat=decimal per the bug ledger (default is American and would mis-parse).

Smart retry policy
------------------
* 401 / 403 (auth errors)         → **no retry**, mark the ingestor ``degraded``
  so remaining sports in the cycle are skipped. Auth errors aren't transient.
* 429 (rate limit) / 5xx          → retry with exponential backoff (1s, 2s, 4s).
* Network / timeout               → retry with exponential backoff.
* Everything else                 → surface after logging.

``validate_key()`` probes the free ``/sports`` endpoint to confirm the key works
at startup without burning a paid quota call.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

from apex.core.models import MarketType, OddsSnapshot
from apex.utils.logger import get_logger
from apex.utils.math_utils import clamp_prob, implied_prob_from_decimal
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


# Status codes that ARE worth retrying. Everything else (especially 401/403/404)
# is either terminal or caller-facing — retrying just burns quota.
_RETRY_STATUSES: frozenset[int] = frozenset({408, 425, 429, 500, 502, 503, 504})
# Auth failures — mark degraded and bail out of the cycle entirely.
_AUTH_FAIL_STATUSES: frozenset[int] = frozenset({401, 403})


class OddsIngestor:
    def __init__(
        self,
        api_key: str,
        client: httpx.AsyncClient | None = None,
        timeout: float = 15.0,
        retry_attempts: int = 3,
        retry_base_delay: float = 1.0,
        retry_max_delay: float = 8.0,
    ) -> None:
        self.api_key = (api_key or "").strip()
        self._client = client or httpx.AsyncClient(
            timeout=timeout, headers={"User-Agent": "APEX/0.1"}
        )
        self._owns_client = client is None
        self.retry_attempts = max(1, retry_attempts)
        self.retry_base_delay = retry_base_delay
        self.retry_max_delay = retry_max_delay
        # Cycle-level degraded flag — set on 401/403 to short-circuit
        # remaining sports in this cycle. ``reset_cycle()`` clears it at the
        # start of the next cycle so recovery is possible.
        self.degraded: bool = False
        # Sticky until a successful call clears it.
        self.auth_failed: bool = False
        self.last_error: str = ""

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    # ------------------------------------------------------------------ #
    # Key / cycle management                                              #
    # ------------------------------------------------------------------ #

    @property
    def key_configured(self) -> bool:
        return bool(self.api_key) and self.api_key != "test_odds_key"

    def reset_cycle(self) -> None:
        """Clear the within-cycle degraded flag so retry can happen next cycle."""
        # Only reset the transient cycle flag; auth_failed stays sticky until
        # a successful request resets it.
        self.degraded = self.auth_failed

    # ------------------------------------------------------------------ #
    # HTTP helpers                                                        #
    # ------------------------------------------------------------------ #

    async def _request(
        self,
        path: str,
        params: dict[str, Any] | None = None,
    ) -> Any:
        """HTTP GET with smart retry. Returns parsed JSON or raises.

        Auth failures (401/403) set ``self.auth_failed = True`` and ``degraded``
        and are NOT retried. Rate limits and 5xx are retried with exponential
        backoff. Connection/network errors are retried.
        """
        full_params = dict(params or {})
        full_params["apiKey"] = self.api_key
        full_params.setdefault("oddsFormat", "decimal")
        full_params.setdefault("regions", "us")
        url = f"{BASE}{path}"

        last_exc: Exception | None = None
        for attempt in range(self.retry_attempts):
            try:
                r = await self._client.get(url, params=full_params)
            except httpx.HTTPError as exc:
                last_exc = exc
                if attempt == self.retry_attempts - 1:
                    self.last_error = f"network: {exc}"
                    raise
                delay = min(self.retry_base_delay * (2**attempt), self.retry_max_delay)
                logger.warning(
                    "odds network error %s (attempt %d/%d, sleep %.1fs): %s",
                    path, attempt + 1, self.retry_attempts, delay, exc,
                )
                await asyncio.sleep(delay)
                continue

            if r.status_code in _AUTH_FAIL_STATUSES:
                # Terminal for this cycle (same key is going to 401 for every
                # sport). Mark degraded + auth_failed and do NOT retry.
                self.auth_failed = True
                self.degraded = True
                self.last_error = f"auth {r.status_code}: {r.text[:200]}"
                logger.error(
                    "odds auth failed %d on %s — disabling odds for cycle: %s",
                    r.status_code, path, r.text[:200],
                )
                r.raise_for_status()  # raises HTTPStatusError

            if r.status_code in _RETRY_STATUSES:
                last_exc = httpx.HTTPStatusError(
                    f"{r.status_code} {r.reason_phrase}", request=r.request, response=r
                )
                if attempt == self.retry_attempts - 1:
                    self.last_error = f"http {r.status_code}: {r.text[:120]}"
                    raise last_exc
                delay = min(self.retry_base_delay * (2**attempt), self.retry_max_delay)
                logger.warning(
                    "odds retryable %d on %s (attempt %d/%d, sleep %.1fs)",
                    r.status_code, path, attempt + 1, self.retry_attempts, delay,
                )
                await asyncio.sleep(delay)
                continue

            # Any other non-2xx is logged and raised without retry.
            if r.status_code >= 400:
                self.last_error = f"http {r.status_code}: {r.text[:120]}"
                r.raise_for_status()

            # Success — clear sticky auth flag so recovery works.
            self.auth_failed = False
            self.last_error = ""
            return r.json()

        # Should not reach here, but just in case:
        assert last_exc is not None
        raise last_exc

    # ------------------------------------------------------------------ #
    # Public API                                                          #
    # ------------------------------------------------------------------ #

    async def validate_key(self) -> tuple[bool, str]:
        """Probe /sports (free endpoint) to confirm the key works.

        Returns ``(ok, reason)``. Safe to call at startup.
        """
        if not self.key_configured:
            return False, "ODDS_API_KEY is missing or placeholder"
        try:
            data = await self._request("/sports", {"all": "true"})
            if isinstance(data, list) and data:
                return True, ""
            return False, "unexpected /sports response"
        except httpx.HTTPStatusError as exc:
            code = exc.response.status_code if exc.response is not None else 0
            return False, f"HTTP {code}"
        except Exception as exc:  # noqa: BLE001
            return False, f"{exc}"

    async def fetch_odds(self, sport: str, markets: str = "h2h") -> list[OddsSnapshot]:
        """Fetch moneyline (h2h) odds for a sport. Returns per-bookmaker snapshots.

        Returns [] (without error) if the key is missing, a prior 401/403 in this
        cycle put us in degraded mode, or the upstream request failed after retries.
        """
        if not self.key_configured:
            return []
        if self.degraded:
            # Short-circuit — same key would 401 here too.
            return []
        sport_key = SPORT_KEY_MAP.get(sport.upper(), sport.lower())
        try:
            data = await self._request(f"/sports/{sport_key}/odds/", {"markets": markets})
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
