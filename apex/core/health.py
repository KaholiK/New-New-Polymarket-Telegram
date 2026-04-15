"""System health: per-source freshness, API latency, DB status."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass
class SourceHealth:
    name: str
    last_success_ts: datetime | None = None
    last_failure_ts: datetime | None = None
    last_error: str = ""
    consecutive_failures: int = 0
    total_successes: int = 0
    total_failures: int = 0
    latency_ms_recent: list[float] = field(default_factory=list)

    def record_success(self, latency_ms: float) -> None:
        self.last_success_ts = datetime.now(UTC)
        self.consecutive_failures = 0
        self.total_successes += 1
        self.latency_ms_recent.append(latency_ms)
        if len(self.latency_ms_recent) > 50:
            self.latency_ms_recent.pop(0)

    def record_failure(self, error: str) -> None:
        self.last_failure_ts = datetime.now(UTC)
        self.last_error = error
        self.consecutive_failures += 1
        self.total_failures += 1

    @property
    def avg_latency_ms(self) -> float:
        if not self.latency_ms_recent:
            return 0.0
        return sum(self.latency_ms_recent) / len(self.latency_ms_recent)

    @property
    def age_seconds(self) -> float:
        if not self.last_success_ts:
            return float("inf")
        return (datetime.now(UTC) - self.last_success_ts).total_seconds()

    def is_healthy(self, max_age_seconds: float) -> bool:
        return self.age_seconds <= max_age_seconds and self.consecutive_failures < 3


class HealthRegistry:
    """Aggregates per-source health for /health command and freshness gating."""

    def __init__(self) -> None:
        self._sources: dict[str, SourceHealth] = {}
        self.db_healthy: bool = True
        self.db_last_error: str = ""
        self.start_time: datetime = datetime.now(UTC)

    def get(self, name: str) -> SourceHealth:
        if name not in self._sources:
            self._sources[name] = SourceHealth(name=name)
        return self._sources[name]

    def record_success(self, name: str, latency_ms: float) -> None:
        self.get(name).record_success(latency_ms)

    def record_failure(self, name: str, error: str) -> None:
        self.get(name).record_failure(error)

    def mark_db(self, healthy: bool, error: str = "") -> None:
        self.db_healthy = healthy
        self.db_last_error = error

    def all_healthy(self, max_ages: dict[str, float]) -> bool:
        for name, max_age in max_ages.items():
            s = self._sources.get(name)
            if s is None or not s.is_healthy(max_age):
                return False
        return self.db_healthy

    def snapshot(self) -> dict:
        uptime = (datetime.now(UTC) - self.start_time).total_seconds()
        return {
            "uptime_seconds": round(uptime, 1),
            "db_healthy": self.db_healthy,
            "db_last_error": self.db_last_error,
            "sources": {
                name: {
                    "age_seconds": round(s.age_seconds, 1) if s.last_success_ts else None,
                    "consecutive_failures": s.consecutive_failures,
                    "avg_latency_ms": round(s.avg_latency_ms, 1),
                    "total_successes": s.total_successes,
                    "total_failures": s.total_failures,
                    "last_error": s.last_error,
                }
                for name, s in self._sources.items()
            },
        }
