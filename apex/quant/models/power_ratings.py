"""Power ratings from ESPN OFF/DEF stats + Pythagorean win expectation."""

from __future__ import annotations

from apex.core.models import ModelEstimate
from apex.quant.data.stats_ingestor import LEAGUE_AVG_PPG, PYTH_EXPONENT, TeamStats, off_def_ratings
from apex.utils.math_utils import clamp_prob


class PowerRatingsModel:
    def __init__(self, sport: str) -> None:
        self.sport = sport.upper()
        self._stats_by_team: dict[str, TeamStats] = {}
        self._ratings: dict[str, tuple[float, float]] = {}

    def load(self, stats: list[TeamStats]) -> None:
        self._stats_by_team = {s.team: s for s in stats}
        self._ratings = off_def_ratings(stats, self.sport)

    def has_team(self, team: str) -> bool:
        return team in self._stats_by_team

    def predict_scores(self, home: str, away: str) -> tuple[float, float]:
        """Expected points for (home, away)."""
        if home not in self._stats_by_team or away not in self._stats_by_team:
            return 0.0, 0.0
        off_a, def_a = self._ratings.get(home, (100.0, 100.0))
        off_b, def_b = self._ratings.get(away, (100.0, 100.0))
        league_avg = LEAGUE_AVG_PPG.get(self.sport, 100.0)
        # Expected points: (own OFF + opp DEF) / 200 * league_avg (both normalized to 100)
        home_pts = (off_a + def_b) / 200.0 * league_avg
        away_pts = (off_b + def_a) / 200.0 * league_avg
        return home_pts, away_pts

    def predict(self, home: str, away: str) -> float:
        """Home win prob via Pythagorean expectation on expected scores."""
        hp, ap = self.predict_scores(home, away)
        if hp <= 0 or ap <= 0:
            return 0.5
        exp = PYTH_EXPONENT.get(self.sport, 2.0)
        prob = (hp**exp) / (hp**exp + ap**exp)
        return clamp_prob(prob)

    def predict_estimate(self, home: str, away: str) -> ModelEstimate | None:
        if not (self.has_team(home) and self.has_team(away)):
            return None
        hp, ap = self.predict_scores(home, away)
        p = self.predict(home, away)
        factors = [
            f"Power: {home} OFF/DEF={self._ratings.get(home, (100,100))[0]:.1f}/{self._ratings.get(home, (100,100))[1]:.1f}",
            f"Power: {away} OFF/DEF={self._ratings.get(away, (100,100))[0]:.1f}/{self._ratings.get(away, (100,100))[1]:.1f}",
            f"Expected: {home} {hp:.1f} – {away} {ap:.1f}",
        ]
        return ModelEstimate(
            model_name="power_ratings",
            probability=p,
            uncertainty=0.06,
            confidence=0.65,
            factors=factors,
        )

    def predict_spread(self, home: str, away: str) -> float:
        """Expected point differential (home - away), negative if away favored."""
        hp, ap = self.predict_scores(home, away)
        return hp - ap

    def predict_total(self, home: str, away: str) -> float:
        hp, ap = self.predict_scores(home, away)
        return hp + ap
