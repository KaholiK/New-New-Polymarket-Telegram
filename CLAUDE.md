# CLAUDE.md — Developer Guide

## Architecture at a glance

```
discovery → forecaster → strategies → scorer → decision → sizer → order manager
                                                                       ↓
                                                          dry-run / live exchange
                                                                       ↓
                                                         fill tracker → CLV
                                                                       ↓
                                                      resolution monitor → calibrator
```

Every periodic task runs on APScheduler (see `apex/core/scheduler.py`). The
`ApexEngine` in `apex/core/engine.py` owns all long-lived state.

## Environment variables

Everything lives in `apex/config.py`. Most have sensible defaults; the only
required fields for a live run are `TELEGRAM_BOT_TOKEN` and `ODDS_API_KEY`.

Paper mode is the default (`DRY_RUN=true`).

## Running tests

```bash
pytest -q                    # all unit tests
python scripts/smoke.py      # zero-network smoke test
ruff check apex/ tests/      # lint
```

## Trade lifecycle

1. `MarketDiscovery.scan_active_markets()` → pulls camelCase Gamma data, parses
   `clobTokenIds` (JSON-string), filters to sports markets above
   `min_mapping_confidence`.
2. `Forecaster.forecast()` → runs Elo + power ratings + Poisson + market-implied +
   situational + injury models, blends via log-linear pool, applies calibration.
3. Each enabled strategy in `apex/strategies/` emits a `Signal` or `None`.
4. `meta.decision_engine.evaluate_signal()` scores 0-100, resolves conflicts,
   sizes with shrunk fractional Kelly subject to all risk gates, outputs a
   `Decision` with a full `ReasonTrace`.
5. `OrderManager.place_from_decision()` debits the bankroll at placement and
   routes to `DryRunExchange` in paper mode.
6. `DryRunExchange.tick()` progresses partial fills. `FillTracker` records each
   fill with blended average price = `total_usd / total_contracts`.
7. `ResolutionMonitor` polls Gamma for `closed=True` markets and settles P&L.
8. `CLVTracker` records entry vs closing price per trade; the result feeds
   strategy health (`sharp_follow` auto-disables on rolling negative CLV).

## Formulas to remember

- Elo expected score: `P(A) = 1 / (1 + 10^((B - A) / 400))`
- Pythagorean win prob: `P(A) = A^exp / (A^exp + B^exp)`
- Shrunk Kelly: use `max(0, raw_edge - edge_std)` as the effective edge.
- Slippage cost: `price_diff × contracts`. NEVER `× size_usd`.
- Fill price: `total_usd / total_contracts`. NEVER `/ size_usd`.
- Brier: `mean((forecast - outcome)^2)`; 0.25 = coin flip.

## Extension points

- Add a strategy: subclass `BaseStrategy`, register in
  `apex/strategies/__init__.py`.
- Add a model: implement a `predict_estimate()` returning `ModelEstimate`, plug
  into `Forecaster`.
- Tune weights: `apex/quant/calibration/model_weights.py` recomputes from
  rolling Brier.

## Common pitfalls

- Don't cache `Settings`. `get_settings()` is NOT `lru_cache`d for a reason —
  tests monkeypatch env vars per case.
- Don't use plain substring matching on market titles ("Thunder" contains
  "under"). Always use `\b` word-boundary regex.
- Don't compute fill price as `total_cost / size_usd` — that returns ~1.0.
- Always `html.escape()` dynamic strings before embedding in Telegram HTML.
