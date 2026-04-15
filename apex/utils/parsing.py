"""Team name normalization, alias resolution, fuzzy matching.

IMPORTANT: Alias keys are SPORT-NAMESPACED (e.g. "nfl:san francisco") because
"San Francisco" exists in both NFL (49ers) and NBA history — using a bare name
as a key would collide.
"""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

# Sport-namespaced team aliases → canonical name used in Elo and stats tables.
# Keys are lowercased. Canonical values are the "display" team name (title case).
TEAM_ALIASES: dict[str, str] = {
    # NBA
    "nba:lakers": "Los Angeles Lakers",
    "nba:la lakers": "Los Angeles Lakers",
    "nba:lal": "Los Angeles Lakers",
    "nba:clippers": "LA Clippers",
    "nba:la clippers": "LA Clippers",
    "nba:lac": "LA Clippers",
    "nba:celtics": "Boston Celtics",
    "nba:bos": "Boston Celtics",
    "nba:warriors": "Golden State Warriors",
    "nba:gsw": "Golden State Warriors",
    "nba:golden state": "Golden State Warriors",
    "nba:thunder": "Oklahoma City Thunder",
    "nba:okc": "Oklahoma City Thunder",
    "nba:oklahoma city": "Oklahoma City Thunder",
    "nba:knicks": "New York Knicks",
    "nba:nyk": "New York Knicks",
    "nba:nets": "Brooklyn Nets",
    "nba:bkn": "Brooklyn Nets",
    "nba:bulls": "Chicago Bulls",
    "nba:chi": "Chicago Bulls",
    "nba:heat": "Miami Heat",
    "nba:mia": "Miami Heat",
    "nba:bucks": "Milwaukee Bucks",
    "nba:mil": "Milwaukee Bucks",
    "nba:nuggets": "Denver Nuggets",
    "nba:den": "Denver Nuggets",
    "nba:suns": "Phoenix Suns",
    "nba:phx": "Phoenix Suns",
    "nba:mavericks": "Dallas Mavericks",
    "nba:mavs": "Dallas Mavericks",
    "nba:dal": "Dallas Mavericks",
    "nba:rockets": "Houston Rockets",
    "nba:hou": "Houston Rockets",
    "nba:spurs": "San Antonio Spurs",
    "nba:sas": "San Antonio Spurs",
    "nba:san antonio": "San Antonio Spurs",
    "nba:76ers": "Philadelphia 76ers",
    "nba:sixers": "Philadelphia 76ers",
    "nba:phi": "Philadelphia 76ers",
    "nba:raptors": "Toronto Raptors",
    "nba:tor": "Toronto Raptors",
    "nba:pistons": "Detroit Pistons",
    "nba:det": "Detroit Pistons",
    "nba:cavaliers": "Cleveland Cavaliers",
    "nba:cavs": "Cleveland Cavaliers",
    "nba:cle": "Cleveland Cavaliers",
    "nba:magic": "Orlando Magic",
    "nba:orl": "Orlando Magic",
    "nba:hawks": "Atlanta Hawks",
    "nba:atl": "Atlanta Hawks",
    "nba:hornets": "Charlotte Hornets",
    "nba:cha": "Charlotte Hornets",
    "nba:wizards": "Washington Wizards",
    "nba:was": "Washington Wizards",
    "nba:pacers": "Indiana Pacers",
    "nba:ind": "Indiana Pacers",
    "nba:timberwolves": "Minnesota Timberwolves",
    "nba:wolves": "Minnesota Timberwolves",
    "nba:min": "Minnesota Timberwolves",
    "nba:jazz": "Utah Jazz",
    "nba:uta": "Utah Jazz",
    "nba:kings": "Sacramento Kings",
    "nba:sac": "Sacramento Kings",
    "nba:trail blazers": "Portland Trail Blazers",
    "nba:blazers": "Portland Trail Blazers",
    "nba:por": "Portland Trail Blazers",
    "nba:grizzlies": "Memphis Grizzlies",
    "nba:mem": "Memphis Grizzlies",
    "nba:pelicans": "New Orleans Pelicans",
    "nba:nop": "New Orleans Pelicans",
    # NFL — only unambiguous/common aliases (sport-prefixed to avoid collisions)
    "nfl:san francisco": "San Francisco 49ers",
    "nfl:49ers": "San Francisco 49ers",
    "nfl:sf": "San Francisco 49ers",
    "nfl:cowboys": "Dallas Cowboys",
    "nfl:dal": "Dallas Cowboys",
    "nfl:eagles": "Philadelphia Eagles",
    "nfl:phi": "Philadelphia Eagles",
    "nfl:chiefs": "Kansas City Chiefs",
    "nfl:kc": "Kansas City Chiefs",
    "nfl:kansas city": "Kansas City Chiefs",
    "nfl:packers": "Green Bay Packers",
    "nfl:gb": "Green Bay Packers",
    "nfl:bills": "Buffalo Bills",
    "nfl:buf": "Buffalo Bills",
    "nfl:patriots": "New England Patriots",
    "nfl:ne": "New England Patriots",
    "nfl:jets": "New York Jets",
    "nfl:nyj": "New York Jets",
    "nfl:giants": "New York Giants",
    "nfl:nyg": "New York Giants",
    "nfl:dolphins": "Miami Dolphins",
    "nfl:mia": "Miami Dolphins",
    "nfl:ravens": "Baltimore Ravens",
    "nfl:bal": "Baltimore Ravens",
    "nfl:bengals": "Cincinnati Bengals",
    "nfl:cin": "Cincinnati Bengals",
    "nfl:browns": "Cleveland Browns",
    "nfl:cle": "Cleveland Browns",
    "nfl:steelers": "Pittsburgh Steelers",
    "nfl:pit": "Pittsburgh Steelers",
    "nfl:texans": "Houston Texans",
    "nfl:hou": "Houston Texans",
    "nfl:colts": "Indianapolis Colts",
    "nfl:ind": "Indianapolis Colts",
    "nfl:jaguars": "Jacksonville Jaguars",
    "nfl:jax": "Jacksonville Jaguars",
    "nfl:titans": "Tennessee Titans",
    "nfl:ten": "Tennessee Titans",
    "nfl:broncos": "Denver Broncos",
    "nfl:den": "Denver Broncos",
    "nfl:raiders": "Las Vegas Raiders",
    "nfl:lv": "Las Vegas Raiders",
    "nfl:chargers": "Los Angeles Chargers",
    "nfl:lac": "Los Angeles Chargers",
    "nfl:rams": "Los Angeles Rams",
    "nfl:lar": "Los Angeles Rams",
    "nfl:seahawks": "Seattle Seahawks",
    "nfl:sea": "Seattle Seahawks",
    "nfl:cardinals": "Arizona Cardinals",
    "nfl:ari": "Arizona Cardinals",
    "nfl:vikings": "Minnesota Vikings",
    "nfl:min": "Minnesota Vikings",
    "nfl:bears": "Chicago Bears",
    "nfl:chi": "Chicago Bears",
    "nfl:lions": "Detroit Lions",
    "nfl:det": "Detroit Lions",
    "nfl:saints": "New Orleans Saints",
    "nfl:no": "New Orleans Saints",
    "nfl:falcons": "Atlanta Falcons",
    "nfl:atl": "Atlanta Falcons",
    "nfl:panthers": "Carolina Panthers",
    "nfl:car": "Carolina Panthers",
    "nfl:buccaneers": "Tampa Bay Buccaneers",
    "nfl:bucs": "Tampa Bay Buccaneers",
    "nfl:tb": "Tampa Bay Buccaneers",
    "nfl:commanders": "Washington Commanders",
    "nfl:was": "Washington Commanders",
    # MLB — subset of most common aliases
    "mlb:yankees": "New York Yankees",
    "mlb:nyy": "New York Yankees",
    "mlb:mets": "New York Mets",
    "mlb:nym": "New York Mets",
    "mlb:red sox": "Boston Red Sox",
    "mlb:bos": "Boston Red Sox",
    "mlb:dodgers": "Los Angeles Dodgers",
    "mlb:lad": "Los Angeles Dodgers",
    "mlb:angels": "Los Angeles Angels",
    "mlb:laa": "Los Angeles Angels",
    "mlb:giants": "San Francisco Giants",
    "mlb:sfg": "San Francisco Giants",
    "mlb:astros": "Houston Astros",
    "mlb:hou": "Houston Astros",
    "mlb:braves": "Atlanta Braves",
    "mlb:atl": "Atlanta Braves",
    "mlb:phillies": "Philadelphia Phillies",
    "mlb:phi": "Philadelphia Phillies",
    "mlb:cubs": "Chicago Cubs",
    "mlb:chc": "Chicago Cubs",
    "mlb:white sox": "Chicago White Sox",
    "mlb:cws": "Chicago White Sox",
    "mlb:cardinals": "St. Louis Cardinals",
    "mlb:stl": "St. Louis Cardinals",
    "mlb:rangers": "Texas Rangers",
    "mlb:tex": "Texas Rangers",
    "mlb:orioles": "Baltimore Orioles",
    "mlb:bal": "Baltimore Orioles",
    "mlb:padres": "San Diego Padres",
    "mlb:sd": "San Diego Padres",
    "mlb:mariners": "Seattle Mariners",
    "mlb:sea": "Seattle Mariners",
    "mlb:blue jays": "Toronto Blue Jays",
    "mlb:tor": "Toronto Blue Jays",
    # NHL — subset
    "nhl:rangers": "New York Rangers",
    "nhl:nyr": "New York Rangers",
    "nhl:islanders": "New York Islanders",
    "nhl:nyi": "New York Islanders",
    "nhl:bruins": "Boston Bruins",
    "nhl:bos": "Boston Bruins",
    "nhl:maple leafs": "Toronto Maple Leafs",
    "nhl:tor": "Toronto Maple Leafs",
    "nhl:leafs": "Toronto Maple Leafs",
    "nhl:canadiens": "Montreal Canadiens",
    "nhl:mtl": "Montreal Canadiens",
    "nhl:habs": "Montreal Canadiens",
    "nhl:red wings": "Detroit Red Wings",
    "nhl:det": "Detroit Red Wings",
    "nhl:blackhawks": "Chicago Blackhawks",
    "nhl:chi": "Chicago Blackhawks",
    "nhl:avalanche": "Colorado Avalanche",
    "nhl:col": "Colorado Avalanche",
    "nhl:golden knights": "Vegas Golden Knights",
    "nhl:vgk": "Vegas Golden Knights",
    "nhl:kings": "Los Angeles Kings",
    "nhl:lak": "Los Angeles Kings",
    "nhl:sharks": "San Jose Sharks",
    "nhl:sjs": "San Jose Sharks",
    "nhl:panthers": "Florida Panthers",
    "nhl:fla": "Florida Panthers",
    "nhl:lightning": "Tampa Bay Lightning",
    "nhl:tbl": "Tampa Bay Lightning",
    "nhl:oilers": "Edmonton Oilers",
    "nhl:edm": "Edmonton Oilers",
    "nhl:flames": "Calgary Flames",
    "nhl:cgy": "Calgary Flames",
    "nhl:jets": "Winnipeg Jets",
    "nhl:wpg": "Winnipeg Jets",
}


def normalize_text(s: str) -> str:
    """Lowercase, strip accents, collapse whitespace, remove most punctuation."""
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower().strip()
    # Replace some punctuation with space, remove others
    s = re.sub(r"[.'`’]", "", s)
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def resolve_team(name: str, sport: str | None = None) -> str | None:
    """Resolve a team name to canonical form. Sport namespace recommended.

    If sport is provided, only sport-prefixed keys are considered.
    Returns None if no match.
    """
    if not name:
        return None
    norm = normalize_text(name)
    if sport:
        sport_key = sport.lower()
        direct = TEAM_ALIASES.get(f"{sport_key}:{norm}")
        if direct:
            return direct
        # Also try substring match within sport namespace
        for key, canon in TEAM_ALIASES.items():
            if not key.startswith(f"{sport_key}:"):
                continue
            alias = key.split(":", 1)[1]
            if alias == norm:
                return canon
        return None

    # No sport specified → ambiguous; only accept unambiguous matches across all sports
    candidates = set()
    for key, canon in TEAM_ALIASES.items():
        alias = key.split(":", 1)[1]
        if alias == norm:
            candidates.add(canon)
    if len(candidates) == 1:
        return next(iter(candidates))
    return None


def fuzzy_ratio(a: str, b: str) -> float:
    """0-1 similarity score using SequenceMatcher on normalized strings."""
    na, nb = normalize_text(a), normalize_text(b)
    if not na or not nb:
        return 0.0
    return SequenceMatcher(None, na, nb).ratio()


def fuzzy_best_match(query: str, candidates: list[str], min_ratio: float = 0.6) -> tuple[str, float] | None:
    """Return best (candidate, ratio) above threshold, or None."""
    best: tuple[str, float] | None = None
    for c in candidates:
        r = fuzzy_ratio(query, c)
        if r >= min_ratio and (best is None or r > best[1]):
            best = (c, r)
    return best


def extract_teams_from_title(title: str) -> tuple[str | None, str | None]:
    """Best-effort team extraction from a Polymarket question title.

    Handles 'X vs Y', 'X @ Y', 'X beats Y', 'Will X win...' patterns.
    Returns (team_a, team_b) — may be None if not parseable.
    """
    if not title:
        return None, None
    t = title.strip()

    # "A vs B" or "A vs. B"
    m = re.search(r"(.+?)\s+vs\.?\s+(.+)", t, re.IGNORECASE)
    if m:
        return _clean_team(m.group(1)), _clean_team(m.group(2))

    # "A @ B"
    m = re.search(r"(.+?)\s+@\s+(.+)", t)
    if m:
        return _clean_team(m.group(1)), _clean_team(m.group(2))

    # "A beat[s] B", "A defeat[s] B"
    m = re.search(r"(.+?)\s+(?:beat|beats|defeat|defeats)\s+(.+)", t, re.IGNORECASE)
    if m:
        return _clean_team(m.group(1)), _clean_team(m.group(2))

    return None, None


def _clean_team(raw: str) -> str:
    """Strip trailing '?', words like 'win', 'moneyline', sportsbook noise."""
    s = raw.strip()
    s = re.sub(r"\?+$", "", s).strip()
    # Common trailing noise
    s = re.sub(
        r"\b(win|wins|moneyline|total|over|under|spread|cover|to\s+win)\b.*$",
        "",
        s,
        flags=re.IGNORECASE,
    ).strip()
    s = re.sub(r"\s+", " ", s)
    return s.strip(" ,.-")
