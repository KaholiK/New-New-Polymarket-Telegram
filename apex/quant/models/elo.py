"""Per-team Elo with sport-specific K-factors, home advantage, season regression."""

from __future__ import annotations

from dataclasses import dataclass

from apex.core.models import ModelEstimate
from apex.utils.math_utils import clamp_prob

STARTING_ELO = 1500.0

# Sport-specific K-factors (early-season, late-season)
K_FACTORS = {
    "NBA": (20.0, 12.0),
    "NFL": (20.0, 12.0),
    "MLB": (10.0, 6.0),  # lower variance per game
    "NHL": (20.0, 12.0),
    "UFC": (32.0, 32.0),  # single-fight sport
    "MLS": (20.0, 12.0),
}

# Elo-point home advantage
HOME_ADVANTAGE = {
    "NBA": 65.0,
    "NFL": 48.0,
    "MLB": 24.0,
    "NHL": 33.0,
    "UFC": 0.0,  # no home for fight
    "MLS": 60.0,
}

# Early-season threshold — first 20% of games use high K
EARLY_SEASON_GAME_COUNT = {
    "NBA": 16,  # 82-game season → ~20%
    "NFL": 4,
    "MLB": 32,
    "NHL": 16,
    "UFC": 0,
    "MLS": 7,
}


def expected_score(elo_a: float, elo_b: float) -> float:
    """Standard Elo expected score for team A."""
    return 1.0 / (1.0 + 10.0 ** ((elo_b - elo_a) / 400.0))


def k_factor(sport: str, games_played: int) -> float:
    """K-factor adapts to early vs late season."""
    sport_up = sport.upper()
    early_k, late_k = K_FACTORS.get(sport_up, (20.0, 12.0))
    threshold = EARLY_SEASON_GAME_COUNT.get(sport_up, 10)
    return early_k if games_played < threshold else late_k


def season_regression(elo: float, regression_factor: float = 0.25) -> float:
    """Regress Elo toward 1500 at season start. Default: carry 75%, regress 25%."""
    return elo * (1.0 - regression_factor) + STARTING_ELO * regression_factor


@dataclass
class EloEntry:
    elo: float = STARTING_ELO
    games_played: int = 0


class EloModel:
    """Stateful Elo with optional persistence via db.upsert_elo()."""

    def __init__(self, sport: str) -> None:
        self.sport = sport.upper()
        self.ratings: dict[str, EloEntry] = {}

    def get(self, team: str) -> float:
        return self.ratings.get(team, EloEntry()).elo

    def get_games(self, team: str) -> int:
        return self.ratings.get(team, EloEntry()).games_played

    def set(self, team: str, elo: float, games_played: int = 0) -> None:
        self.ratings[team] = EloEntry(elo=elo, games_played=games_played)

    def bulk_load(self, rows: dict[str, float]) -> None:
        for t, e in rows.items():
            if t not in self.ratings:
                self.ratings[t] = EloEntry(elo=e, games_played=0)
            else:
                self.ratings[t].elo = e

    def predict(self, home: str, away: str, home_is_home: bool = True) -> float:
        """Return probability that `home` beats `away`."""
        ea = self.get(home)
        eb = self.get(away)
        adj = HOME_ADVANTAGE.get(self.sport, 0.0) if home_is_home else 0.0
        p = expected_score(ea + adj, eb)
        return clamp_prob(p)

    def predict_estimate(self, home: str, away: str) -> ModelEstimate:
        p = self.predict(home, away)
        ea, eb = self.get(home), self.get(away)
        factors = [
            f"Elo {home}={ea:.0f} vs {away}={eb:.0f}",
            f"home advantage +{HOME_ADVANTAGE.get(self.sport, 0.0):.0f}",
        ]
        uncertainty = 0.05 if (self.get_games(home) > 10 and self.get_games(away) > 10) else 0.08
        confidence = 0.8 if uncertainty <= 0.05 else 0.5
        return ModelEstimate(
            model_name="elo",
            probability=p,
            uncertainty=uncertainty,
            confidence=confidence,
            factors=factors,
        )

    def update(
        self, home: str, away: str, home_won: bool, home_is_home: bool = True
    ) -> tuple[float, float]:
        """Apply Elo update after a completed game. Returns (home_delta, away_delta)."""
        self.ratings.setdefault(home, EloEntry())
        self.ratings.setdefault(away, EloEntry())

        adj = HOME_ADVANTAGE.get(self.sport, 0.0) if home_is_home else 0.0
        ea = self.ratings[home].elo
        eb = self.ratings[away].elo
        expected_home = expected_score(ea + adj, eb)
        actual_home = 1.0 if home_won else 0.0

        k_home = k_factor(self.sport, self.ratings[home].games_played)
        k_away = k_factor(self.sport, self.ratings[away].games_played)

        delta_home = k_home * (actual_home - expected_home)
        delta_away = k_away * ((1.0 - actual_home) - (1.0 - expected_home))

        self.ratings[home].elo += delta_home
        self.ratings[away].elo += delta_away
        self.ratings[home].games_played += 1
        self.ratings[away].games_played += 1

        return delta_home, delta_away

    def regress_all(self, regression_factor: float = 0.25) -> None:
        """Season-start regression: carry (1-rf) of prior Elo, regress rf toward 1500."""
        for team, entry in self.ratings.items():
            entry.elo = season_regression(entry.elo, regression_factor)
            entry.games_played = 0
