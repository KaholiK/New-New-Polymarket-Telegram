"""Brier score + log-loss + ECE per model, per sport."""

from __future__ import annotations

from dataclasses import dataclass, field

from apex.utils.math_utils import brier_score, clamp_prob, log_loss


@dataclass
class ModelStats:
    model_name: str
    sport: str = "ALL"
    forecasts: int = 0
    brier_sum: float = 0.0
    log_loss_sum: float = 0.0
    buckets: dict[int, tuple[int, int]] = field(default_factory=dict)  # bucket -> (count, wins)

    @property
    def avg_brier(self) -> float:
        if self.forecasts == 0:
            return 0.25  # coin-flip baseline
        return self.brier_sum / self.forecasts

    @property
    def avg_log_loss(self) -> float:
        if self.forecasts == 0:
            return 0.693  # -ln(0.5)
        return self.log_loss_sum / self.forecasts

    @property
    def ece(self) -> float:
        """Expected Calibration Error across buckets."""
        if not self.buckets:
            return 0.0
        total_n = sum(c for c, _ in self.buckets.values())
        if total_n == 0:
            return 0.0
        ece = 0.0
        for bucket, (n, wins) in self.buckets.items():
            if n == 0:
                continue
            bucket_conf = (bucket + 0.5) / 10.0
            actual = wins / n
            ece += (n / total_n) * abs(bucket_conf - actual)
        return ece


def bucket_of(prob: float) -> int:
    """Return bucket index 0..9 for probability p ∈ [0,1]."""
    p = max(0.0, min(1.0, prob))
    idx = int(p * 10)
    return min(idx, 9)


class BrierTracker:
    def __init__(self) -> None:
        self._stats: dict[tuple[str, str], ModelStats] = {}

    def _key(self, model_name: str, sport: str) -> tuple[str, str]:
        return (model_name, sport or "ALL")

    def get(self, model_name: str, sport: str = "ALL") -> ModelStats:
        key = self._key(model_name, sport)
        if key not in self._stats:
            self._stats[key] = ModelStats(model_name=model_name, sport=sport or "ALL")
        return self._stats[key]

    def record(
        self,
        model_name: str,
        prob: float,
        outcome: int,
        sport: str = "ALL",
    ) -> None:
        p = clamp_prob(prob)
        stats = self.get(model_name, sport)
        stats.forecasts += 1
        stats.brier_sum += brier_score(p, outcome)
        stats.log_loss_sum += log_loss(p, outcome)
        b = bucket_of(p)
        count, wins = stats.buckets.get(b, (0, 0))
        stats.buckets[b] = (count + 1, wins + (1 if outcome == 1 else 0))

    def summary(self) -> dict[str, dict[str, float]]:
        out: dict[str, dict[str, float]] = {}
        for (name, sport), s in self._stats.items():
            out[f"{name}:{sport}"] = {
                "forecasts": s.forecasts,
                "brier": round(s.avg_brier, 4),
                "log_loss": round(s.avg_log_loss, 4),
                "ece": round(s.ece, 4),
            }
        return out
