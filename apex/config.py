"""APEX configuration via pydantic-settings.

Every setting has a typed default so the bot can start in paper mode without a full .env.
get_settings() is intentionally NOT lru_cached — strategies and other classes should call
it dynamically so tests can monkeypatch values per-case.

Credential strings are stripped of surrounding whitespace automatically. A leading
space in .env (very common operator typo) would otherwise URL-encode as "+" or "%20"
and silently break Telegram and Odds API calls.
"""

from __future__ import annotations

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # --- Required credentials ---
    telegram_bot_token: str = ""
    odds_api_key: str = ""

    # --- Optional upgrades (enhanced forecasting) ---
    anthropic_api_key: str = ""  # enables claude_analyzer model
    sportsdata_api_key: str = ""  # enables richer player/team stats
    anthropic_model: str = "claude-sonnet-4-20250514"
    anthropic_daily_cap_usd: float = 1.0  # stop calling API after this daily spend
    anthropic_edge_threshold: float = 0.02  # only analyze markets with raw_edge above this

    # --- Polymarket (only needed for live mode) ---
    polymarket_private_key: str = ""
    polymarket_api_key: str = ""
    polymarket_api_secret: str = ""

    # --- Bot identity ---
    bot_name: str = "APEX"

    # --- Mode ---
    dry_run: bool = True

    # --- Bankroll ---
    starting_bankroll: float = 20.0

    # --- Risk limits ---
    max_position_pct: float = 0.15
    max_sport_exposure_pct: float = 0.40
    # Per-event exposure: either a flat USD floor (for very small bankrolls like $20)
    # or a percentage of bankroll, whichever is larger.
    max_event_exposure_usd: float = 5.0
    max_event_exposure_pct: float = 0.25
    daily_drawdown_pct: float = 0.20
    rolling_drawdown_pct: float = 0.35
    max_consecutive_losses: int = 5
    min_profit_threshold: float = 1.0
    min_order_size_usd: float = 0.50
    max_book_fraction: float = 0.30

    # --- Kelly ---
    kelly_fraction: float = 0.25
    kelly_fraction_small_bankroll: float = 0.33
    small_bankroll_threshold: float = 50.0

    # --- Data freshness (seconds) ---
    odds_max_age: int = 300
    polymarket_max_age: int = 120
    injury_max_age: int = 600
    news_max_age: int = 900

    # --- Strategy toggles ---
    strategy_fair_value: bool = True
    strategy_book_divergence: bool = True
    strategy_news_shock: bool = True
    strategy_injury_reprice: bool = True
    strategy_steam_move: bool = True
    strategy_contrarian: bool = True
    strategy_orderbook_scalp: bool = False
    strategy_prelock_reprice: bool = True
    strategy_complement_arb: bool = True
    strategy_sharp_follow: bool = True
    strategy_momentum: bool = True

    # --- Scheduling intervals (seconds) ---
    market_scan_interval: int = 120
    strategy_cycle_interval: int = 60
    fill_poll_interval: int = 15
    resolution_poll_interval: int = 60
    results_tracker_interval: int = 600
    health_check_interval: int = 300
    stop_manager_interval: int = 15

    # --- Telegram ---
    telegram_authorized_users: str = ""  # comma-separated numeric user IDs
    admin_chat_id: int = 0  # chat ID for operational alerts (0 disables)
    admin_alert_throttle_seconds: float = 30 * 60  # min gap between same-key alerts

    # --- Mapping ---
    min_mapping_confidence: float = 0.70

    # --- Scoring / decision ---
    decision_approve_threshold: float = 60.0
    decision_reduced_threshold: float = 40.0

    # --- Database ---
    db_path: str = "apex.db"

    # --- Logging ---
    log_level: str = "INFO"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Strip whitespace from all credential strings. Leading/trailing spaces in .env
    # files are a common operator error and would URL-encode as "+" or "%20" when
    # passed through httpx, silently breaking auth.
    @field_validator(
        "telegram_bot_token",
        "odds_api_key",
        "anthropic_api_key",
        "sportsdata_api_key",
        "anthropic_model",
        "polymarket_private_key",
        "polymarket_api_key",
        "polymarket_api_secret",
        "telegram_authorized_users",
        mode="before",
    )
    @classmethod
    def _strip_str(cls, v: str | None) -> str:
        if v is None:
            return ""
        return str(v).strip()

    @property
    def authorized_user_ids(self) -> list[int]:
        raw = self.telegram_authorized_users.strip()
        if not raw:
            return []
        out: list[int] = []
        for chunk in raw.split(","):
            chunk = chunk.strip()
            if not chunk:
                continue
            try:
                out.append(int(chunk))
            except ValueError:
                continue
        return out


def get_settings() -> Settings:
    """Return a fresh Settings instance.

    NOT lru_cached — callers should call this at decision-time, not at __init__ time,
    so tests can monkeypatch behavior.
    """
    return Settings()
