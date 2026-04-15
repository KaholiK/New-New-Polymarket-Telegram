"""Per-sport, per-event, total dollar exposure limits."""

from __future__ import annotations

from dataclasses import dataclass

from apex.config import get_settings
from apex.core.models import Sport
from apex.core.state import BotState


@dataclass
class ExposureCheck:
    ok: bool
    reasons: list[str]
    available_for_sport: float
    available_for_event: float


def sport_exposure(state: BotState, sport: Sport, market_sport_map: dict[str, Sport]) -> float:
    """Sum of cost basis of open positions in a given sport."""
    total = 0.0
    for key, pos in state.positions.items():
        s = market_sport_map.get(pos.market_id, Sport.UNKNOWN)
        if s == sport:
            total += pos.cost_basis_usd
    return total


def event_exposure(state: BotState, event_id: str, market_event_map: dict[str, str]) -> float:
    total = 0.0
    for pos in state.positions.values():
        if market_event_map.get(pos.market_id) == event_id:
            total += pos.cost_basis_usd
    return total


def check_exposure(
    state: BotState,
    proposed_usd: float,
    sport: Sport,
    event_id: str,
    market_sport_map: dict[str, Sport] | None = None,
    market_event_map: dict[str, str] | None = None,
) -> ExposureCheck:
    s = get_settings()
    market_sport_map = market_sport_map or {}
    market_event_map = market_event_map or {}
    reasons: list[str] = []
    max_sport = state.bankroll * s.max_sport_exposure_pct
    cur_sport = sport_exposure(state, sport, market_sport_map)
    cur_event = event_exposure(state, event_id, market_event_map)
    # Event cap = max(flat USD floor, % of bankroll)
    max_event = max(s.max_event_exposure_usd, state.bankroll * s.max_event_exposure_pct)
    available_sport = max(0.0, max_sport - cur_sport)
    available_event = max(0.0, max_event - cur_event)
    if proposed_usd > available_sport:
        reasons.append(f"sport_cap_exceeded:sport={sport.value} need=${proposed_usd:.2f} avail=${available_sport:.2f}")
    if proposed_usd > available_event:
        reasons.append(f"event_cap_exceeded:event={event_id} need=${proposed_usd:.2f} avail=${available_event:.2f}")
    return ExposureCheck(
        ok=not reasons,
        reasons=reasons,
        available_for_sport=available_sport,
        available_for_event=available_event,
    )
