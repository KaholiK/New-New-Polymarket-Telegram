"""Extract sport, league, teams, market_type from Polymarket market titles.

CRITICAL: detect_market_type uses \\b word boundaries. Without word boundaries, the
substring "under" in "Oklahoma City Thunder" would incorrectly classify a moneyline
market as a totals market. This bug has bitten prior builds — keep the word boundaries.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from apex.core.models import MarketType, Sport
from apex.utils.parsing import extract_teams_from_title, fuzzy_ratio, resolve_team

SPORT_KEYWORDS: dict[Sport, list[str]] = {
    Sport.NBA: ["nba", "basketball", "lakers", "celtics", "warriors"],
    Sport.NFL: ["nfl", "football", "super bowl", "cowboys", "chiefs", "eagles"],
    Sport.MLB: ["mlb", "baseball", "world series", "yankees", "dodgers"],
    Sport.NHL: ["nhl", "hockey", "stanley cup", "maple leafs", "bruins"],
    Sport.UFC: ["ufc", "mma", "fight night"],
    Sport.MLS: ["mls", "major league soccer"],
    Sport.NCAAB: ["ncaab", "march madness", "college basketball"],
    Sport.NCAAF: ["ncaaf", "college football", "bowl game"],
}


# Word-boundary regex — NEVER switch to plain substring matching.
# "Oklahoma City Thunder" contains the substring "under" but is NOT a totals market.
MARKET_TYPE_PATTERNS: list[tuple[MarketType, re.Pattern[str]]] = [
    (MarketType.TOTAL, re.compile(r"\b(over|under)\b", re.IGNORECASE)),
    (MarketType.SPREAD, re.compile(r"\b(spread|cover|handicap|\+\d+\.?\d*|\-\d+\.?\d*)\b", re.IGNORECASE)),
    (MarketType.PROP, re.compile(r"\b(rebounds|assists|points|yards|touchdowns|strikeouts|goals|saves|passing|rushing)\b", re.IGNORECASE)),
    (MarketType.MONEYLINE, re.compile(r"\b(beat|beats|win|wins|moneyline|ml|defeat|defeats|advance|advances)\b", re.IGNORECASE)),
]


@dataclass
class CatalogInfo:
    sport: Sport
    league: str
    market_type: MarketType
    home_team: str | None
    away_team: str | None
    confidence: float  # 0-1 mapping confidence


def detect_sport(text: str, tags: list[str] | None = None) -> Sport:
    """Detect sport from title text. Falls back to tags if available.

    Note: Gamma `tags` field is frequently None on live data — never crash on None here.
    """
    if not text:
        return Sport.UNKNOWN
    t = text.lower()
    # Prefer explicit tags first
    if tags:
        joined = " ".join(str(x).lower() for x in tags if x)
        for sport, keywords in SPORT_KEYWORDS.items():
            if any(k in joined for k in keywords):
                return sport
    # Fallback to title keyword matching
    scores: dict[Sport, int] = {}
    for sport, keywords in SPORT_KEYWORDS.items():
        scores[sport] = sum(1 for k in keywords if k in t)
    best = max(scores.items(), key=lambda x: x[1])
    if best[1] == 0:
        return Sport.UNKNOWN
    return best[0]


def detect_league(sport: Sport) -> str:
    mapping = {
        Sport.NBA: "NBA",
        Sport.NFL: "NFL",
        Sport.MLB: "MLB",
        Sport.NHL: "NHL",
        Sport.UFC: "UFC",
        Sport.MLS: "MLS",
        Sport.NCAAB: "NCAAB",
        Sport.NCAAF: "NCAAF",
    }
    return mapping.get(sport, "")


def detect_market_type(title: str) -> MarketType:
    """Classify market type from title using WORD-BOUNDARY regexes.

    REGRESSION TEST: 'Oklahoma City Thunder' must NOT match 'under'. Use \\b.
    """
    if not title:
        return MarketType.OTHER
    # Check patterns in priority order (TOTAL first, then SPREAD, PROP, MONEYLINE).
    # But don't let TOTAL fire on a simple "A vs B" moneyline. So MONEYLINE vs-pattern
    # is detected separately as a fallback.
    for mt, pattern in MARKET_TYPE_PATTERNS:
        if pattern.search(title):
            # If we matched PROP but the title actually describes a moneyline pattern
            # (X vs Y to win), prefer moneyline.
            if mt == MarketType.PROP and (
                re.search(r"\b(vs|versus|beat|beats)\b", title, re.IGNORECASE)
                or re.search(r"\s@\s", title)
            ):
                return MarketType.MONEYLINE
            return mt
    # "Team A vs Team B" or "Team A @ Team B" → moneyline.
    # '@' isn't a word char so \b around it doesn't work — use separate patterns.
    if re.search(r"\b(vs|versus)\b", title, re.IGNORECASE) or re.search(r"\s@\s", title):
        return MarketType.MONEYLINE
    return MarketType.OTHER


def map_catalog(title: str, tags: list[str] | None = None) -> CatalogInfo:
    """Produce full catalog info for a market title."""
    sport = detect_sport(title, tags)
    league = detect_league(sport)
    market_type = detect_market_type(title)

    raw_a, raw_b = extract_teams_from_title(title)
    canon_a = resolve_team(raw_a, sport=league) if raw_a and league else None
    canon_b = resolve_team(raw_b, sport=league) if raw_b and league else None

    # Confidence scoring:
    # - 0.0 if sport unknown OR no teams extracted
    # - Baseline 0.5 if sport detected
    # - +0.2 if both team names extracted
    # - +0.2 if both teams resolve to canonical aliases
    # - +0.1 if market_type detected
    # Max 1.0.
    conf = 0.0
    if sport != Sport.UNKNOWN:
        conf += 0.5
    if raw_a and raw_b:
        conf += 0.2
    if canon_a and canon_b:
        conf += 0.2
    if market_type != MarketType.OTHER:
        conf += 0.1
    conf = min(1.0, conf)

    # Fuzzy adjustment: downgrade if canonical names disagree with input
    if raw_a and canon_a:
        r = fuzzy_ratio(raw_a, canon_a)
        if r < 0.4:
            conf = max(0.0, conf - 0.1)

    return CatalogInfo(
        sport=sport,
        league=league,
        market_type=market_type,
        home_team=canon_a or raw_a,
        away_team=canon_b or raw_b,
        confidence=conf,
    )
