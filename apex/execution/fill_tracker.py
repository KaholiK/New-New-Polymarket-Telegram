"""Track partial fills, compute blended avg price, fill accumulator.

Critical formula (bug ledger): avg_fill_price = total_usd / total_contracts.
NEVER compute as total_cost / size_usd (that returns ≈1.0).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from apex.core.models import Fill, Order


@dataclass
class FillAccumulator:
    order_id: str
    fills: list[Fill] = field(default_factory=list)

    @property
    def total_contracts(self) -> float:
        return sum(f.contracts for f in self.fills)

    @property
    def total_usd(self) -> float:
        return sum(f.usd for f in self.fills)

    @property
    def avg_price(self) -> float:
        if self.total_contracts <= 0:
            return 0.0
        # CRITICAL: total_usd / total_contracts — NEVER / size_usd
        return self.total_usd / self.total_contracts

    def add(self, f: Fill) -> None:
        self.fills.append(f)


class FillTracker:
    def __init__(self) -> None:
        self._accs: dict[str, FillAccumulator] = {}

    def register_order(self, order: Order) -> None:
        self._accs[order.id] = FillAccumulator(order_id=order.id)

    def record_fill(self, f: Fill) -> FillAccumulator:
        acc = self._accs.setdefault(f.order_id, FillAccumulator(order_id=f.order_id))
        acc.add(f)
        return acc

    def get(self, order_id: str) -> FillAccumulator | None:
        return self._accs.get(order_id)

    def all_accumulators(self) -> list[FillAccumulator]:
        return list(self._accs.values())
