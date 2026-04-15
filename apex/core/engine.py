"""ApexEngine — master orchestrator that wires every subsystem.

This module composes: discovery, odds ingestion, forecaster, strategies, decision engine,
order manager, CLV tracker, resolution monitor. It is the single owner of long-lived
state (BotState, DB, health registry).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from apex.config import Settings, get_settings
from apex.core.health import HealthRegistry
from apex.core.models import Forecast, Market
from apex.core.state import BotState
from apex.data.consensus_builder import build_consensus
from apex.data.injury_feed import InjuryFeed
from apex.data.line_movement import LineMovementTracker
from apex.data.news_monitor import NewsMonitor
from apex.data.odds_ingestor import OddsIngestor
from apex.data.score_feed import ScoreFeed
from apex.data.source_health import SourceHealthTracker
from apex.execution.clv_tracker import CLVTracker
from apex.execution.dry_run_exchange import DryRunExchange
from apex.execution.fill_tracker import FillTracker
from apex.execution.order_manager import OrderManager
from apex.execution.resolution_monitor import ResolutionMonitor
from apex.execution.stop_manager import StopManager
from apex.market.discovery import MarketDiscovery
from apex.market.polymarket_client import PolymarketClient
from apex.meta.decision_engine import evaluate_signal
from apex.quant.calibration.brier_tracker import BrierTracker
from apex.quant.calibration.calibrator import Calibrator
from apex.quant.data.feature_cache import FeatureCache
from apex.quant.data.results_tracker import ResultsTracker
from apex.quant.data.stats_ingestor import StatsIngestor
from apex.quant.forecaster import ForecastContext, Forecaster
from apex.quant.models.elo import EloModel
from apex.quant.models.power_ratings import PowerRatingsModel
from apex.storage.db import Database
from apex.strategies import DataContext, enabled_strategies
from apex.utils.logger import get_logger
from apex.utils.parsing import fuzzy_ratio

logger = get_logger(__name__)

DEFAULT_SPORTS = ["NBA", "NFL", "MLB", "NHL"]


@dataclass
class EngineStats:
    discovered_markets: int = 0
    signals_generated: int = 0
    decisions_approved: int = 0
    orders_placed: int = 0


class ApexEngine:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.state = BotState(
            starting_bankroll=self.settings.starting_bankroll, dry_run=self.settings.dry_run
        )
        self.health = HealthRegistry()
        self.db = Database(path=self.settings.db_path)
        self.source_health = SourceHealthTracker()

        # HTTP clients
        self._http = httpx.AsyncClient(timeout=15.0, headers={"User-Agent": "APEX/0.1"})
        self.polymarket = PolymarketClient(client=self._http)
        self.discovery = MarketDiscovery(self.polymarket)
        self.odds = OddsIngestor(self.settings.odds_api_key, client=self._http)
        self.injuries = InjuryFeed(client=self._http)
        self.news = NewsMonitor(client=self._http)
        self.scores = ScoreFeed(client=self._http)
        self.stats = StatsIngestor(client=self._http)

        # Quant
        self.elo_models: dict[str, EloModel] = {sp: EloModel(sp) for sp in DEFAULT_SPORTS}
        self.power_models: dict[str, PowerRatingsModel] = {
            sp: PowerRatingsModel(sp) for sp in DEFAULT_SPORTS
        }
        self.calibrator = Calibrator()
        self.brier = BrierTracker()
        self.forecaster = Forecaster(
            elo_models=self.elo_models,
            power_models=self.power_models,
            calibrator=self.calibrator,
            brier_tracker=self.brier,
        )
        self.feature_cache = FeatureCache(ttl_seconds=60.0)
        self.line_mov = LineMovementTracker()

        # Execution
        self.dry = DryRunExchange()
        self.fills = FillTracker()
        self.order_manager = OrderManager(self.state, self.dry, self.fills)
        self.clv = CLVTracker(db=self.db)
        self.resolution = ResolutionMonitor(self.polymarket, self.db, self.state)
        self.stops = StopManager()
        self.results_tracker = ResultsTracker(self.scores, self.db)

        # Strategy registry
        self.strategies = enabled_strategies()

        # In-memory caches
        self.markets_by_condition: dict[str, Market] = {}
        self.stats_counters = EngineStats()

    # ------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------

    async def startup(self) -> None:
        await self.db.connect()
        # Restore Elo
        for sport, model in self.elo_models.items():
            rows = await self.db.load_elo(sport)
            model.bulk_load(rows)
        logger.info("engine: startup complete, bankroll=$%.2f", self.state.bankroll)

    async def shutdown(self) -> None:
        await self.polymarket.aclose()
        await self.odds.aclose()
        await self.injuries.aclose()
        await self.news.aclose()
        await self.scores.aclose()
        await self.stats.aclose()
        await self._http.aclose()
        await self.db.close()

    # ------------------------------------------------------------
    # Periodic jobs
    # ------------------------------------------------------------

    async def scan_markets(self) -> list[Market]:
        markets = await self.discovery.scan_active_markets(
            min_confidence=self.settings.min_mapping_confidence
        )
        self.source_health.record_success("polymarket", payload=len(markets))
        self.health.record_success("polymarket", 0.0)
        for m in markets:
            self.markets_by_condition[m.condition_id] = m
        self.stats_counters.discovered_markets = len(markets)
        return markets

    async def ingest_stats(self) -> None:
        """Pull ESPN team stats into PowerRatingsModel."""
        for sport, model in self.power_models.items():
            rows = await self.stats.fetch_team_stats(sport)
            if rows:
                model.load(rows)

    async def ingest_odds(self) -> dict[str, Any]:
        """Pull multi-book odds, build consensus, track line movement."""
        out: dict[str, Any] = {}
        for sport in DEFAULT_SPORTS:
            snaps = await self.odds.fetch_odds(sport)
            self.line_mov.ingest(snaps)
            consensus = build_consensus(snaps)
            out[sport] = consensus
        self.source_health.record_success("odds")
        self.health.record_success("odds", 0.0)
        return out

    async def generate_signals(self) -> list:
        """Run each enabled strategy across all known markets."""
        all_signals = []
        for market in self.markets_by_condition.values():
            fc = await self._forecast_market(market)
            ctx = DataContext(
                forecast=fc,
                source_ages={
                    "polymarket": self.source_health.age("polymarket"),
                    "odds": self.source_health.age("odds"),
                    "news": self.source_health.age("news"),
                    "injuries": self.source_health.age("injuries"),
                },
            )
            for strat in self.strategies:
                try:
                    sig = await strat.signal(market, ctx)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("strategy %s failed for %s: %s", strat.name, market.condition_id, exc)
                    continue
                if sig is not None:
                    all_signals.append(sig)
        self.stats_counters.signals_generated = len(all_signals)
        return all_signals

    async def _forecast_market(self, market: Market) -> Forecast | None:
        key = f"fc:{market.condition_id}"
        cached = self.feature_cache.get(key)
        if cached is not None:
            return cached
        ctx = ForecastContext(
            market=market,
            home_team=market.home_team or "",
            away_team=market.away_team or "",
            sport=market.sport,
            data_freshness=1.0,
        )
        try:
            fc = self.forecaster.forecast(ctx)
        except Exception as exc:  # noqa: BLE001
            logger.warning("forecast failed for %s: %s", market.condition_id, exc)
            return None
        self.feature_cache.set(key, fc)
        return fc

    async def predict_by_query(self, query: str) -> Forecast | None:
        """Find a market by fuzzy title match, forecast it, return Forecast."""
        if not query or not self.markets_by_condition:
            return None
        best: tuple[Market, float] | None = None
        for m in self.markets_by_condition.values():
            r = fuzzy_ratio(query, m.question or "")
            if best is None or r > best[1]:
                best = (m, r)
        if best is None or best[1] < 0.4:
            return None
        return await self._forecast_market(best[0])

    async def poll_fills(self) -> None:
        await self.dry.tick()

    async def poll_resolutions(self) -> None:
        rows = await self.db.get_open_trades()
        from apex.core.models import Side, Trade, TradeStatus

        trades = []
        for r in rows:
            try:
                trades.append(
                    Trade(
                        id=r["id"],
                        market_id=r["market_id"],
                        event_id=r.get("event_id") or "",
                        strategy=r.get("strategy") or "",
                        side=Side(r["side"]),
                        size_usd=float(r["size_usd"]),
                        entry_price=float(r["entry_price"]),
                        filled_qty=float(r.get("filled_qty") or 0),
                        filled_price=float(r.get("filled_price") or 0),
                        status=TradeStatus(r["status"]),
                        pnl=float(r.get("pnl") or 0),
                    )
                )
            except (ValueError, KeyError):
                continue
        if trades:
            await self.resolution.check_and_settle(trades)

    async def poll_results(self) -> None:
        finals = await self.results_tracker.poll_finals(DEFAULT_SPORTS)
        for r in finals:
            model = self.elo_models.get(r.sport)
            if model is None:
                continue
            home_won = r.winner == r.home_team
            model.update(r.home_team, r.away_team, home_won=home_won)
            await self.db.upsert_elo(r.sport, r.home_team, model.get(r.home_team))
            await self.db.upsert_elo(r.sport, r.away_team, model.get(r.away_team))

    async def evaluate_and_place(self, signals: list) -> None:
        """Score each signal, then place approved decisions."""
        for sig in signals:
            sport = sig.forecast.sport if sig.forecast else None
            market = self.markets_by_condition.get(sig.market_id)
            if market is None:
                continue
            decision = evaluate_signal(
                signal=sig,
                state=self.state,
                market_volume=market.volume,
                market_liquidity=market.liquidity,
                data_freshness=1.0,
                mapping_confidence=market.mapping_confidence,
                sport=sport or market.sport,
                event_id=market.event_id or "",
            )
            if decision.outcome.value in ("APPROVE", "APPROVE_REDUCED"):
                token_id = market.yes_token_id if sig.side.value == "YES" else market.no_token_id
                await self.order_manager.place_from_decision(decision, token_id=token_id)
                self.stats_counters.decisions_approved += 1
                self.stats_counters.orders_placed += 1
