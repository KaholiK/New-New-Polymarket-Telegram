"""Forecaster — master brain. Runs all models and builds a Forecast object."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from apex.core.models import (
    Confidence,
    Forecast,
    InjuryNote,
    Market,
    MarketType,
    ModelEstimate,
    Side,
    Sport,
)
from apex.data.consensus_builder import Consensus
from apex.quant.calibration.brier_tracker import BrierTracker
from apex.quant.calibration.calibrator import Calibrator
from apex.quant.calibration.model_weights import compute_weights
from apex.quant.models.elo import EloModel
from apex.quant.models.ensemble import classify_confidence, combine
from apex.quant.models.injury_adjuster import InjuryAdjusterModel
from apex.quant.models.market_implied import MarketImpliedModel
from apex.quant.models.poisson import PoissonModel
from apex.quant.models.power_ratings import PowerRatingsModel
from apex.quant.models.situational import SituationalInputs, SituationalModel
from apex.utils.logger import get_logger
from apex.utils.math_utils import clamp_prob, ev_polymarket, polymarket_edge

logger = get_logger(__name__)


@dataclass
class ForecastContext:
    """Inputs passed from engine to forecaster for a single market."""

    market: Market
    consensus: Consensus | None = None
    injuries: list[InjuryNote] = field(default_factory=list)
    situational: SituationalInputs | None = None
    home_team: str = ""
    away_team: str = ""
    sport: Sport = Sport.UNKNOWN
    # optional per-source data freshness [0..1]
    data_freshness: float = 1.0


class Forecaster:
    def __init__(
        self,
        elo_models: dict[str, EloModel] | None = None,
        power_models: dict[str, PowerRatingsModel] | None = None,
        poisson_configs: dict[str, tuple[float, int]] | None = None,  # sport → (lambda, n_sims)
        calibrator: Calibrator | None = None,
        brier_tracker: BrierTracker | None = None,
    ) -> None:
        self.elo_models = elo_models or {}
        self.power_models = power_models or {}
        self.poisson_configs = poisson_configs or {
            "MLB": (9.2, 10000),
            "NHL": (6.2, 10000),
            "MLS": (2.7, 10000),
        }
        self.calibrator = calibrator or Calibrator()
        self.brier_tracker = brier_tracker or BrierTracker()
        self.market_implied = MarketImpliedModel()
        self.situational = SituationalModel()
        self.injury = InjuryAdjusterModel()

    def _elo(self, sport: Sport) -> EloModel | None:
        return self.elo_models.get(sport.value)

    def _power(self, sport: Sport) -> PowerRatingsModel | None:
        return self.power_models.get(sport.value)

    def forecast(self, ctx: ForecastContext) -> Forecast:
        """Produce a full Forecast for a single market."""
        m = ctx.market
        sport = ctx.sport or m.sport
        home = ctx.home_team or m.home_team or ""
        away = ctx.away_team or m.away_team or ""

        fc = Forecast(
            event_id=m.event_id or uuid.uuid4().hex[:12],
            market_id=m.condition_id,
            sport=sport,
            league=m.league,
            market_type=m.market_type,
            home_team=home,
            away_team=away,
            side=Side.YES,
            market_price=m.yes_price,
            market_implied_prob=clamp_prob(m.yes_price),
        )

        # For non-moneyline markets, we currently only route the market-implied model.
        if m.market_type != MarketType.MONEYLINE or not home or not away:
            mi = self.market_implied.predict_estimate(m, ctx.consensus, market_is_home=True)
            fc.model_estimates["market_implied"] = mi
            fc.ensemble_prob = mi.probability
            fc.ensemble_std = mi.uncertainty
            fc.confidence = Confidence.LOW
            fc.data_freshness = ctx.data_freshness
            fc.key_factors = mi.factors[:3]
            fc.rejection_reasons.append("non_moneyline_or_missing_teams")
            return fc

        # 1. Market-implied
        mi = self.market_implied.predict_estimate(m, ctx.consensus, market_is_home=True)
        fc.model_estimates["market_implied"] = mi

        # 2. Elo
        elo = self._elo(sport)
        if elo is not None and elo.get_games(home) + elo.get_games(away) > 0:
            fc.model_estimates["elo"] = elo.predict_estimate(home, away)

        # 3. Power ratings
        power = self._power(sport)
        if power is not None and power.has_team(home) and power.has_team(away):
            est = power.predict_estimate(home, away)
            if est is not None:
                fc.model_estimates["power_ratings"] = est

        # 4. Poisson for score-based sports
        if sport.value in self.poisson_configs and power is not None:
            lambda_avg, nsims = self.poisson_configs[sport.value]
            home_stats = power._stats_by_team.get(home)  # noqa: SLF001
            away_stats = power._stats_by_team.get(away)  # noqa: SLF001
            if home_stats and away_stats:
                pm = PoissonModel(league_avg_goals=lambda_avg, n_sims=nsims, seed=42)
                fc.model_estimates["poisson"] = pm.predict_estimate(
                    home_stats.avg_points_for,
                    home_stats.avg_points_against,
                    away_stats.avg_points_for,
                    away_stats.avg_points_against,
                )

        # Compute provisional ensemble to use as base prob for situational/injury adjustments
        weights = compute_weights(self.brier_tracker, sport=sport.value)
        base = combine(fc.model_estimates, weights=weights)

        # 5. Situational
        if ctx.situational is not None:
            sit_est = self.situational.predict_estimate(
                base.probability, ctx.situational, sport=sport.value
            )
            fc.model_estimates["situational"] = sit_est

        # 6. Injuries
        inj_est = self.injury.predict_estimate(
            base.probability,
            sport=sport.value,
            home_team=home,
            away_team=away,
            injuries=ctx.injuries,
        )
        fc.model_estimates["injury"] = inj_est

        # Final ensemble with all contributions
        ensemble = combine(
            fc.model_estimates,
            weights=weights,
            edge_zscore=0.0,  # computed below
        )

        # Apply calibration if trained
        calibrated = self.calibrator.apply("ensemble", ensemble.probability, sport=sport.value)
        fc.ensemble_prob = calibrated
        fc.ensemble_std = ensemble.std
        fc.model_disagreement = ensemble.disagreement
        fc.confidence = ensemble.confidence

        # Edge calcs
        fc.raw_edge = polymarket_edge(calibrated, m.yes_price)
        if ensemble.std > 0:
            fc.edge_zscore = fc.raw_edge / max(0.01, ensemble.std)
        else:
            fc.edge_zscore = 0.0

        # Reclassify confidence with the actual z-score
        fc.confidence = classify_confidence(
            n_models=len(fc.model_estimates),
            disagreement=ensemble.disagreement,
            edge_zscore=fc.edge_zscore,
        )

        # Cost model: taker fee 2% + expected slippage 1¢ + maker/taker tax
        # Paper mode has no fees — but estimate conservatively for sizing.
        estimated_cost = 0.02  # 2% of size as buffer
        fc.edge_after_costs = fc.raw_edge - estimated_cost

        # Choose side: YES if edge > 0, NO if edge < 0
        if fc.raw_edge >= 0:
            fc.side = Side.YES
        else:
            fc.side = Side.NO
            # recompute edge from the NO perspective
            fc.raw_edge = -fc.raw_edge
            fc.market_price = m.no_price
            fc.market_implied_prob = clamp_prob(m.no_price)
            # For NO, "true prob" is (1 - calibrated)
            true_no = 1.0 - calibrated
            fc.raw_edge = true_no - m.no_price
            fc.edge_after_costs = fc.raw_edge - estimated_cost

        fc.data_freshness = ctx.data_freshness

        # Kelly & actionability
        from apex.utils.math_utils import kelly_from_polymarket

        price = m.yes_price if fc.side == Side.YES else m.no_price
        true_prob = calibrated if fc.side == Side.YES else 1.0 - calibrated
        fc.kelly_fraction = kelly_from_polymarket(true_prob, price)

        # Actionable? Defer to decision engine; here we just flag based on quant gates.
        reasons: list[str] = []
        if fc.confidence == Confidence.NO_OPINION:
            reasons.append("no_opinion")
        if fc.edge_after_costs <= 0:
            reasons.append("edge_after_costs_nonpositive")
        if abs(fc.edge_zscore) < 1.0:
            reasons.append("edge_below_z1")
        if ctx.data_freshness < 0.4:
            reasons.append("stale_data")
        if fc.kelly_fraction <= 0:
            reasons.append("zero_kelly")
        fc.rejection_reasons = reasons
        fc.is_actionable = not reasons

        # Key factors — top 3-5 most descriptive
        fc.key_factors = _top_factors(fc.model_estimates, limit=5)

        # Tentative sizing (before risk engine): Kelly × small fraction × default bankroll.
        # Real sizing happens in risk/position_sizer with current bankroll.
        fc.recommended_size_usd = 0.0  # sizing comes later

        # EV check (report only)
        ev = ev_polymarket(true_prob, price, 1.0)
        if ev < 0 and fc.is_actionable:
            fc.is_actionable = False
            fc.rejection_reasons.append("negative_ev_per_dollar")

        return fc


def _top_factors(estimates: dict[str, ModelEstimate], limit: int = 5) -> list[str]:
    """Pick the most informative short factors from contributing models."""
    out: list[str] = []
    priority = ["market_implied", "elo", "power_ratings", "injury", "situational", "poisson"]
    for name in priority:
        est = estimates.get(name)
        if est is None or not est.factors:
            continue
        # Take first factor per model
        out.append(est.factors[0])
        if len(out) >= limit:
            break
    return out[:limit]


def _safe_get(d: dict[str, Any], key: str, default: Any = None) -> Any:
    try:
        return d.get(key, default)
    except AttributeError:
        return default
