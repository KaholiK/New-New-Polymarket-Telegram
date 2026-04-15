"""APPROVE / APPROVE_REDUCED / HOLD / REJECT with reason trace."""

from __future__ import annotations

from apex.config import get_settings
from apex.core.models import Decision, DecisionOutcome, ReasonTrace, Signal, Sport
from apex.core.state import BotState
from apex.meta.conflict_resolver import dedupe_and_resolve
from apex.meta.scorer import score_signal
from apex.risk.drawdown import check_drawdowns
from apex.risk.position_sizer import SizingResult, size_position


def evaluate_signal(
    signal: Signal,
    state: BotState,
    market_volume: float,
    market_liquidity: float,
    data_freshness: float,
    mapping_confidence: float,
    sport: Sport,
    event_id: str,
    book=None,  # type: ignore
    market_sport_map: dict[str, Sport] | None = None,
    market_event_map: dict[str, str] | None = None,
    existing_same_event: int = 0,
    existing_same_sport: int = 0,
) -> Decision:
    """Score and size a single signal → full Decision."""
    s = get_settings()

    # Hard gates — produce immediate REJECT
    if state.killed:
        return _reject(signal, "kill_switch_active")
    if state.paused:
        return _reject(signal, f"paused:{state.pause_reason}")
    dd = check_drawdowns(state)
    if dd.daily_exceeded or dd.rolling_exceeded:
        return _reject(signal, f"drawdown daily={dd.daily_dd:.2%} rolling={dd.rolling_dd:.2%}")

    # Score
    total, comps, penalties = score_signal(
        signal=signal,
        volume=market_volume,
        liquidity=market_liquidity,
        data_freshness=data_freshness,
        mapping_confidence=mapping_confidence,
        existing_same_event=existing_same_event,
        existing_same_sport=existing_same_sport,
    )

    # Determine outcome by threshold
    if total < s.decision_reduced_threshold:
        return Decision(
            signal=signal,
            outcome=DecisionOutcome.REJECT,
            final_size_usd=0.0,
            trace=ReasonTrace(
                score=total,
                components=comps,
                penalties=penalties,
                reasons=[f"score {total:.1f} < reject threshold {s.decision_reduced_threshold}"],
            ),
        )

    # Sizing
    if signal.forecast is None:
        return Decision(
            signal=signal,
            outcome=DecisionOutcome.REJECT,
            final_size_usd=0.0,
            trace=ReasonTrace(
                score=total,
                components=comps,
                penalties=penalties,
                reasons=["no_forecast_attached"],
            ),
        )
    sizing: SizingResult = size_position(
        forecast=signal.forecast,
        state=state,
        book=book,
        sport=sport,
        event_id=event_id,
        market_sport_map=market_sport_map,
        market_event_map=market_event_map,
    )
    if not sizing.approved:
        return Decision(
            signal=signal,
            outcome=DecisionOutcome.REJECT,
            final_size_usd=0.0,
            trace=ReasonTrace(
                score=total,
                components=comps,
                penalties=penalties,
                reasons=sizing.reasons,
            ),
        )

    # APPROVE vs APPROVE_REDUCED
    if total >= s.decision_approve_threshold:
        final_size = sizing.size_usd
        outcome = DecisionOutcome.APPROVE
    else:
        final_size = round(sizing.size_usd * 0.5, 2)
        outcome = DecisionOutcome.APPROVE_REDUCED

    return Decision(
        signal=signal,
        outcome=outcome,
        final_size_usd=final_size,
        trace=ReasonTrace(
            score=total,
            components=comps,
            penalties=penalties,
            reasons=[
                f"score {total:.1f}",
                f"kelly {sizing.kelly_fraction:.3f}",
                f"size ${final_size:.2f}",
            ],
        ),
    )


def _reject(signal: Signal, reason: str) -> Decision:
    return Decision(
        signal=signal,
        outcome=DecisionOutcome.REJECT,
        final_size_usd=0.0,
        trace=ReasonTrace(score=0.0, reasons=[reason], rejection_reasons=[reason]),
    )


def evaluate_batch(
    signals: list[Signal],
    **common_kwargs,
) -> list[Decision]:
    """Score all signals, dedup/resolve conflicts, then return Decisions."""
    scored: list[tuple[Signal, float]] = []
    for sig in signals:
        # Score without full evaluation for dedup ranking
        total, _, _ = score_signal(
            signal=sig,
            volume=common_kwargs.get("market_volume", 0.0),
            liquidity=common_kwargs.get("market_liquidity", 0.0),
            data_freshness=common_kwargs.get("data_freshness", 1.0),
            mapping_confidence=common_kwargs.get("mapping_confidence", 1.0),
            existing_same_event=common_kwargs.get("existing_same_event", 0),
            existing_same_sport=common_kwargs.get("existing_same_sport", 0),
        )
        scored.append((sig, total))
    resolved = dedupe_and_resolve(scored)
    out: list[Decision] = []
    for sig, _ in resolved:
        out.append(evaluate_signal(sig, **common_kwargs))  # type: ignore[arg-type]
    return out
