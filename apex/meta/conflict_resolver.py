"""Deduplicate overlapping signals, resolve opposite-side conflicts."""

from __future__ import annotations

from apex.core.models import Side, Signal


def dedupe_and_resolve(
    scored: list[tuple[Signal, float]],
    score_diff_required: float = 30.0,
) -> list[tuple[Signal, float]]:
    """Collapse signals on the same market.

    - Same market + same side → keep highest-scoring signal.
    - Same market + opposite sides → reject both unless higher score beats lower by >= score_diff_required.
    """
    by_market: dict[str, list[tuple[Signal, float]]] = {}
    for sig, score in scored:
        by_market.setdefault(sig.market_id, []).append((sig, score))

    out: list[tuple[Signal, float]] = []
    for _, group in by_market.items():
        yes = [(s, sc) for s, sc in group if s.side == Side.YES]
        no = [(s, sc) for s, sc in group if s.side == Side.NO]

        best_yes = max(yes, key=lambda x: x[1]) if yes else None
        best_no = max(no, key=lambda x: x[1]) if no else None

        if best_yes and best_no:
            diff = abs(best_yes[1] - best_no[1])
            if diff < score_diff_required:
                continue  # conflict → reject both
            if best_yes[1] > best_no[1]:
                out.append(best_yes)
            else:
                out.append(best_no)
        elif best_yes:
            out.append(best_yes)
        elif best_no:
            out.append(best_no)

    return sorted(out, key=lambda x: x[1], reverse=True)
