"""News feed with SHA-256 dedup fingerprinting."""

from __future__ import annotations

import hashlib
from typing import Any

import httpx

from apex.core.models import NewsItem, Sport
from apex.utils.logger import get_logger
from apex.utils.retry import async_retry
from apex.utils.time_utils import parse_iso, utc_now

logger = get_logger(__name__)

NEWS_URL_FMT = "https://site.api.espn.com/apis/site/v2/sports/{sport}/{league}/news"

SPORT_LEAGUE_MAP = {
    "NBA": ("basketball", "nba"),
    "NFL": ("football", "nfl"),
    "MLB": ("baseball", "mlb"),
    "NHL": ("hockey", "nhl"),
}


def news_fingerprint(headline: str, published_at: Any = None) -> str:
    """Stable SHA-256 fingerprint for dedup."""
    base = f"{(headline or '').strip().lower()}|{published_at or ''}"
    return hashlib.sha256(base.encode("utf-8")).hexdigest()[:32]


class NewsMonitor:
    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client or httpx.AsyncClient(timeout=15.0, headers={"User-Agent": "APEX/0.1"})
        self._owns_client = client is None
        self._seen_in_mem: set[str] = set()

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    @async_retry(attempts=3, base_delay=1.0, max_delay=8.0, exceptions=(httpx.HTTPError,))
    async def _get(self, url: str) -> Any:
        r = await self._client.get(url)
        r.raise_for_status()
        return r.json()

    async def fetch_news(self, sport: str) -> list[NewsItem]:
        sl = SPORT_LEAGUE_MAP.get(sport.upper())
        if not sl:
            return []
        url = NEWS_URL_FMT.format(sport=sl[0], league=sl[1])
        try:
            data = await self._get(url)
        except httpx.HTTPError as exc:
            logger.warning("news fetch failed for %s: %s", sport, exc)
            return []
        return parse_news(data, sport)

    def filter_new(self, items: list[NewsItem]) -> list[NewsItem]:
        """Return only items whose fingerprint we haven't seen this run."""
        out = []
        for it in items:
            if it.fingerprint in self._seen_in_mem:
                continue
            self._seen_in_mem.add(it.fingerprint)
            out.append(it)
        return out


def parse_news(raw: Any, sport: str) -> list[NewsItem]:
    out: list[NewsItem] = []
    if not isinstance(raw, dict):
        return out
    articles = raw.get("articles") or raw.get("items") or []
    if not isinstance(articles, list):
        return out
    try:
        sport_enum = Sport(sport.upper())
    except ValueError:
        sport_enum = Sport.UNKNOWN
    for art in articles:
        if not isinstance(art, dict):
            continue
        headline = str(art.get("headline") or art.get("title") or "")
        if not headline:
            continue
        summary = str(art.get("description") or art.get("summary") or "")
        pub_raw = str(art.get("published") or art.get("lastModified") or "")
        pub = parse_iso(pub_raw) or utc_now()
        teams: list[str] = []
        cats = art.get("categories") or []
        if isinstance(cats, list):
            for c in cats:
                if isinstance(c, dict):
                    t = c.get("team")
                    if isinstance(t, dict):
                        name = str(t.get("displayName") or t.get("name") or "")
                        if name:
                            teams.append(name)
        fp = news_fingerprint(headline, pub.isoformat())
        out.append(
            NewsItem(
                fingerprint=fp,
                headline=headline,
                summary=summary,
                teams=teams,
                sport=sport_enum,
                published_at=pub,
                fetched_at=utc_now(),
            )
        )
    return out
