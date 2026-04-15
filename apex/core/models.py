"""Core pydantic models shared across modules.

Every cross-module data structure lives here to avoid circular imports and to keep a
single source of truth for trade/order/forecast schemas.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


def _utcnow() -> datetime:
    return datetime.now(UTC)


# ---------- Enums ----------


class Sport(str, Enum):
    NBA = "NBA"
    NFL = "NFL"
    MLB = "MLB"
    NHL = "NHL"
    UFC = "UFC"
    MLS = "MLS"
    NCAAB = "NCAAB"
    NCAAF = "NCAAF"
    UNKNOWN = "UNKNOWN"


class MarketType(str, Enum):
    MONEYLINE = "moneyline"
    SPREAD = "spread"
    TOTAL = "total"
    PROP = "prop"
    OTHER = "other"


class Side(str, Enum):
    YES = "YES"
    NO = "NO"


class OrderStatus(str, Enum):
    PENDING = "pending"
    OPEN = "open"
    PARTIAL = "partial"
    FILLED = "filled"
    CANCELED = "canceled"
    REJECTED = "rejected"
    FAILED = "failed"


class TradeStatus(str, Enum):
    OPEN = "open"
    CLOSED = "closed"
    RESOLVED_WIN = "resolved_win"
    RESOLVED_LOSS = "resolved_loss"
    RESOLVED_INVALID = "resolved_invalid"
    CANCELED = "canceled"


class DecisionOutcome(str, Enum):
    APPROVE = "APPROVE"
    APPROVE_REDUCED = "APPROVE_REDUCED"
    HOLD = "HOLD"
    REJECT = "REJECT"


class Confidence(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    NO_OPINION = "no_opinion"


# ---------- Market & event ----------


class Market(BaseModel):
    """Polymarket market, normalized."""

    model_config = ConfigDict(extra="allow")

    condition_id: str
    question: str
    sport: Sport = Sport.UNKNOWN
    league: str = ""
    market_type: MarketType = MarketType.OTHER
    home_team: str | None = None
    away_team: str | None = None
    yes_token_id: str = ""
    no_token_id: str = ""
    yes_price: float = 0.5
    no_price: float = 0.5
    volume: float = 0.0
    liquidity: float = 0.0
    end_date: datetime | None = None
    accepting_orders: bool = True
    event_id: str | None = None
    mapping_confidence: float = 0.0
    fetched_at: datetime = Field(default_factory=_utcnow)
    tags: list[str] = Field(default_factory=list)


class OrderBookLevel(BaseModel):
    price: float
    size: float


class OrderBook(BaseModel):
    token_id: str
    bids: list[OrderBookLevel] = Field(default_factory=list)
    asks: list[OrderBookLevel] = Field(default_factory=list)
    fetched_at: datetime = Field(default_factory=_utcnow)

    @property
    def best_bid(self) -> float:
        return self.bids[0].price if self.bids else 0.0

    @property
    def best_ask(self) -> float:
        return self.asks[0].price if self.asks else 1.0

    @property
    def mid(self) -> float:
        if not self.bids or not self.asks:
            return 0.5
        return (self.best_bid + self.best_ask) / 2.0

    @property
    def spread(self) -> float:
        if not self.bids or not self.asks:
            return 1.0
        return max(0.0, self.best_ask - self.best_bid)


# ---------- Forecast ----------


class ModelEstimate(BaseModel):
    model_name: str
    probability: float = Field(ge=0.0, le=1.0)
    uncertainty: float = 0.05
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    factors: list[str] = Field(default_factory=list)


class Forecast(BaseModel):
    """Full forecast output of quant/forecaster.py for a single market."""

    model_config = ConfigDict(extra="allow")

    event_id: str
    market_id: str
    sport: Sport = Sport.UNKNOWN
    league: str = ""
    market_type: MarketType = MarketType.MONEYLINE
    home_team: str = ""
    away_team: str = ""
    side: Side = Side.YES

    model_estimates: dict[str, ModelEstimate] = Field(default_factory=dict)
    ensemble_prob: float = 0.5
    ensemble_std: float = 0.1
    confidence: Confidence = Confidence.NO_OPINION

    market_price: float = 0.5
    market_implied_prob: float = 0.5
    raw_edge: float = 0.0
    edge_zscore: float = 0.0
    edge_after_costs: float = 0.0

    kelly_fraction: float = 0.0
    recommended_size_usd: float = 0.0
    is_actionable: bool = False
    rejection_reasons: list[str] = Field(default_factory=list)
    key_factors: list[str] = Field(default_factory=list)
    model_disagreement: float = 0.0
    data_freshness: float = 1.0
    created_at: datetime = Field(default_factory=_utcnow)


# ---------- Signal & decision ----------


class Signal(BaseModel):
    """Output of a single Strategy.signal() call."""

    strategy: str
    market_id: str
    event_id: str
    side: Side
    size_hint_usd: float
    edge: float
    edge_zscore: float
    confidence: Confidence
    urgency: float = 0.0  # 0-1, higher = act sooner
    forecast: Forecast | None = None
    explanation: list[str] = Field(default_factory=list)
    required_freshness_ok: bool = True
    created_at: datetime = Field(default_factory=_utcnow)


class ReasonTrace(BaseModel):
    """Structured breakdown of why a decision was made."""

    score: float
    components: dict[str, float] = Field(default_factory=dict)
    penalties: dict[str, float] = Field(default_factory=dict)
    reasons: list[str] = Field(default_factory=list)
    rejection_reasons: list[str] = Field(default_factory=list)


class Decision(BaseModel):
    signal: Signal
    outcome: DecisionOutcome
    final_size_usd: float
    trace: ReasonTrace
    created_at: datetime = Field(default_factory=_utcnow)


# ---------- Orders, fills, trades, positions ----------


class Order(BaseModel):
    id: str
    market_id: str
    token_id: str
    side: Side
    price: float
    size_usd: float
    contracts: float = 0.0
    filled_contracts: float = 0.0
    filled_usd: float = 0.0
    avg_fill_price: float = 0.0
    status: OrderStatus = OrderStatus.PENDING
    strategy: str = ""
    signal_id: str = ""
    dry_run: bool = True
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


class Fill(BaseModel):
    order_id: str
    price: float
    contracts: float
    usd: float
    fee: float = 0.0
    fetched_at: datetime = Field(default_factory=_utcnow)


class Position(BaseModel):
    market_id: str
    token_id: str
    side: Side
    contracts: float
    avg_entry_price: float
    cost_basis_usd: float
    current_price: float = 0.0
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0
    opened_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


class Trade(BaseModel):
    id: str
    signal_id: str = ""
    market_id: str
    event_id: str = ""
    strategy: str = ""
    side: Side
    size_usd: float
    entry_price: float
    filled_qty: float = 0.0
    filled_price: float = 0.0
    status: TradeStatus = TradeStatus.OPEN
    pnl: float = 0.0
    closing_price: float | None = None
    clv: float | None = None
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)
    resolved_at: datetime | None = None


# ---------- Data context passed to strategies ----------


class OddsSnapshot(BaseModel):
    event_id: str
    bookmaker: str
    sport: str
    home_team: str
    away_team: str
    home_odds: float
    away_odds: float
    home_implied_prob: float
    away_implied_prob: float
    market_type: MarketType = MarketType.MONEYLINE
    fetched_at: datetime = Field(default_factory=_utcnow)


class InjuryNote(BaseModel):
    event_id: str
    team: str
    player: str
    position: str = ""
    status: str = ""  # OUT, DOUBTFUL, QUESTIONABLE, PROBABLE, DAY-TO-DAY
    description: str = ""
    fetched_at: datetime = Field(default_factory=_utcnow)


class NewsItem(BaseModel):
    fingerprint: str
    headline: str
    summary: str = ""
    teams: list[str] = Field(default_factory=list)
    sport: Sport = Sport.UNKNOWN
    published_at: datetime = Field(default_factory=_utcnow)
    fetched_at: datetime = Field(default_factory=_utcnow)
