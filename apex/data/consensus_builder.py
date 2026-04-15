"""Remove vig, build weighted consensus, sharp-book preference."""

from __future__ import annotations

from dataclasses import dataclass

from apex.core.models import OddsSnapshot
from apex.data.odds_ingestor import book_weight
from apex.utils.math_utils import clamp_prob, remove_vig_two_way


@dataclass
class Consensus:
    event_id: str
    home_team: str
    away_team: str
    home_prob: float
    away_prob: float
    book_count: int
    weighted_book_count: float
    fair_probs_by_book: dict[str, tuple[float, float]]


def build_consensus(snapshots: list[OddsSnapshot]) -> dict[str, Consensus]:
    """Group snapshots by event_id and build sharp-weighted consensus.

    For each snapshot: remove vig (two-way normalize). Then take the weighted average
    of fair probabilities across books. Pinnacle weight 3.0, Circa 2.5, BetCME 2.0, etc.
    """
    by_event: dict[str, list[OddsSnapshot]] = {}
    for s in snapshots:
        by_event.setdefault(s.event_id, []).append(s)

    out: dict[str, Consensus] = {}
    for event_id, snaps in by_event.items():
        if not snaps:
            continue
        home = snaps[0].home_team
        away = snaps[0].away_team
        weighted_home = 0.0
        weighted_away = 0.0
        total_weight = 0.0
        fair_by_book: dict[str, tuple[float, float]] = {}
        for s in snaps:
            fair_h, fair_a = remove_vig_two_way(s.home_implied_prob, s.away_implied_prob)
            w = book_weight(s.bookmaker)
            weighted_home += fair_h * w
            weighted_away += fair_a * w
            total_weight += w
            fair_by_book[s.bookmaker] = (fair_h, fair_a)
        if total_weight <= 0:
            continue
        ph = clamp_prob(weighted_home / total_weight)
        pa = clamp_prob(weighted_away / total_weight)
        # Final normalization (should already be ≈1)
        s = ph + pa
        if s > 0:
            ph, pa = ph / s, pa / s
        out[event_id] = Consensus(
            event_id=event_id,
            home_team=home,
            away_team=away,
            home_prob=clamp_prob(ph),
            away_prob=clamp_prob(pa),
            book_count=len(snaps),
            weighted_book_count=total_weight,
            fair_probs_by_book=fair_by_book,
        )
    return out
