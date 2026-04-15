#!/usr/bin/env python
"""Zero-network smoke test — imports, core math, dry-run exchange, regression checks."""

from __future__ import annotations

import asyncio
import importlib
import sys
from pathlib import Path

# Let this script run from the repo root without install
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


async def main() -> int:
    print("APEX smoke test")
    print("=" * 50)

    # 1. Import every apex module
    print("→ importing all modules...")
    to_import = [
        "apex.config",
        "apex.core.models",
        "apex.core.state",
        "apex.core.health",
        "apex.core.engine",
        "apex.core.scheduler",
        "apex.market.catalog_mapper",
        "apex.market.discovery",
        "apex.market.event_mapper",
        "apex.market.orderbook",
        "apex.market.polymarket_client",
        "apex.market.status_guard",
        "apex.data.consensus_builder",
        "apex.data.injury_feed",
        "apex.data.line_movement",
        "apex.data.news_monitor",
        "apex.data.odds_ingestor",
        "apex.data.score_feed",
        "apex.data.source_health",
        "apex.quant.forecaster",
        "apex.quant.models.elo",
        "apex.quant.models.poisson",
        "apex.quant.models.power_ratings",
        "apex.quant.models.market_implied",
        "apex.quant.models.situational",
        "apex.quant.models.injury_adjuster",
        "apex.quant.models.ensemble",
        "apex.quant.calibration.brier_tracker",
        "apex.quant.calibration.calibrator",
        "apex.quant.calibration.model_weights",
        "apex.quant.data.stats_ingestor",
        "apex.quant.data.feature_cache",
        "apex.quant.data.results_tracker",
        "apex.quant.data.historical_odds",
        "apex.strategies",
        "apex.meta.scorer",
        "apex.meta.conflict_resolver",
        "apex.meta.decision_engine",
        "apex.risk.kelly",
        "apex.risk.position_sizer",
        "apex.risk.drawdown",
        "apex.risk.exposure",
        "apex.risk.kill_switch",
        "apex.risk.stale_data_guard",
        "apex.risk.consecutive_loss_guard",
        "apex.execution.order_manager",
        "apex.execution.fill_tracker",
        "apex.execution.slippage",
        "apex.execution.dry_run_exchange",
        "apex.execution.clv_tracker",
        "apex.execution.resolution_monitor",
        "apex.execution.stop_manager",
        "apex.storage.db",
        "apex.telegram.auth",
        "apex.telegram.formatters",
        "apex.utils.math_utils",
        "apex.utils.parsing",
        "apex.utils.time_utils",
        "apex.utils.retry",
    ]
    for name in to_import:
        try:
            importlib.import_module(name)
        except Exception as exc:  # noqa: BLE001
            print(f"  FAIL  {name}: {exc}")
            return 1
    print(f"  OK    {len(to_import)} modules imported")

    # 2. Math sanity
    print("→ math sanity...")
    from apex.utils.math_utils import (
        american_to_decimal,
        implied_prob_from_decimal,
        kelly_from_polymarket,
    )

    assert abs(american_to_decimal(-110) - 1.909) < 0.01, "american_to_decimal broke"
    assert implied_prob_from_decimal(2.0) == 0.5, "implied_prob broke"
    assert kelly_from_polymarket(0.55, 0.48) > 0, "kelly zero at positive edge"
    print("  OK    math functions")

    # 3. Market type regression
    print("→ 'Thunder' word-boundary regression...")
    from apex.core.models import MarketType
    from apex.market.catalog_mapper import detect_market_type

    assert (
        detect_market_type("Oklahoma City Thunder vs Lakers") == MarketType.MONEYLINE
    ), "Thunder misclassified as TOTAL — word boundary regression!"
    print("  OK    Thunder classified as moneyline")

    # 4. clobTokenIds parse cases
    print("→ _parse_clob_token_ids edge cases...")
    from apex.market.discovery import _parse_clob_token_ids

    cases = [
        ('["a","b"]', ("a", "b")),
        (["a", "b"], ("a", "b")),
        (None, ("", "")),
        ("", ("", "")),
        ("malformed[", ("", "")),
    ]
    for raw, expected in cases:
        got = _parse_clob_token_ids(raw)
        assert got == expected, f"case {raw!r} → {got!r} expected {expected!r}"
    print(f"  OK    {len(cases)} parse cases handled")

    # 5. DryRunExchange roundtrip
    print("→ dry-run exchange place/cancel...")
    from apex.core.models import Order, OrderBook, OrderBookLevel, Side
    from apex.execution.dry_run_exchange import DryRunExchange

    ex = DryRunExchange()
    order = Order(
        id="", market_id="m", token_id="t",
        side=Side.YES, price=0.5, size_usd=5.0, contracts=10,
    )
    book = OrderBook(token_id="t", asks=[OrderBookLevel(price=0.5, size=100)])
    placed = await ex.place(order, book)
    assert placed.id
    assert placed.filled_contracts > 0
    await ex.tick()
    polled = await ex.poll(placed.id)
    assert polled is not None
    # Blended avg price must be in (0,1)
    assert 0 < polled.avg_fill_price < 1, f"avg_fill_price invalid: {polled.avg_fill_price}"
    print("  OK    place, tick, avg_fill_price")

    # 6. Slippage dimension check
    print("→ slippage price-difference invariant...")
    from apex.execution.slippage import pre_trade_estimate

    book2 = OrderBook(
        token_id="t",
        asks=[OrderBookLevel(price=0.5, size=100), OrderBookLevel(price=0.55, size=100)],
    )
    est = pre_trade_estimate(book2, "BUY", 150)
    # Slippage USD must NOT scale with trade-size-in-USD. Quick sanity: < $10 for tiny order.
    assert 0 < est.slippage_usd < 10, f"slippage dimensional bug: ${est.slippage_usd}"
    print(f"  OK    slippage_usd=${est.slippage_usd:.4f}")

    # 7. Auth fails closed
    print("→ telegram auth fails closed on empty list...")
    import os

    os.environ["TELEGRAM_AUTHORIZED_USERS"] = ""
    from apex.telegram.auth import is_authorized

    assert is_authorized(12345) is False, "auth accepted user with empty list — REGRESSION"
    print("  OK    auth closed on empty list")

    print("=" * 50)
    print("✅ ALL SMOKE CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
