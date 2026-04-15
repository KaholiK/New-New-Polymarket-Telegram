"""Per-source circuit breaker + freshness tracker.

Thin wrapper around utils.retry.CircuitBreaker that remembers last-success timestamps
so strategies can enforce required_freshness() gates.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from apex.utils.logger import get_logger
from apex.utils.retry import CircuitBreaker
from apex.utils.time_utils import age_seconds, utc_now

logger = get_logger(__name__)


class SourceHealthTracker:
    def __init__(self) -> None:
        self._breakers: dict[str, CircuitBreaker] = {}
        self._last_success: dict[str, datetime] = {}
        self._last_payload: dict[str, Any] = {}

    def breaker(self, name: str) -> CircuitBreaker:
        if name not in self._breakers:
            self._breakers[name] = CircuitBreaker(name)
        return self._breakers[name]

    def record_success(self, name: str, payload: Any = None) -> None:
        self._last_success[name] = utc_now()
        if payload is not None:
            self._last_payload[name] = payload
        self.breaker(name).record_success()

    def record_failure(self, name: str) -> None:
        self.breaker(name).record_failure()

    def age(self, name: str) -> float:
        ts = self._last_success.get(name)
        if ts is None:
            return float("inf")
        return age_seconds(ts)

    def is_fresh(self, name: str, max_age_s: float) -> bool:
        return self.age(name) <= max_age_s

    def last_payload(self, name: str) -> Any:
        return self._last_payload.get(name)

    def snapshot(self) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for name in set(list(self._breakers) + list(self._last_success)):
            out[name] = {
                "age_seconds": round(self.age(name), 1) if self.age(name) != float("inf") else None,
                "state": self.breaker(name).state,
            }
        return out
