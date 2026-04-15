"""Check: market accepting orders, not locked, before game start."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from apex.core.models import Market
from apex.utils.time_utils import minutes_until, utc_now


@dataclass
class StatusCheck:
    ok: bool
    reasons: list[str]


def check_status(market: Market, min_minutes_to_start: float = 0.0) -> StatusCheck:
    """Gate: market must be accepting orders and not yet started."""
    reasons: list[str] = []
    if not market.accepting_orders:
        reasons.append("not_accepting_orders")
    if not market.yes_token_id and not market.no_token_id:
        reasons.append("no_tokens")
    if market.end_date is not None:
        mins = minutes_until(market.end_date)
        if mins < min_minutes_to_start:
            reasons.append(f"too_close_to_start:{mins:.1f}m")
        if mins < 0:
            reasons.append("event_past")
    return StatusCheck(ok=len(reasons) == 0, reasons=reasons)


def locked_markets_within(markets: list[Market], window: timedelta) -> list[Market]:
    """Return markets within `window` of end_date (for lockout)."""
    now = utc_now()
    out = []
    for m in markets:
        if m.end_date is None:
            continue
        delta = (m.end_date - now).total_seconds()
        if 0 <= delta <= window.total_seconds():
            out.append(m)
    return out
