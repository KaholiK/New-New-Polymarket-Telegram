"""Poisson simulation for score-based sports (soccer, baseball, hockey)."""

from __future__ import annotations

import numpy as np

from apex.core.models import ModelEstimate
from apex.utils.math_utils import clamp_prob


class PoissonModel:
    """Simulate N games with Poisson-distributed team scores.

    Attack = team_goals_for / league_avg
    Defense = league_avg / team_goals_against  (higher → stronger D)
    Lambda = team_attack * opponent_defense * league_avg_goals
    """

    def __init__(self, league_avg_goals: float, n_sims: int = 10000, seed: int | None = None) -> None:
        self.league_avg_goals = float(max(0.5, league_avg_goals))
        self.n_sims = int(n_sims)
        self._rng = np.random.default_rng(seed)

    def lambdas(
        self,
        home_gf: float,
        home_ga: float,
        away_gf: float,
        away_ga: float,
        home_boost: float = 1.0,
    ) -> tuple[float, float]:
        """Compute per-team expected goals.

        Floor scoring rates at 0.1 to avoid zero-lambda degenerate simulation.
        """
        if self.league_avg_goals <= 0:
            return 0.1, 0.1
        home_att = home_gf / self.league_avg_goals
        home_def = self.league_avg_goals / max(0.1, home_ga)
        away_att = away_gf / self.league_avg_goals
        away_def = self.league_avg_goals / max(0.1, away_ga)
        home_lambda = max(0.1, home_att * away_def * self.league_avg_goals * home_boost)
        away_lambda = max(0.1, away_att * home_def * self.league_avg_goals)
        return home_lambda, away_lambda

    def simulate(
        self,
        home_lambda: float,
        away_lambda: float,
    ) -> tuple[np.ndarray, np.ndarray]:
        home = self._rng.poisson(home_lambda, size=self.n_sims)
        away = self._rng.poisson(away_lambda, size=self.n_sims)
        return home, away

    def predict(
        self,
        home_gf: float,
        home_ga: float,
        away_gf: float,
        away_ga: float,
    ) -> dict[str, float]:
        hl, al = self.lambdas(home_gf, home_ga, away_gf, away_ga)
        home, away = self.simulate(hl, al)
        home_win = float((home > away).mean())
        away_win = float((away > home).mean())
        draw = float((home == away).mean())
        return {
            "home_win": clamp_prob(home_win),
            "away_win": clamp_prob(away_win),
            "draw": clamp_prob(draw),
            "home_lambda": hl,
            "away_lambda": al,
        }

    def predict_total(
        self,
        home_gf: float,
        home_ga: float,
        away_gf: float,
        away_ga: float,
        line: float,
    ) -> dict[str, float]:
        hl, al = self.lambdas(home_gf, home_ga, away_gf, away_ga)
        home, away = self.simulate(hl, al)
        totals = home + away
        over = float((totals > line).mean())
        push = float((totals == line).mean())
        under = 1.0 - over - push
        return {"over": clamp_prob(over), "under": clamp_prob(under), "push": push}

    def predict_estimate(
        self,
        home_gf: float,
        home_ga: float,
        away_gf: float,
        away_ga: float,
    ) -> ModelEstimate:
        res = self.predict(home_gf, home_ga, away_gf, away_ga)
        factors = [
            f"Home λ={res['home_lambda']:.2f}",
            f"Away λ={res['away_lambda']:.2f}",
            f"Draw prob={res['draw']:.2%}",
        ]
        return ModelEstimate(
            model_name="poisson",
            probability=res["home_win"],
            uncertainty=0.07,
            confidence=0.55,
            factors=factors,
        )
