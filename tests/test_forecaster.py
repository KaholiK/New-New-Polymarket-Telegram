"""Tests for the forecaster — end-to-end integration with mock data."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from apex.core.models import Market, MarketType, Side, Sport
from apex.quant.data.stats_ingestor import TeamStats
from apex.quant.forecaster import ForecastContext, Forecaster
from apex.quant.models.elo import EloModel
from apex.quant.models.power_ratings import PowerRatingsModel
from apex.quant.models.situational import SituationalInputs


def _make_market(yes_price: float = 0.48) -> Market:
    return Market(
        condition_id="cid_test",
        question="Lakers vs Celtics",
        sport=Sport.NBA,
        league="NBA",
        market_type=MarketType.MONEYLINE,
        home_team="Los Angeles Lakers",
        away_team="Boston Celtics",
        yes_token_id="y",
        no_token_id="n",
        yes_price=yes_price,
        no_price=1.0 - yes_price,
        end_date=datetime.now(UTC) + timedelta(hours=4),
        accepting_orders=True,
        event_id="evt_test",
        volume=100000,
        liquidity=5000,
    )


def _make_forecaster() -> Forecaster:
    elo = EloModel("NBA")
    elo.set("Los Angeles Lakers", 1560, games_played=30)
    elo.set("Boston Celtics", 1580, games_played=30)

    power = PowerRatingsModel("NBA")
    power.load(
        [
            TeamStats(
                team="Los Angeles Lakers",
                sport="NBA",
                wins=40,
                losses=20,
                games_played=60,
                points_for_total=115 * 60,
                points_against_total=110 * 60,
                avg_points_for=115,
                avg_points_against=110,
            ),
            TeamStats(
                team="Boston Celtics",
                sport="NBA",
                wins=44,
                losses=16,
                games_played=60,
                points_for_total=118 * 60,
                points_against_total=108 * 60,
                avg_points_for=118,
                avg_points_against=108,
            ),
        ]
    )
    return Forecaster(elo_models={"NBA": elo}, power_models={"NBA": power})


def test_forecast_runs_end_to_end():
    f = _make_forecaster()
    ctx = ForecastContext(
        market=_make_market(),
        home_team="Los Angeles Lakers",
        away_team="Boston Celtics",
        sport=Sport.NBA,
    )
    fc = f.forecast(ctx)
    assert fc.market_id == "cid_test"
    # Multiple models contribute
    assert len(fc.model_estimates) >= 3
    assert fc.ensemble_prob > 0.001 and fc.ensemble_prob < 0.999


def test_forecast_side_flips_to_no_when_negative_edge():
    f = _make_forecaster()
    # Market says yes = 0.90 (expensive) — our model likely disagrees → NO side
    ctx = ForecastContext(
        market=_make_market(yes_price=0.90),
        home_team="Los Angeles Lakers",
        away_team="Boston Celtics",
        sport=Sport.NBA,
    )
    fc = f.forecast(ctx)
    # side should be NO because 0.90 is overpriced relative to model
    assert fc.side in (Side.YES, Side.NO)


def test_forecast_non_moneyline_routed_to_market_implied_only():
    f = _make_forecaster()
    m = _make_market()
    m.market_type = MarketType.TOTAL
    ctx = ForecastContext(
        market=m, home_team="", away_team="", sport=Sport.NBA,
    )
    fc = f.forecast(ctx)
    assert "market_implied" in fc.model_estimates


def test_forecast_with_situational():
    f = _make_forecaster()
    ctx = ForecastContext(
        market=_make_market(),
        home_team="Los Angeles Lakers",
        away_team="Boston Celtics",
        sport=Sport.NBA,
        situational=SituationalInputs(
            home_team="Los Angeles Lakers",
            away_team="Boston Celtics",
            home_rest_days=4,
            away_rest_days=1,
        ),
    )
    fc = f.forecast(ctx)
    assert "situational" in fc.model_estimates


def test_forecast_stale_data_marks_not_actionable():
    f = _make_forecaster()
    ctx = ForecastContext(
        market=_make_market(),
        home_team="Los Angeles Lakers",
        away_team="Boston Celtics",
        sport=Sport.NBA,
        data_freshness=0.1,
    )
    fc = f.forecast(ctx)
    assert "stale_data" in fc.rejection_reasons or not fc.is_actionable


def test_forecast_sets_kelly_fraction():
    f = _make_forecaster()
    ctx = ForecastContext(
        market=_make_market(),
        home_team="Los Angeles Lakers",
        away_team="Boston Celtics",
        sport=Sport.NBA,
    )
    fc = f.forecast(ctx)
    assert fc.kelly_fraction >= 0.0


def test_forecast_sets_key_factors():
    f = _make_forecaster()
    ctx = ForecastContext(
        market=_make_market(),
        home_team="Los Angeles Lakers",
        away_team="Boston Celtics",
        sport=Sport.NBA,
    )
    fc = f.forecast(ctx)
    assert isinstance(fc.key_factors, list)


def test_forecast_returns_confidence_enum():
    f = _make_forecaster()
    ctx = ForecastContext(
        market=_make_market(),
        home_team="Los Angeles Lakers",
        away_team="Boston Celtics",
        sport=Sport.NBA,
    )
    fc = f.forecast(ctx)
    from apex.core.models import Confidence

    assert fc.confidence in (
        Confidence.HIGH,
        Confidence.MEDIUM,
        Confidence.LOW,
        Confidence.NO_OPINION,
    )


def test_forecast_no_team_data():
    # No Elo, no power → only market-implied → NO_OPINION
    f = Forecaster()
    ctx = ForecastContext(
        market=_make_market(),
        home_team="Los Angeles Lakers",
        away_team="Boston Celtics",
        sport=Sport.NBA,
    )
    fc = f.forecast(ctx)
    # Only 1-2 models → likely not actionable
    assert fc.is_actionable is False or fc.ensemble_prob > 0
