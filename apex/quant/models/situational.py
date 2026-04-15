"""Rest days, travel, altitude, B2B, dome/outdoor, motivation adjustments.

Each adjustment is a delta to home win probability, capped at ±0.08 in aggregate.
"""

from __future__ import annotations

from dataclasses import dataclass

from apex.core.models import ModelEstimate
from apex.utils.math_utils import clamp_prob

# Venue altitude (meters) and dome status by team
VENUE_DATA: dict[str, dict] = {
    # NBA
    "Denver Nuggets": {"altitude": 1609, "dome": True},
    "Utah Jazz": {"altitude": 1288, "dome": True},
    "Phoenix Suns": {"altitude": 331, "dome": True},
    # NFL
    "Denver Broncos": {"altitude": 1609, "dome": False},
    "Minnesota Vikings": {"altitude": 260, "dome": True},
    "Atlanta Falcons": {"altitude": 320, "dome": True},
    "New Orleans Saints": {"altitude": 1, "dome": True},
    "Las Vegas Raiders": {"altitude": 610, "dome": True},
    "Los Angeles Rams": {"altitude": 71, "dome": True},
    "Houston Texans": {"altitude": 15, "dome": True},
    "Detroit Lions": {"altitude": 180, "dome": True},
    "Indianapolis Colts": {"altitude": 220, "dome": True},
    "Arizona Cardinals": {"altitude": 331, "dome": True},
    "Dallas Cowboys": {"altitude": 131, "dome": True},
    # MLS
    "Real Salt Lake": {"altitude": 1288, "dome": False},
    "Colorado Rapids": {"altitude": 1609, "dome": False},
}


@dataclass
class SituationalInputs:
    home_team: str
    away_team: str
    home_rest_days: int = 2
    away_rest_days: int = 2
    home_back_to_back: bool = False
    away_back_to_back: bool = False
    travel_timezone_shift: int = 0  # number of timezones away team crossed
    altitude_diff_meters: float = 0.0  # how much higher the venue is for away team
    home_playoff_elimination: bool = False
    away_playoff_elimination: bool = False
    is_rivalry: bool = False


def situational_adjustment(inp: SituationalInputs, sport: str = "NBA") -> tuple[float, list[str]]:
    """Sum of situational deltas (home win prob). Total capped at ±0.08."""
    factors: list[str] = []
    adj = 0.0

    rest_diff = inp.home_rest_days - inp.away_rest_days
    if abs(rest_diff) >= 2:
        delta = 0.007 * rest_diff  # +0.021 for 3-day advantage
        adj += delta
        factors.append(f"rest diff {rest_diff:+d} days → {delta:+.3f}")

    if inp.home_back_to_back and sport.upper() == "NBA":
        adj -= 0.035
        factors.append("home on B2B → -0.035")
    if inp.away_back_to_back and sport.upper() == "NBA":
        adj += 0.035
        factors.append("away on B2B → +0.035")

    if inp.travel_timezone_shift >= 2:
        delta = 0.008 * min(3, inp.travel_timezone_shift)
        adj += delta
        factors.append(f"away crossed {inp.travel_timezone_shift} TZ → +{delta:.3f}")

    if inp.altitude_diff_meters >= 1000:
        adj += 0.015
        factors.append(f"altitude advantage (+{inp.altitude_diff_meters:.0f}m) → +0.015")
    if inp.altitude_diff_meters >= 2000:
        adj += 0.005  # Mexico City-style
        factors.append("extreme altitude (+0.020 total)")

    if inp.home_playoff_elimination and not inp.away_playoff_elimination:
        adj += 0.025
        factors.append("home faces elimination → +0.025 motivation")
    if inp.away_playoff_elimination and not inp.home_playoff_elimination:
        adj -= 0.025
        factors.append("away faces elimination → -0.025")

    if inp.is_rivalry:
        adj += 0.010
        factors.append("rivalry game → +0.010 home")

    # Cap aggregate ± 0.08
    adj = max(-0.08, min(0.08, adj))
    return adj, factors


class SituationalModel:
    """Returns a delta to whatever baseline probability the caller passes in."""

    def apply(
        self, base_prob: float, inp: SituationalInputs, sport: str = "NBA"
    ) -> tuple[float, list[str]]:
        delta, factors = situational_adjustment(inp, sport)
        return clamp_prob(base_prob + delta), factors

    def predict_estimate(
        self, base_prob: float, inp: SituationalInputs, sport: str = "NBA"
    ) -> ModelEstimate:
        new_prob, factors = self.apply(base_prob, inp, sport)
        return ModelEstimate(
            model_name="situational",
            probability=new_prob,
            uncertainty=0.04,
            confidence=0.5,
            factors=factors or ["no material situational edge"],
        )
