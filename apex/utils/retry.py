"""Exponential backoff + circuit breaker for external HTTP calls."""

from __future__ import annotations

import asyncio
import functools
import time
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from apex.utils.logger import get_logger

logger = get_logger(__name__)

T = TypeVar("T")


def async_retry(
    attempts: int = 4,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    exceptions: tuple[type[Exception], ...] = (Exception,),
) -> Callable[[Callable[..., Awaitable[T]]], Callable[..., Awaitable[T]]]:
    """Retry decorator with exponential backoff 1s, 2s, 4s, capped at max_delay."""

    def decorator(fn: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:
        @functools.wraps(fn)
        async def wrapper(*args: Any, **kwargs: Any) -> T:
            last_exc: Exception | None = None
            for i in range(attempts):
                try:
                    return await fn(*args, **kwargs)
                except exceptions as exc:
                    last_exc = exc
                    if i == attempts - 1:
                        break
                    delay = min(base_delay * (2**i), max_delay)
                    logger.warning(
                        "retry attempt %d/%d for %s: %s (sleep %.1fs)",
                        i + 1,
                        attempts,
                        fn.__name__,
                        exc,
                        delay,
                    )
                    await asyncio.sleep(delay)
            assert last_exc is not None
            raise last_exc

        return wrapper

    return decorator


class CircuitBreakerOpen(Exception):
    """Raised when the circuit breaker is open and calls are being short-circuited."""


class CircuitBreaker:
    """Simple circuit breaker: open after N consecutive failures, half-open after cool_off.

    States:
      closed   → calls pass through, failures counted
      open     → calls raise CircuitBreakerOpen, flips to half_open after cool_off
      half_open → next call probes; success → closed, failure → open
    """

    def __init__(
        self,
        name: str,
        failure_threshold: int = 3,
        cool_off_seconds: float = 60.0,
    ) -> None:
        self.name = name
        self.failure_threshold = failure_threshold
        self.cool_off_seconds = cool_off_seconds
        self._failures = 0
        self._opened_at: float | None = None
        self._state = "closed"

    @property
    def state(self) -> str:
        if self._state == "open" and self._opened_at is not None:
            if time.monotonic() - self._opened_at >= self.cool_off_seconds:
                return "half_open"
        return self._state

    def record_success(self) -> None:
        self._failures = 0
        self._state = "closed"
        self._opened_at = None

    def record_failure(self) -> None:
        self._failures += 1
        if self._failures >= self.failure_threshold:
            self._state = "open"
            self._opened_at = time.monotonic()

    def allow(self) -> bool:
        return self.state != "open"

    async def call(self, fn: Callable[..., Awaitable[T]], *args: Any, **kwargs: Any) -> T:
        """Execute fn through the breaker."""
        if not self.allow():
            raise CircuitBreakerOpen(f"circuit breaker '{self.name}' is open")
        try:
            result = await fn(*args, **kwargs)
            self.record_success()
            return result
        except Exception:
            self.record_failure()
            raise
