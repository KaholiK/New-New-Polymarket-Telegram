#!/usr/bin/env python
"""Live API integration: ESPN, Gamma, CLOB order book, Forecaster.

This script makes real network calls. Run manually to verify the bot can reach
external APIs and parse them. It will NOT place any orders.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


async def main() -> int:
    from apex.data.odds_ingestor import OddsIngestor
    from apex.data.score_feed import ScoreFeed
    from apex.market.discovery import MarketDiscovery
    from apex.market.polymarket_client import PolymarketClient
    from apex.quant.data.stats_ingestor import StatsIngestor

    print("APEX live pipeline test")
    print("=" * 50)

    print("→ Polymarket Gamma discovery...")
    pm = PolymarketClient()
    try:
        disc = MarketDiscovery(pm)
        markets = await disc.scan_active_markets(max_markets=20)
        print(f"  discovered {len(markets)} markets")
        for m in markets[:3]:
            print(f"    - {m.question[:60]} sport={m.sport.value} conf={m.mapping_confidence:.2f}")
    except Exception as exc:  # noqa: BLE001
        print(f"  FAIL gamma: {exc}")
    finally:
        await pm.aclose()

    print("→ ESPN scoreboard...")
    sf = ScoreFeed()
    try:
        events = await sf.fetch_scoreboard("NBA")
        print(f"  {len(events)} events")
        for ev in events[:3]:
            print(f"    {ev.home_team} vs {ev.away_team} ({ev.status})")
    except Exception as exc:  # noqa: BLE001
        print(f"  FAIL scoreboard: {exc}")
    finally:
        await sf.aclose()

    print("→ ESPN standings → power ratings...")
    si = StatsIngestor()
    try:
        stats = await si.fetch_team_stats("NBA")
        print(f"  {len(stats)} teams")
    except Exception as exc:  # noqa: BLE001
        print(f"  FAIL standings: {exc}")
    finally:
        await si.aclose()

    print("→ The Odds API...")
    import os

    key = os.environ.get("ODDS_API_KEY", "")
    if not key or key == "test_odds_key":
        print("  skipped (no ODDS_API_KEY)")
    else:
        oi = OddsIngestor(key)
        try:
            snaps = await oi.fetch_odds("NBA")
            print(f"  {len(snaps)} snapshots")
        except Exception as exc:  # noqa: BLE001
            print(f"  FAIL odds: {exc}")
        finally:
            await oi.aclose()

    print("=" * 50)
    print("Pipeline probe complete.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
