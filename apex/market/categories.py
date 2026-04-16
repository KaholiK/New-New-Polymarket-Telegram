"""Comprehensive market categorization for Polymarket markets.

Provides a fine-grained Category enum (sports broken out by league, plus non-sport
verticals), keyword dictionaries for detection, and a detect_category() entry point
that scores candidate categories from a market title and optional event title / tags.

Word-boundary note
------------------
Short or ambiguous keywords (e.g. "sol", "eth", "f1") are wrapped in \\b word-boundary
patterns so they don't fire on substrings ("solution", "ethics", "cf1").  Longer or
visually unambiguous keywords (e.g. "bitcoin", "premier league") are matched with a
plain ``in`` check for speed, since a false-positive there is highly unlikely.
"""

from __future__ import annotations

import re
from enum import Enum

from apex.core.models import Sport

# ---------------------------------------------------------------------------
# Category enum
# ---------------------------------------------------------------------------


class Category(str, Enum):
    # ---- Sports: North American professional ----
    NFL = "NFL"
    NBA = "NBA"
    MLB = "MLB"
    NHL = "NHL"
    NCAAF = "NCAAF"
    NCAAB = "NCAAB"
    UFC_MMA = "UFC_MMA"
    BOXING = "BOXING"
    NASCAR = "NASCAR"
    WNBA = "WNBA"

    # ---- Sports: Motorsport ----
    F1 = "F1"
    MOTOGP = "MOTOGP"

    # ---- Sports: Soccer / Football ----
    MLS = "MLS"
    EPL = "EPL"
    LA_LIGA = "LA_LIGA"
    BUNDESLIGA = "BUNDESLIGA"
    SERIE_A = "SERIE_A"
    LIGUE_1 = "LIGUE_1"
    CHAMPIONS_LEAGUE = "CHAMPIONS_LEAGUE"
    EUROPA_LEAGUE = "EUROPA_LEAGUE"
    WORLD_CUP = "WORLD_CUP"

    # ---- Sports: Other ----
    TENNIS = "TENNIS"
    GOLF = "GOLF"
    CRICKET = "CRICKET"
    ESPORTS = "ESPORTS"
    OLYMPICS = "OLYMPICS"

    # ---- Non-sport verticals ----
    CRYPTO = "CRYPTO"
    POLITICS = "POLITICS"
    ENTERTAINMENT = "ENTERTAINMENT"
    ECONOMICS = "ECONOMICS"
    SCIENCE = "SCIENCE"
    WEATHER = "WEATHER"

    # ---- Fallback ----
    OTHER = "OTHER"


# ---------------------------------------------------------------------------
# Keyword lists
# ---------------------------------------------------------------------------
# All keywords are stored lower-case.  Plain strings are matched with a
# simple ``keyword in text_lower`` check.  Entries that are wrapped in a
# list starting with the sentinel "__wb__" are treated as word-boundary
# patterns and compiled to ``\bkeyword\b``.
#
# To keep the detection loop simple, we pre-compile word-boundary patterns
# at module load time (see _WB_PATTERNS below).

CATEGORY_KEYWORDS: dict[Category, list[str]] = {

    # ------------------------------------------------------------------
    Category.NFL: [
        "nfl", "super bowl", "pro bowl", "nfl draft",
        # AFC
        "buffalo bills", "miami dolphins", "new england patriots", "new york jets",
        "baltimore ravens", "cincinnati bengals", "cleveland browns", "pittsburgh steelers",
        "houston texans", "indianapolis colts", "jacksonville jaguars", "tennessee titans",
        "denver broncos", "kansas city chiefs", "las vegas raiders", "los angeles chargers",
        # NFC
        "dallas cowboys", "new york giants", "philadelphia eagles", "washington commanders",
        "chicago bears", "detroit lions", "green bay packers", "minnesota vikings",
        "atlanta falcons", "carolina panthers", "new orleans saints", "tampa bay buccaneers",
        "arizona cardinals", "los angeles rams", "san francisco 49ers", "seattle seahawks",
        # Common short names (only add when unambiguous in context)
        "bills", "dolphins", "patriots", "jets", "ravens", "bengals", "browns", "steelers",
        "texans", "colts", "jaguars", "titans", "broncos", "chiefs", "raiders", "chargers",
        "cowboys", "giants", "eagles", "commanders", "bears", "lions", "packers", "vikings",
        "falcons", "panthers", "saints", "buccaneers", "cardinals", "rams", "seahawks",
        # Conference / division labels
        "afc east", "afc north", "afc south", "afc west",
        "nfc east", "nfc north", "nfc south", "nfc west",
        "afc championship", "nfc championship",
    ],

    # ------------------------------------------------------------------
    Category.NBA: [
        "nba", "nba finals", "nba mvp", "nba championship", "nba all-star", "slam dunk",
        "basketball",
        # All 30 franchises
        "atlanta hawks", "boston celtics", "brooklyn nets", "charlotte hornets",
        "chicago bulls", "cleveland cavaliers", "dallas mavericks", "denver nuggets",
        "detroit pistons", "golden state warriors", "houston rockets",
        "indiana pacers", "los angeles clippers", "los angeles lakers",
        "memphis grizzlies", "miami heat", "milwaukee bucks", "minnesota timberwolves",
        "new orleans pelicans", "new york knicks", "oklahoma city thunder",
        "orlando magic", "philadelphia 76ers", "phoenix suns", "portland trail blazers",
        "sacramento kings", "san antonio spurs", "toronto raptors",
        "utah jazz", "washington wizards",
        # Common short names
        "hawks", "celtics", "nets", "hornets", "bulls", "cavaliers", "cavs",
        "mavericks", "mavs", "nuggets", "pistons", "warriors", "rockets",
        "pacers", "clippers", "lakers", "grizzlies", "heat", "bucks",
        "timberwolves", "wolves", "pelicans", "knicks", "thunder",
        "magic", "76ers", "sixers", "suns", "trail blazers", "blazers",
        "kings", "spurs", "raptors", "jazz", "wizards",
    ],

    # ------------------------------------------------------------------
    Category.MLB: [
        "mlb", "world series", "baseball", "home run derby", "all-star game",
        "al pennant", "nl pennant", "wild card",
        # All 30 franchises
        "arizona diamondbacks", "atlanta braves", "baltimore orioles",
        "boston red sox", "chicago cubs", "chicago white sox",
        "cincinnati reds", "cleveland guardians", "colorado rockies",
        "detroit tigers", "houston astros", "kansas city royals",
        "los angeles angels", "los angeles dodgers", "miami marlins",
        "milwaukee brewers", "minnesota twins", "new york mets",
        "new york yankees", "oakland athletics", "philadelphia phillies",
        "pittsburgh pirates", "san diego padres", "san francisco giants",
        "seattle mariners", "st. louis cardinals", "tampa bay rays",
        "texas rangers", "toronto blue jays", "washington nationals",
        # Short names
        "diamondbacks", "d-backs", "braves", "orioles", "red sox",
        "cubs", "white sox", "reds", "guardians", "rockies",
        "tigers", "astros", "royals", "angels", "dodgers",
        "marlins", "brewers", "twins", "mets", "yankees",
        "athletics", "phillies", "pirates", "padres",
        "mariners", "cardinals", "rays", "rangers", "blue jays", "nationals",
    ],

    # ------------------------------------------------------------------
    Category.NHL: [
        "nhl", "hockey", "stanley cup",
        # All 32 franchises
        "anaheim ducks", "arizona coyotes", "boston bruins", "buffalo sabres",
        "calgary flames", "carolina hurricanes", "chicago blackhawks",
        "colorado avalanche", "columbus blue jackets", "dallas stars",
        "detroit red wings", "edmonton oilers", "florida panthers",
        "los angeles kings", "minnesota wild", "montreal canadiens",
        "nashville predators", "new jersey devils", "new york islanders",
        "new york rangers", "ottawa senators", "philadelphia flyers",
        "pittsburgh penguins", "san jose sharks", "seattle kraken",
        "st. louis blues", "tampa bay lightning", "toronto maple leafs",
        "utah hockey club", "vancouver canucks", "vegas golden knights",
        "washington capitals", "winnipeg jets",
        # Short names
        "ducks", "coyotes", "bruins", "sabres", "flames", "hurricanes",
        "blackhawks", "avalanche", "blue jackets", "stars", "red wings",
        "oilers", "kings", "wild", "canadiens", "habs",
        "predators", "devils", "islanders", "rangers", "senators",
        "flyers", "penguins", "sharks", "kraken", "blues",
        "lightning", "maple leafs", "leafs", "canucks", "golden knights",
        "capitals", "jets",
    ],

    # ------------------------------------------------------------------
    Category.NCAAF: [
        "ncaaf", "college football", "cfp", "college football playoff",
        "heisman", "bowl game", "rose bowl", "sugar bowl", "orange bowl",
        "cotton bowl", "fiesta bowl", "peach bowl", "alamo bowl",
        "national championship", "college football national",
    ],

    # ------------------------------------------------------------------
    Category.NCAAB: [
        "ncaab", "march madness", "college basketball", "final four",
        "elite eight", "sweet sixteen", "ncaa tournament", "ncaa basketball",
        "college hoops",
    ],

    # ------------------------------------------------------------------
    Category.UFC_MMA: [
        "ufc", "mma", "fight night", "bellator", "pfl", "championship bout",
        "mixed martial arts", "octagon", "cage fight", "submission",
        "knockout", "tko", "lightweight title", "heavyweight title",
        "welterweight title", "middleweight title", "featherweight title",
        "bantamweight title",
    ],

    # ------------------------------------------------------------------
    Category.BOXING: [
        "boxing", "heavyweight", "middleweight", "light heavyweight",
        "welterweight", "featherweight", "bantamweight", "lightweight",
        "title fight", "wbc", "wba", "ibf", "wbo", "world title",
        "prizefight", "bout",
    ],

    # ------------------------------------------------------------------
    Category.NASCAR: [
        "nascar", "daytona 500", "daytona", "cup series", "xfinity series",
        "truck series", "talladega", "bristol motor speedway",
        "charlotte motor speedway", "martinsville", "bristol",
        "stock car",
    ],

    # ------------------------------------------------------------------
    Category.WNBA: [
        "wnba", "women's basketball", "women's nba", "wnba finals",
        "wnba championship", "las vegas aces", "new york liberty",
        "seattle storm", "chicago sky", "connecticut sun",
        "minnesota lynx", "phoenix mercury", "atlanta dream",
        "indiana fever", "washington mystics", "dallas wings",
        "los angeles sparks",
    ],

    # ------------------------------------------------------------------
    Category.F1: [
        "formula 1", "formula one", "grand prix", "f1 championship",
        "f1 world championship", "f1 season", "f1 race",
        # Drivers (high-profile)
        "verstappen", "hamilton", "leclerc", "norris", "russell",
        "perez", "alonso", "sainz", "piastri", "bottas", "zhou",
        "stroll", "hulkenberg", "gasly", "ocon", "tsunoda",
        "magnussen", "albon", "sargeant", "de vries", "lawson",
        # Constructors
        "red bull racing", "mercedes amg", "ferrari", "mclaren",
        "aston martin", "alpine f1", "williams f1", "alphatauri",
        "alfa romeo", "haas f1",
        # Venues (add the most iconic ones)
        "monaco grand prix", "monaco gp", "silverstone grand prix",
        "monza grand prix", "spa grand prix", "suzuka grand prix",
    ],

    # ------------------------------------------------------------------
    Category.MOTOGP: [
        "motogp", "moto gp", "moto2", "moto3", "motogp championship",
        "motogp season", "motogp race",
    ],

    # ------------------------------------------------------------------
    Category.MLS: [
        "mls", "major league soccer", "mls cup", "mls playoffs",
        "supporters shield", "lafc", "la galaxy", "inter miami",
        "new england revolution", "seattle sounders", "portland timbers",
        "nycfc", "new york red bulls", "atlanta united",
        "orlando city", "chicago fire", "toronto fc", "cf montreal",
        "new york city fc", "red bulls",
    ],

    # ------------------------------------------------------------------
    Category.EPL: [
        "premier league", "epl", "fa cup", "league cup", "carabao cup",
        "english football", "english premier",
        # All 20 EPL clubs (common names cover most seasons)
        "arsenal", "aston villa", "bournemouth", "brentford",
        "brighton", "burnley", "chelsea", "crystal palace",
        "everton", "fulham", "ipswich town", "leicester city",
        "liverpool", "luton town", "manchester city", "manchester united",
        "newcastle united", "nottingham forest", "sheffield united",
        "southampton", "tottenham hotspur", "tottenham", "spurs",
        "west ham", "wolverhampton", "wolves",
        "man city", "man united", "man utd",
    ],

    # ------------------------------------------------------------------
    Category.LA_LIGA: [
        "la liga", "laliga", "spanish football", "spanish league",
        "real madrid", "fc barcelona", "atletico madrid", "atletico",
        "sevilla", "real sociedad", "athletic bilbao", "villarreal",
        "real betis", "valencia", "getafe", "osasuna", "rayo vallecano",
        "celta vigo", "girona", "almeria", "cadiz", "granada",
    ],

    # ------------------------------------------------------------------
    Category.BUNDESLIGA: [
        "bundesliga", "german football", "german league",
        "bayern munich", "borussia dortmund", "rb leipzig",
        "bayer leverkusen", "eintracht frankfurt", "wolfsburg",
        "borussia monchengladbach", "freiburg", "union berlin",
        "mainz", "hoffenheim", "augsburg", "bochum", "werder bremen",
        "hertha berlin", "darmstadt", "heidenheim",
        "bvb", "fcb munich",
    ],

    # ------------------------------------------------------------------
    Category.SERIE_A: [
        "serie a", "italian football", "italian league",
        "juventus", "inter milan", "ac milan", "napoli", "as roma",
        "lazio", "atalanta", "fiorentina", "torino", "udinese",
        "bologna", "sassuolo", "empoli", "monza", "salernitana",
        "lecce", "cagliari", "genoa", "hellas verona", "frosinone",
        "inter fc",
    ],

    # ------------------------------------------------------------------
    Category.LIGUE_1: [
        "ligue 1", "ligue1", "french football", "french league",
        "paris saint-germain", "psg", "marseille", "lyon",
        "monaco", "nice", "rennes", "lens", "lille",
        "toulouse", "nantes", "montpellier", "reims",
        "lorient", "brest", "clermont", "strasbourg",
        "metz", "le havre",
    ],

    # ------------------------------------------------------------------
    Category.CHAMPIONS_LEAGUE: [
        "champions league", "ucl", "uefa champions", "cl final",
        "champions league final", "champions league draw",
        "champions league group",
    ],

    # ------------------------------------------------------------------
    Category.EUROPA_LEAGUE: [
        "europa league", "uel", "conference league", "uecl",
        "uefa europa", "europa conference",
    ],

    # ------------------------------------------------------------------
    Category.WORLD_CUP: [
        "world cup", "fifa world cup", "fifa", "world cup qualifier",
        "world cup final", "world cup group", "world cup draw",
        "copa america", "euros", "euro 2024", "euro 2026",
        "european championship",
    ],

    # ------------------------------------------------------------------
    Category.TENNIS: [
        "atp", "wta", "grand slam", "wimbledon", "us open tennis",
        "french open", "australian open", "roland garros",
        "tennis", "tennis tournament",
        # Top players
        "djokovic", "alcaraz", "sinner", "swiatek", "medvedev",
        "zverev", "tsitsipas", "rublev", "fritz", "tiafoe",
        "sabalenka", "gauff", "rybakina", "pegula", "vondrousova",
        "nadal", "federer", "serena", "osaka",
        # Tournament levels
        "masters 1000", "atp finals", "wta finals",
    ],

    # ------------------------------------------------------------------
    Category.GOLF: [
        "pga", "liv golf", "masters", "the masters", "augusta",
        "us open golf", "british open", "the open championship",
        "ryder cup", "presidents cup", "tour championship",
        "players championship", "genesis invitational",
        "golf tournament", "golf major",
        # Top players
        "tiger woods", "rory mcilroy", "dustin johnson", "jon rahm",
        "scottie scheffler", "brooks koepka", "bryson dechambeau",
        "phil mickelson", "jordan spieth", "justin thomas",
        "xander schauffele", "patrick cantlay", "collin morikawa",
    ],

    # ------------------------------------------------------------------
    Category.CRICKET: [
        "ipl", "indian premier league", "cricket", "t20", "t20 world cup",
        "test cricket", "ashes", "odi cricket", "one day international",
        "bbl", "big bash", "psl", "cricket world cup",
        "england cricket", "india cricket", "australia cricket",
    ],

    # ------------------------------------------------------------------
    Category.ESPORTS: [
        "esports", "e-sports", "league of legends", "counter-strike",
        "cs2", "dota", "dota 2", "valorant", "worlds", "lol worlds",
        "overwatch league", "call of duty league", "rocket league",
        "apex legends", "fortnite tournament", "starcraft",
        "hearthstone", "rainbow six", "pubg", "gaming tournament",
    ],

    # ------------------------------------------------------------------
    Category.OLYMPICS: [
        "olympics", "olympic games", "summer olympics", "winter olympics",
        "paralympics", "olympiad", "olympic gold", "olympic medal",
        "olympic champion",
    ],

    # ------------------------------------------------------------------
    Category.CRYPTO: [
        "bitcoin", "btc", "ethereum", "crypto", "cryptocurrency",
        "blockchain", "dogecoin", "xrp", "ripple", "cardano",
        "polkadot", "chainlink", "polygon", "avalanche", "avax",
        "solana", "bnb", "binance", "tron", "litecoin", "shiba inu",
        "defi", "nft", "web3", "altcoin", "stablecoin",
        "coinbase", "binance exchange", "kraken exchange",
        "crypto market", "digital asset", "token price",
        "uniswap", "aave", "compound", "maker",
        "pepe coin", "floki", "arbitrum", "optimism",
        "near protocol", "aptos", "sui", "celestia",
        "token", "coin price",
    ],

    # ------------------------------------------------------------------
    Category.POLITICS: [
        "president", "election", "congress", "senate", "house of representatives",
        "trump", "biden", "harris", "governor", "democrat", "republican",
        "vote", "impeach", "supreme court", "white house", "oval office",
        "midterm", "primary election", "general election", "ballot",
        "polling", "approval rating", "veto", "filibuster",
        "inauguration", "cabinet", "speaker of the house",
        "attorney general", "secretary of state",
        "uk election", "uk prime minister", "labour party", "tory",
        "eu election", "european parliament", "nato",
    ],

    # ------------------------------------------------------------------
    Category.ENTERTAINMENT: [
        "oscar", "oscars", "academy award", "emmy", "grammy",
        "golden globe", "bafta", "movie", "film", "box office",
        "album", "spotify", "billboard", "streaming",
        "netflix", "disney", "hbo", "apple tv",
        "number one song", "best picture", "best actor", "best actress",
        "music chart", "chart topper", "concert tour",
        "celebrity", "reality tv", "tv show", "season finale",
        "superhero", "marvel", "dc comics",
    ],

    # ------------------------------------------------------------------
    Category.ECONOMICS: [
        "gdp", "inflation", "federal reserve", "interest rate",
        "unemployment", "recession", "stock market", "s&p 500",
        "dow jones", "nasdaq", "treasury yield", "bond market",
        "trade deficit", "trade war", "tariff", "imf", "world bank",
        "cpi", "ppi", "jobs report", "fed meeting", "fomc",
        "rate hike", "rate cut", "quantitative easing",
        "us economy", "global economy",
    ],

    # ------------------------------------------------------------------
    Category.SCIENCE: [
        "nasa", "spacex", "mars", "moon landing", "moon mission",
        "climate change", "climate", "asteroid", "rocket launch",
        "iss", "international space station", "james webb",
        "ai model", "artificial intelligence", "chatgpt",
        "fusion energy", "nuclear fusion", "cern",
        "vaccine", "pandemic", "disease outbreak",
    ],

    # ------------------------------------------------------------------
    Category.WEATHER: [
        "hurricane", "earthquake", "temperature record", "wildfire",
        "tornado", "typhoon", "flood", "drought",
        "heat wave", "blizzard", "snowstorm",
    ],
}


# ---------------------------------------------------------------------------
# Word-boundary keywords
# ---------------------------------------------------------------------------
# Some keywords are too short or ambiguous to match with plain substring
# checks.  We compile them once here and test them separately in detect_category.
#
# Format: {Category: [pattern, ...]}

_WB_KEYWORD_STRINGS: dict[Category, list[str]] = {
    Category.F1: ["f1"],
    Category.CRICKET: ["t20"],
    Category.CRYPTO: ["sol", "eth", "bnb", "ada", "dot", "link", "matic", "avax"],
    Category.ECONOMICS: ["fed", "gdp", "cpi", "ppi"],
    Category.GOLF: ["pga"],
    Category.TENNIS: ["atp", "wta"],
}

# Pre-compile: {Category: list[compiled_pattern]}
_WB_PATTERNS: dict[Category, list[re.Pattern[str]]] = {
    cat: [re.compile(rf"\b{re.escape(kw)}\b", re.IGNORECASE) for kw in kws]
    for cat, kws in _WB_KEYWORD_STRINGS.items()
}


# ---------------------------------------------------------------------------
# Category → Sport backward-compatibility mapping
# ---------------------------------------------------------------------------

CATEGORY_TO_SPORT_ENUM: dict[Category, Sport] = {
    Category.NFL: Sport.NFL,
    Category.NBA: Sport.NBA,
    Category.MLB: Sport.MLB,
    Category.NHL: Sport.NHL,
    Category.UFC_MMA: Sport.UFC,
    Category.MLS: Sport.MLS,
    Category.NCAAB: Sport.NCAAB,
    Category.NCAAF: Sport.NCAAF,
    # Categories with no direct Sport enum value
    Category.BOXING: Sport.UNKNOWN,
    Category.NASCAR: Sport.UNKNOWN,
    Category.WNBA: Sport.UNKNOWN,
    Category.F1: Sport.UNKNOWN,
    Category.MOTOGP: Sport.UNKNOWN,
    Category.EPL: Sport.UNKNOWN,
    Category.LA_LIGA: Sport.UNKNOWN,
    Category.BUNDESLIGA: Sport.UNKNOWN,
    Category.SERIE_A: Sport.UNKNOWN,
    Category.LIGUE_1: Sport.UNKNOWN,
    Category.CHAMPIONS_LEAGUE: Sport.UNKNOWN,
    Category.EUROPA_LEAGUE: Sport.UNKNOWN,
    Category.WORLD_CUP: Sport.UNKNOWN,
    Category.TENNIS: Sport.UNKNOWN,
    Category.GOLF: Sport.UNKNOWN,
    Category.CRICKET: Sport.UNKNOWN,
    Category.ESPORTS: Sport.UNKNOWN,
    Category.OLYMPICS: Sport.UNKNOWN,
    Category.CRYPTO: Sport.UNKNOWN,
    Category.POLITICS: Sport.UNKNOWN,
    Category.ENTERTAINMENT: Sport.UNKNOWN,
    Category.ECONOMICS: Sport.UNKNOWN,
    Category.SCIENCE: Sport.UNKNOWN,
    Category.WEATHER: Sport.UNKNOWN,
    Category.OTHER: Sport.UNKNOWN,
}

# ---------------------------------------------------------------------------
# Sets for quick membership tests
# ---------------------------------------------------------------------------

_SPORTS_CATEGORIES: frozenset[Category] = frozenset({
    Category.NFL,
    Category.NBA,
    Category.MLB,
    Category.NHL,
    Category.NCAAF,
    Category.NCAAB,
    Category.UFC_MMA,
    Category.BOXING,
    Category.NASCAR,
    Category.WNBA,
    Category.F1,
    Category.MOTOGP,
    Category.MLS,
    Category.EPL,
    Category.LA_LIGA,
    Category.BUNDESLIGA,
    Category.SERIE_A,
    Category.LIGUE_1,
    Category.CHAMPIONS_LEAGUE,
    Category.EUROPA_LEAGUE,
    Category.WORLD_CUP,
    Category.TENNIS,
    Category.GOLF,
    Category.CRICKET,
    Category.ESPORTS,
    Category.OLYMPICS,
})


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------


def detect_category(
    title: str,
    event_title: str | None = None,
    tags: list[str] | None = None,
) -> Category:
    """Score each category by keyword matches and return the best match.

    Scoring:
    - Each plain keyword match in the combined text: +1 point.
    - Each word-boundary pattern match: +1 point.
    - Tags are also searched; a tag match is worth +2 (tags are more curated).
    - The category with the highest total score wins.
    - Ties are broken by the order categories are iterated (dict insertion order).
    - If no category scores > 0, returns Category.OTHER.

    Parameters
    ----------
    title:
        The market question / title string (required).
    event_title:
        Optional parent event title from Gamma's ``events[0].title``.
    tags:
        Optional list of tags from Gamma.  May be None; handled gracefully.
    """
    # Build combined search text (lower-cased once)
    parts = [title]
    if event_title:
        parts.append(event_title)
    combined = " ".join(parts).lower()

    # Build tags text separately so we can weight it differently
    tags_text = ""
    if tags:
        tags_text = " ".join(str(t) for t in tags if t).lower()

    scores: dict[Category, int] = {}

    for cat, keywords in CATEGORY_KEYWORDS.items():
        score = 0
        for kw in keywords:
            if kw in combined:
                score += 1
            if tags_text and kw in tags_text:
                score += 2  # tags are authoritative
        # Word-boundary patterns for this category (if any)
        if cat in _WB_PATTERNS:
            for pat in _WB_PATTERNS[cat]:
                if pat.search(combined):
                    score += 1
                if tags_text and pat.search(tags_text):
                    score += 2
        if score > 0:
            scores[cat] = score

    if not scores:
        return Category.OTHER

    best_cat = max(scores, key=lambda c: scores[c])
    return best_cat


# ---------------------------------------------------------------------------
# Helper predicates
# ---------------------------------------------------------------------------


def is_sports_category(cat: Category) -> bool:
    """Return True if the category represents a sporting event or league."""
    return cat in _SPORTS_CATEGORIES


def is_crypto_category(cat: Category) -> bool:
    """Return True if the category is the crypto / digital-asset vertical."""
    return cat is Category.CRYPTO
