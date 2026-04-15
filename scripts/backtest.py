#!/usr/bin/env python
"""Historical simulation: compute Sharpe, max DD, CLV, Brier, breakdown by sport.

Reads from the same SQLite DB the live bot uses (odds_snapshots + game_results).
Intentionally minimal — the goal is a repeatable replay with real numbers, not a
full backtesting framework.
"""

from __future__ import annotations

import argparse
import asyncio
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from apex.storage.db import Database  # noqa: E402
from apex.utils.math_utils import brier_score  # noqa: E402


async def run(db_path: str) -> int:
    db = Database(path=db_path)
    await db.connect()
    try:
        trades = await db.list_trades(limit=10000)
        resolved = [t for t in trades if t.get("resolved_at")]
        if not resolved:
            print("No resolved trades found.")
            return 0

        pnls = [float(t["pnl"] or 0) for t in resolved]
        total = sum(pnls)
        wins = sum(1 for p in pnls if p > 0)
        losses = sum(1 for p in pnls if p < 0)
        win_rate = wins / max(1, len(resolved))
        mean = statistics.mean(pnls)
        stdev = statistics.pstdev(pnls) if len(pnls) > 1 else 0.0
        sharpe = (mean / stdev) if stdev > 0 else 0.0

        # Max drawdown walk
        peak = 0.0
        run = 0.0
        max_dd = 0.0
        for p in pnls:
            run += p
            peak = max(peak, run)
            max_dd = min(max_dd, run - peak)

        # Forecast accuracy
        forecasts = await db.resolved_forecasts(limit=10000)
        briers = [
            brier_score(float(f["predicted_prob"]), int(f["actual_outcome"]))
            for f in forecasts
            if f.get("predicted_prob") is not None and f.get("actual_outcome") is not None
        ]
        avg_brier = statistics.mean(briers) if briers else None

        # CLV stats
        clv_rows = await db.list_clv(limit=10000)
        clvs = [float(r["clv"]) for r in clv_rows if r.get("clv") is not None]
        avg_clv = statistics.mean(clvs) if clvs else None
        pos_clv_rate = (sum(1 for c in clvs if c > 0) / len(clvs)) if clvs else None

        # Breakdown by sport
        by_sport: dict[str, list[float]] = {}
        for t in resolved:
            s = (t.get("event_id") or "").split("_")[0] or "unknown"
            by_sport.setdefault(s, []).append(float(t["pnl"] or 0))

        print("APEX backtest report")
        print("=" * 40)
        print(f"Resolved trades: {len(resolved)}")
        print(f"Total P&L: ${total:+.2f}")
        print(f"Wins/Losses: {wins}/{losses}  win rate {win_rate:.2%}")
        print(f"Mean/Std: ${mean:+.2f} / ${stdev:.2f}  Sharpe {sharpe:.2f}")
        print(f"Max DD: ${max_dd:.2f}")
        if avg_brier is not None:
            print(f"Forecast Brier (n={len(briers)}): {avg_brier:.4f}")
        if avg_clv is not None:
            print(f"CLV (n={len(clvs)}): avg {avg_clv:+.4f}, positive rate {pos_clv_rate:.2%}")
        print()
        print("By sport (bucket-key prefix):")
        for sport, pnls_s in by_sport.items():
            print(f"  {sport}: n={len(pnls_s)}  total=${sum(pnls_s):+.2f}  avg=${statistics.mean(pnls_s):+.2f}")
    finally:
        await db.close()
    return 0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="apex.db")
    args = parser.parse_args()
    sys.exit(asyncio.run(run(args.db)))


if __name__ == "__main__":
    main()
