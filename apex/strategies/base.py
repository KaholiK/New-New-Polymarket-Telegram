"""BaseStrategy ABC — every strategy defines signal(), explain(), required_freshness()."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from apex.core.models import Forecast, Market, Signal
from apex.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class DataContext:
    """Bundle of data available to a strategy at decision time."""

    forecast: Forecast | None = None
    sharp_consensus: Any = None
    line_movements: list = field(default_factory=list)
    steam_moves: list = field(default_factory=list)
    fresh_news: list = field(default_factory=list)
    fresh_injuries: list = field(default_factory=list)
    orderbook_yes: Any = None
    orderbook_no: Any = None
    source_ages: dict[str, float] = field(default_factory=dict)


class BaseStrategy(ABC):
    """Abstract base. Each strategy is a pure function: (market, context) → Signal | None.

    Strategies MUST fail CLOSED: if required data is missing or stale, return None.
    """

    name: str = "base"

    @abstractmethod
    async def signal(self, market: Market, context: DataContext) -> Signal | None: ...

    @abstractmethod
    def explain(self) -> list[str]: ...

    @abstractmethod
    def required_freshness(self) -> dict[str, int]:
        """Return {source_name: max_age_seconds} the strategy needs."""

    def freshness_ok(self, context: DataContext) -> bool:
        """True if every required source is fresher than the strategy's limit."""
        needs = self.required_freshness()
        for source, max_age in needs.items():
            age = context.source_ages.get(source)
            if age is None:
                return False
            if age > max_age:
                return False
        return True
