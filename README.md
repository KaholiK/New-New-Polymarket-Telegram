# APEX

Polymarket sports prediction-market trading bot. Telegram-operated, paper-first.

## What it does

1. Discovers sports markets on Polymarket (Gamma API).
2. Maps each market to the real-world game via fuzzy team/player matching.
3. Runs multiple quantitative models (Elo, power ratings, Poisson, market-implied,
   situational, injury adjuster) and combines them with calibration-weighted
   log-linear pooling.
4. Compares calibrated probability to the Polymarket price and computes the edge.
5. Scores candidate signals 0-100 across six positive components and three penalty
   components, then resolves conflicts and produces an APPROVE / APPROVE_REDUCED /
   REJECT decision with a full reason trace.
6. Sizes positions with shrunk fractional Kelly, caps by bankroll/liquidity/exposure,
   and enforces a $1 minimum profit gate.
7. Places orders via a simulated exchange in paper mode (default). Live mode requires
   explicit `.env` + Telegram confirmation.
8. Tracks every prediction's outcome for ongoing Brier / CLV calibration.

## Operating mode

**Paper mode is the default** (`DRY_RUN=true`). No live orders will be placed until
you explicitly set `DRY_RUN=false` in `.env` AND confirm the switch via the inline
`/paper_off` keyboard.

## Setup

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Copy and edit env
cp .env.example .env
# Fill in TELEGRAM_BOT_TOKEN and ODDS_API_KEY at minimum

# 3. Run smoke test (zero network)
python scripts/smoke.py

# 4. Run unit tests
pytest -q

# 5. Start the bot (paper mode)
python -m apex.main
```

## Directory map

- `apex/config.py` — every env-tunable setting, typed defaults.
- `apex/core/` — engine, scheduler, state, health, domain models.
- `apex/market/` — Polymarket discovery, order book, catalog mapping, event mapping.
- `apex/data/` — odds, injury, news, score ingestion + consensus + line movement.
- `apex/quant/` — Elo, power ratings, Poisson, market-implied, situational, injury,
  ensemble, calibration, forecaster.
- `apex/strategies/` — 11 strategies.
- `apex/meta/` — signal scorer, conflict resolver, decision engine.
- `apex/risk/` — Kelly, position sizer, drawdown, exposure, kill switch, guards.
- `apex/execution/` — order manager, fill tracker, slippage, dry-run exchange, CLV,
  resolution monitor, stop manager.
- `apex/telegram/` — bot setup, commands, formatters, auth (fail-closed).
- `apex/storage/` — SQLite schema + CRUD.

## First-week procedure

1. Run in paper mode for at least 2 weeks.
2. Monitor `/status`, `/pnl`, `/calibration`, `/clv` every day.
3. Watch for persistent negative CLV in any strategy — sharp-follow auto-disables.
4. Only flip to live after you are satisfied with paper performance AND CLV trends.

## Tests

Target ≥ 300 unit tests plus the smoke script.

```bash
pytest -q
python scripts/smoke.py
ruff check apex/ tests/ scripts/
```

## Bug ledger (enforced by tests)

- `clobTokenIds` parse across JSON string / list / malformed / empty.
- `detect_market_type` with \b word boundary ("Thunder" → moneyline, not under).
- Slippage USD = price_diff × contracts (NOT × size USD).
- Fill price = total_usd / total_contracts (NOT / size_usd).
- Bankroll debited at order placement, not just on fill.
- Telegram auth fails CLOSED on empty authorized list.
- ESPN standings path `/apis/v2/sports/...` (not `/apis/site/v2/`).
- NFL `pointsFor` divided by `gamesPlayed` (season totals, not per-game).
