"""Player absence impact on win probability, per sport and position tier."""

from __future__ import annotations

from dataclasses import dataclass

from apex.core.models import InjuryNote, ModelEstimate
from apex.utils.math_utils import clamp_prob

# Impact on team win probability if player is OUT (status=OUT)
PLAYER_IMPACT: dict[str, dict[str, float]] = {
    "NBA": {
        "mvp": 0.12,      # LeBron, Jokic, Giannis, Embiid, SGA
        "allstar": 0.07,
        "starter": 0.03,
        "rotation": 0.01,
    },
    "NFL": {
        "starting_qb": 0.15,
        "elite_skill": 0.04,  # elite RB/WR
        "ol_starter": 0.02,
        "defense_starter": 0.02,
    },
    "MLB": {
        "ace_starter": 0.06,
        "mid_starter": 0.03,
        "position_player": 0.015,
    },
    "NHL": {
        "goalie_starter": 0.07,
        "top_forward": 0.03,
        "top_d": 0.025,
    },
}

STATUS_MULTIPLIER: dict[str, float] = {
    "OUT": 1.0,
    "DOUBTFUL": 0.75,
    "QUESTIONABLE": 0.35,
    "PROBABLE": 0.10,
    "DAY-TO-DAY": 0.15,
}


# Curated top players per sport.
# This is intentionally small — calibration handles the long tail.
TOP_PLAYERS: dict[str, dict[str, tuple[str, str]]] = {
    "NBA": {
        # player name (lowercased) → (team canonical, tier)
        "lebron james": ("Los Angeles Lakers", "mvp"),
        "anthony davis": ("Los Angeles Lakers", "allstar"),
        "nikola jokic": ("Denver Nuggets", "mvp"),
        "giannis antetokounmpo": ("Milwaukee Bucks", "mvp"),
        "joel embiid": ("Philadelphia 76ers", "mvp"),
        "shai gilgeous-alexander": ("Oklahoma City Thunder", "mvp"),
        "luka doncic": ("Dallas Mavericks", "mvp"),
        "stephen curry": ("Golden State Warriors", "mvp"),
        "jayson tatum": ("Boston Celtics", "mvp"),
        "kevin durant": ("Phoenix Suns", "allstar"),
        "kawhi leonard": ("LA Clippers", "allstar"),
        "devin booker": ("Phoenix Suns", "allstar"),
    },
    "NFL": {
        "patrick mahomes": ("Kansas City Chiefs", "starting_qb"),
        "josh allen": ("Buffalo Bills", "starting_qb"),
        "lamar jackson": ("Baltimore Ravens", "starting_qb"),
        "jalen hurts": ("Philadelphia Eagles", "starting_qb"),
        "joe burrow": ("Cincinnati Bengals", "starting_qb"),
        "dak prescott": ("Dallas Cowboys", "starting_qb"),
    },
    "MLB": {
        "gerrit cole": ("New York Yankees", "ace_starter"),
        "shohei ohtani": ("Los Angeles Dodgers", "ace_starter"),
    },
    "NHL": {
        "connor mcdavid": ("Edmonton Oilers", "top_forward"),
        "igor shesterkin": ("New York Rangers", "goalie_starter"),
    },
}


def lookup_player(player: str, sport: str) -> tuple[str, str] | None:
    """Return (team, tier) if player is curated, else None."""
    roster = TOP_PLAYERS.get(sport.upper(), {})
    return roster.get((player or "").strip().lower())


@dataclass
class InjuryImpact:
    team: str
    total_impact: float  # sum of (tier_value × status_mult) for all injured players on team
    factors: list[str]


def compute_team_impact(sport: str, team: str, injuries: list[InjuryNote]) -> InjuryImpact:
    sport_up = sport.upper()
    factors: list[str] = []
    total = 0.0
    for inj in injuries:
        if inj.team and inj.team != team:
            # Try fuzzy check — many ESPN feeds use full team name
            if team.lower() not in inj.team.lower() and inj.team.lower() not in team.lower():
                continue
        hit = lookup_player(inj.player, sport_up)
        if hit is None:
            continue
        player_team, tier = hit
        if team and player_team and team != player_team:
            continue
        impact_base = PLAYER_IMPACT.get(sport_up, {}).get(tier, 0.0)
        status_mult = STATUS_MULTIPLIER.get(inj.status.upper(), 0.0)
        contribution = impact_base * status_mult
        if contribution == 0:
            continue
        total += contribution
        factors.append(
            f"{inj.player} ({tier}) {inj.status} → {contribution:+.3f}"
        )
    return InjuryImpact(team=team, total_impact=total, factors=factors)


class InjuryAdjusterModel:
    def predict_estimate(
        self,
        base_prob: float,
        sport: str,
        home_team: str,
        away_team: str,
        injuries: list[InjuryNote],
    ) -> ModelEstimate:
        home_impact = compute_team_impact(sport, home_team, injuries)
        away_impact = compute_team_impact(sport, away_team, injuries)
        # Home injuries reduce home win prob; away injuries increase it
        delta = away_impact.total_impact - home_impact.total_impact
        new_prob = clamp_prob(base_prob + delta)
        factors = home_impact.factors + away_impact.factors
        if not factors:
            factors = ["no material injury impact"]
        # Confidence scales with magnitude — small deltas mean low impact model
        confidence = min(0.7, 0.3 + abs(delta) * 4.0)
        uncertainty = 0.05
        return ModelEstimate(
            model_name="injury",
            probability=new_prob,
            uncertainty=uncertainty,
            confidence=confidence,
            factors=factors,
        )
