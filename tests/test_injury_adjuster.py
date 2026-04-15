"""Tests for injury adjuster."""

from __future__ import annotations

from datetime import UTC, datetime

from apex.core.models import InjuryNote
from apex.quant.models.injury_adjuster import (
    PLAYER_IMPACT,
    STATUS_MULTIPLIER,
    InjuryAdjusterModel,
    compute_team_impact,
    lookup_player,
)


def _inj(player: str, team: str, status: str = "OUT") -> InjuryNote:
    return InjuryNote(
        event_id="",
        team=team,
        player=player,
        status=status,
        fetched_at=datetime.now(UTC),
    )


def test_lookup_mvp():
    assert lookup_player("LeBron James", "NBA") is not None


def test_lookup_unknown_returns_none():
    assert lookup_player("Some Bench Guy", "NBA") is None


def test_lookup_case_insensitive():
    a = lookup_player("lebron james", "NBA")
    b = lookup_player("LeBron James", "NBA")
    assert a == b


def test_status_multiplier_scales():
    out = STATUS_MULTIPLIER["OUT"]
    q = STATUS_MULTIPLIER["QUESTIONABLE"]
    assert out > q


def test_impact_mvp_out():
    injuries = [_inj("LeBron James", "Los Angeles Lakers", "OUT")]
    imp = compute_team_impact("NBA", "Los Angeles Lakers", injuries)
    assert imp.total_impact == PLAYER_IMPACT["NBA"]["mvp"]


def test_impact_questionable_reduced():
    injuries = [_inj("LeBron James", "Los Angeles Lakers", "QUESTIONABLE")]
    imp = compute_team_impact("NBA", "Los Angeles Lakers", injuries)
    expected = PLAYER_IMPACT["NBA"]["mvp"] * STATUS_MULTIPLIER["QUESTIONABLE"]
    assert abs(imp.total_impact - expected) < 1e-6


def test_impact_other_team_ignored():
    injuries = [_inj("LeBron James", "Los Angeles Lakers", "OUT")]
    imp = compute_team_impact("NBA", "Boston Celtics", injuries)
    assert imp.total_impact == 0.0


def test_adjuster_model_shifts_prob():
    m = InjuryAdjusterModel()
    injuries = [_inj("LeBron James", "Los Angeles Lakers", "OUT")]
    est = m.predict_estimate(
        base_prob=0.50,
        sport="NBA",
        home_team="Los Angeles Lakers",
        away_team="Boston Celtics",
        injuries=injuries,
    )
    # Home MVP out → home prob drops
    assert est.probability < 0.50


def test_adjuster_no_injuries_returns_base():
    m = InjuryAdjusterModel()
    est = m.predict_estimate(
        base_prob=0.50,
        sport="NBA",
        home_team="Lakers",
        away_team="Celtics",
        injuries=[],
    )
    assert abs(est.probability - 0.50) < 1e-6
