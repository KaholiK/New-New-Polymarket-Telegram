"""Final position sizing: Kelly → cap by bankroll/liquidity/exposure/drawdown/config max."""

from __future__ import annotations

from dataclasses import dataclass

from apex.config import get_settings
from apex.core.models import Forecast, OrderBook, Sport
from apex.core.state import BotState
from apex.market.orderbook import estimate_fill_price
from apex.risk.drawdown import check_drawdowns
from apex.risk.exposure import check_exposure
from apex.risk.kelly import kelly_size
from apex.utils.math_utils import ev_polymarket


@dataclass
class SizingResult:
    approved: bool
    size_usd: float
    contracts: float
    limit_price: float
    estimated_fill_price: float
    kelly_fraction: float
    reasons: list[str]


def size_position(
    forecast: Forecast,
    state: BotState,
    book: OrderBook | None = None,
    sport: Sport = Sport.UNKNOWN,
    event_id: str = "",
    market_sport_map: dict[str, Sport] | None = None,
    market_event_map: dict[str, str] | None = None,
) -> SizingResult:
    """Decide the final size for a forecast, subject to every risk gate."""
    s = get_settings()
    reasons: list[str] = []

    # 1. Kill/pause
    if state.killed:
        return SizingResult(False, 0.0, 0.0, 0.0, 0.0, 0.0, ["killed"])
    if state.paused:
        return SizingResult(False, 0.0, 0.0, 0.0, 0.0, 0.0, ["paused"])

    # 2. Drawdown
    dd = check_drawdowns(state)
    if dd.daily_exceeded:
        reasons.append(f"daily_drawdown_{dd.daily_dd:.2%}")
    if dd.rolling_exceeded:
        reasons.append(f"rolling_drawdown_{dd.rolling_dd:.2%}")
    if reasons:
        return SizingResult(False, 0.0, 0.0, 0.0, 0.0, 0.0, reasons)

    # 3. Bankroll must be positive
    if state.bankroll <= 0:
        return SizingResult(False, 0.0, 0.0, 0.0, 0.0, 0.0, ["bankroll_zero"])

    # 4. Decide which price/prob to use
    price = forecast.market_price  # already side-aware from forecaster
    true_prob = forecast.ensemble_prob if forecast.side.value == "YES" else 1.0 - forecast.ensemble_prob
    edge = true_prob - price
    if edge <= 0:
        return SizingResult(False, 0.0, 0.0, 0.0, 0.0, 0.0, ["non_positive_edge"])

    # 5. Kelly sizing
    k_frac, k_usd = kelly_size(
        true_prob=true_prob,
        yes_price=price,
        edge_std=forecast.ensemble_std,
        bankroll=state.bankroll,
    )
    if k_usd <= 0:
        return SizingResult(False, 0.0, 0.0, 0.0, 0.0, 0.0, ["kelly_zero"])

    # 6. Cap by max position %
    max_pos = state.bankroll * s.max_position_pct
    capped = min(k_usd, max_pos)

    # 7. Cap by per-event exposure
    exp_check = check_exposure(
        state=state,
        proposed_usd=capped,
        sport=sport,
        event_id=event_id,
        market_sport_map=market_sport_map,
        market_event_map=market_event_map,
    )
    if not exp_check.ok:
        # Cap to available, not reject
        limit = min(exp_check.available_for_sport, exp_check.available_for_event)
        if limit < s.min_order_size_usd:
            return SizingResult(False, 0.0, 0.0, 0.0, 0.0, k_frac, exp_check.reasons)
        capped = min(capped, limit)

    # 8. Cap by visible book depth (max 30%)
    est_fill = price
    contracts = capped / price if price > 0 else 0.0
    if book is not None and (book.bids or book.asks):
        side_str = "BUY"  # buying YES or buying NO from ask side
        avg, filled = estimate_fill_price(book, side_str, contracts)
        if filled > 0:
            est_fill = avg
            # Max 30% of visible depth
            total_depth = sum(lvl.size for lvl in (book.asks if side_str == "BUY" else book.bids))
            max_contracts = total_depth * s.max_book_fraction
            if contracts > max_contracts and max_contracts > 0:
                contracts = max_contracts
                capped = contracts * avg
    # Recompute contracts after USD cap finalized
    if price > 0:
        contracts = capped / price

    # 9. Minimum order size
    if capped < s.min_order_size_usd:
        return SizingResult(False, 0.0, 0.0, 0.0, 0.0, k_frac, ["below_min_order"])

    # 10. $1 minimum profit gate
    ev = ev_polymarket(true_prob, price, capped)
    if ev < s.min_profit_threshold:
        return SizingResult(
            False, 0.0, 0.0, 0.0, 0.0, k_frac, [f"below_profit_gate_ev=${ev:.2f}"]
        )

    return SizingResult(
        approved=True,
        size_usd=round(capped, 2),
        contracts=round(contracts, 4),
        limit_price=round(price, 4),
        estimated_fill_price=round(est_fill, 4),
        kelly_fraction=round(k_frac, 4),
        reasons=[],
    )
