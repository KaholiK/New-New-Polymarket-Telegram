"""Market discovery: periodically poll Gamma, parse camelCase, build Market objects.

_parse_clob_token_ids is the single point of interpretation for Gamma's idiosyncratic
`clobTokenIds` field which can arrive as:
  - JSON-encoded string: '["yes_token", "no_token"]'   (most common)
  - Plain list of strings: ["yes_token", "no_token"]
  - Missing / None / empty string
  - Malformed (non-parseable)
Each case must be handled without crashing.
"""

from __future__ import annotations

import json
from typing import Any

from apex.core.models import Market
from apex.market.catalog_mapper import map_catalog
from apex.market.polymarket_client import PolymarketClient
from apex.utils.logger import get_logger
from apex.utils.time_utils import parse_iso, utc_now

logger = get_logger(__name__)


def _parse_clob_token_ids(raw: Any) -> tuple[str, str]:
    """Parse Gamma `clobTokenIds` into (yes_token_id, no_token_id).

    Gamma returns a JSON-encoded string most of the time, e.g. '["id1","id2"]'.
    Some old endpoints return a native list. Handle both. Empty / malformed returns ("", "").
    """
    if raw is None:
        return "", ""
    if isinstance(raw, list):
        toks = [str(x) for x in raw if x]
        if len(toks) >= 2:
            return toks[0], toks[1]
        if len(toks) == 1:
            return toks[0], ""
        return "", ""
    if isinstance(raw, str):
        s = raw.strip()
        if not s:
            return "", ""
        try:
            parsed = json.loads(s)
        except (ValueError, TypeError):
            return "", ""
        return _parse_clob_token_ids(parsed)
    return "", ""


def _parse_outcome_prices(raw: Any) -> tuple[float, float]:
    """Parse `outcomePrices` (often a JSON-encoded string of two price strings)."""
    if raw is None:
        return 0.5, 0.5
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except (ValueError, TypeError):
            return 0.5, 0.5
        return _parse_outcome_prices(parsed)
    if isinstance(raw, list) and len(raw) >= 2:
        try:
            return float(raw[0]), float(raw[1])
        except (ValueError, TypeError):
            return 0.5, 0.5
    return 0.5, 0.5


def _safe_float(raw: Any, default: float = 0.0) -> float:
    if raw is None:
        return default
    try:
        return float(raw)
    except (ValueError, TypeError):
        return default


def _safe_bool(raw: Any, default: bool = True) -> bool:
    if raw is None:
        return default
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, str):
        return raw.lower() in ("true", "1", "yes")
    return bool(raw)


def market_from_gamma(raw: dict[str, Any]) -> Market | None:
    """Convert a single Gamma market dict to our Market model.

    Returns None if the market is clearly unusable (no conditionId / no tokens).
    """
    if not isinstance(raw, dict):
        return None
    condition_id = raw.get("conditionId") or raw.get("condition_id")
    if not condition_id:
        return None
    question = str(raw.get("question") or raw.get("title") or "").strip()
    yes_tok, no_tok = _parse_clob_token_ids(raw.get("clobTokenIds") or raw.get("clob_token_ids"))
    if not yes_tok and not no_tok:
        # Unusable for trading — skip
        return None

    yes_price, no_price = _parse_outcome_prices(raw.get("outcomePrices") or raw.get("outcome_prices"))
    volume = _safe_float(raw.get("volume"))
    liquidity = _safe_float(raw.get("liquidity") or raw.get("liquidityNum"))
    end_date = parse_iso(raw.get("endDate") or raw.get("end_date") or "")
    accepting_orders = _safe_bool(raw.get("acceptingOrders") or raw.get("accepting_orders"), default=True)

    # Tags — often None on live data; always fall back to [] for mapping
    tags_raw = raw.get("tags")
    tags: list[str] = []
    if isinstance(tags_raw, list):
        tags = [str(t) for t in tags_raw if t]

    # Gamma's `events` field carries the parent event title (e.g. "2026 NHL Stanley
    # Cup Champion"), which usually contains the sport name even when tags=None.
    event_title: str | None = None
    events_raw = raw.get("events")
    if isinstance(events_raw, list) and events_raw:
        first = events_raw[0]
        if isinstance(first, dict):
            event_title = str(first.get("title") or first.get("slug") or "") or None

    catalog = map_catalog(question, tags=tags, event_title=event_title)

    return Market(
        condition_id=str(condition_id),
        question=question,
        sport=catalog.sport,
        league=catalog.league,
        market_type=catalog.market_type,
        home_team=catalog.home_team,
        away_team=catalog.away_team,
        yes_token_id=yes_tok,
        no_token_id=no_tok,
        yes_price=yes_price,
        no_price=no_price,
        volume=volume,
        liquidity=liquidity,
        end_date=end_date,
        accepting_orders=accepting_orders,
        mapping_confidence=catalog.confidence,
        fetched_at=utc_now(),
        tags=tags,
    )


class MarketDiscovery:
    """Scans Gamma for active sports markets."""

    def __init__(self, client: PolymarketClient) -> None:
        self.client = client

    async def scan_active_markets(
        self, max_markets: int = 500, min_confidence: float = 0.0
    ) -> list[Market]:
        """Fetch active Gamma markets, parse, filter to sports markets above confidence."""
        out: list[Market] = []
        offset = 0
        page_size = 100
        while len(out) < max_markets:
            try:
                batch = await self.client.list_markets(closed=False, limit=page_size, offset=offset)
            except Exception as exc:  # noqa: BLE001
                logger.warning("discovery: list_markets failed at offset=%d: %s", offset, exc)
                break
            if not batch:
                break
            for raw in batch:
                m = market_from_gamma(raw)
                if m is None:
                    continue
                if m.mapping_confidence < min_confidence:
                    continue
                out.append(m)
                if len(out) >= max_markets:
                    break
            if len(batch) < page_size:
                break
            offset += page_size
        logger.info("discovery: scanned %d active markets", len(out))
        return out
