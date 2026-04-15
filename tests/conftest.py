"""Common test fixtures: env setup, clean settings, mock DB, sample markets."""

from __future__ import annotations

import os
import tempfile
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio

# Set fake credentials BEFORE any apex import reads them
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test_token")
os.environ.setdefault("ODDS_API_KEY", "test_odds_key")
os.environ.setdefault("DRY_RUN", "true")
os.environ.setdefault("STARTING_BANKROLL", "20.0")

from apex.core.models import Market, MarketType, Sport  # noqa: E402
from apex.core.state import BotState  # noqa: E402
from apex.storage.db import Database  # noqa: E402


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Ensure consistent settings for every test."""
    monkeypatch.setenv("DRY_RUN", "true")
    monkeypatch.setenv("STARTING_BANKROLL", "20.0")
    yield


@pytest.fixture
def sample_market() -> Market:
    return Market(
        condition_id="0xabc123def456",
        question="Will Lakers beat Celtics?",
        sport=Sport.NBA,
        league="NBA",
        market_type=MarketType.MONEYLINE,
        home_team="Los Angeles Lakers",
        away_team="Boston Celtics",
        yes_token_id="11111111",
        no_token_id="22222222",
        yes_price=0.48,
        no_price=0.52,
        volume=50000.0,
        liquidity=2000.0,
        end_date=datetime.now(UTC) + timedelta(hours=4),
        accepting_orders=True,
        event_id="event_lal_bos_20260415",
        mapping_confidence=0.95,
    )


@pytest.fixture
def sample_state() -> BotState:
    return BotState(starting_bankroll=20.0, dry_run=True)


@pytest_asyncio.fixture
async def temp_db() -> AsyncIterator[Database]:
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        path = tmp.name
    db = Database(path=path)
    await db.connect()
    try:
        yield db
    finally:
        await db.close()
        try:
            os.remove(path)
        except OSError:
            pass
