"""Version 1 public contracts. UTC event time and availability time prevent look-ahead."""

from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)
    schema_version: Literal["1.0"] = "1.0"
    id: str = Field(default_factory=lambda: str(uuid4()))
    timestamp: datetime
    available_at: datetime
    source: str = Field(min_length=1)

    @field_validator("timestamp", "available_at")
    @classmethod
    def utc_time(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("timezone required")
        return v.astimezone(UTC)

    @model_validator(mode="after")
    def ordered_time(self):
        if self.available_at < self.timestamp:
            raise ValueError("availability precedes event")
        return self


class MarketSnapshot(Record):
    exchange: str = "polymarket"
    market_id: str
    event_id: str
    question: str
    token_id: str
    outcome: str = "YES"
    probability: float = Field(ge=0, le=1)
    status: Literal["active", "closed", "resolved", "unknown"] = "unknown"
    resolution_rules: str = ""
    resolution_source: str = ""
    end_time: datetime | None = None
    tick_size: float = Field(default=0.01, gt=0, le=1)
    min_order_size: float = Field(default=1, gt=0)


class PriceLevel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)
    price: float = Field(gt=0, lt=1)
    size: float = Field(gt=0)


class OrderBookSnapshot(Record):
    exchange: str = "polymarket"
    market_id: str
    token_id: str
    bids: tuple[PriceLevel, ...] = ()
    asks: tuple[PriceLevel, ...] = ()
    sequence: int = Field(default=0, ge=0)
    complete: bool = True

    @model_validator(mode="after")
    def valid_book(self):
        if list(self.bids) != sorted(self.bids, key=lambda x: x.price, reverse=True):
            raise ValueError("bids must descend")
        if list(self.asks) != sorted(self.asks, key=lambda x: x.price):
            raise ValueError("asks must ascend")
        if self.bids and self.asks and self.bids[0].price >= self.asks[0].price:
            raise ValueError("crossed order book")
        return self


class MarketRelationship(Record):
    market_ids: tuple[str, ...]
    kind: Literal["statistical", "mutually_exclusive", "exhaustive", "conditional", "implication"]
    confidence: float = Field(ge=0, le=1)
    rule_verified: bool = False
    rule_description: str = ""


class RelationshipEvidence(Record):
    relationship_id: str
    sample_count: int = Field(ge=0)
    persistence: int = Field(ge=0)
    strength: float = Field(ge=0)
    confidence: float = Field(ge=0, le=1)
    qualified: bool
    reasons: tuple[str, ...] = ()
    observation_ids: tuple[str, ...] = ()
    regime: str = "unknown"


class ModelProvenance(Record):
    model_name: str
    model_version: str
    training_end: datetime
    artifact_hash: str
    approved: bool = False
    calibration_samples: int = Field(default=0, ge=0)


class ProbabilityEstimate(Record):
    market_id: str
    token_id: str
    probability: float = Field(ge=0, le=1)
    lower: float = Field(ge=0, le=1)
    upper: float = Field(ge=0, le=1)
    model_id: str
    calibrated: bool = False
    evidence_ids: tuple[str, ...] = ()

    @model_validator(mode="after")
    def interval(self):
        if not self.lower <= self.probability <= self.upper:
            raise ValueError("invalid probability interval")
        return self


class TradingOpportunity(Record):
    market_id: str
    token_id: str
    event_id: str
    estimate_id: str
    evidence_ids: tuple[str, ...]
    side: Literal["BUY", "SELL"] = "BUY"
    market_probability: float = Field(gt=0, lt=1)
    estimated_probability: float = Field(ge=0, le=1)
    conservative_probability: float = Field(ge=0, le=1)
    net_edge: float
    fee_rate: float = Field(ge=0, le=1)
    slippage: float = Field(ge=0)
    liquidity: float = Field(ge=0)
    tier: Literal["standard", "high", "exceptional"] = "standard"
    calibrated: bool = False
    independent_evidence: int = Field(default=0, ge=0)


class OrderIntent(Record):
    client_order_id: str
    market_id: str
    token_id: str
    event_id: str
    opportunity_id: str
    side: Literal["BUY", "SELL"] = "BUY"
    limit_price: float = Field(gt=0, lt=1)
    quantity: float = Field(gt=0)
    expires_at: datetime
    tier: Literal["standard", "high", "exceptional"] = "standard"


class RiskDecision(Record):
    intent_id: str
    approved: bool
    reasons: tuple[str, ...]
    approved_notional: float = Field(ge=0)
    reservation_id: str | None = None
    expires_at: datetime


class ExecutionReport(Record):
    intent_id: str
    client_order_id: str
    status: Literal["open", "partial", "filled", "cancelled", "expired", "rejected"]
    filled_quantity: float = Field(ge=0)
    average_price: float = Field(ge=0, le=1)
    fees: float = Field(ge=0)
    remaining_quantity: float = Field(ge=0)
    reason: str = ""


class PortfolioPosition(Record):
    market_id: str
    token_id: str
    event_id: str
    quantity: float = Field(ge=0)
    average_cost: float = Field(ge=0, le=1)
    mark_price: float = Field(ge=0, le=1)
    realized_pnl: float = 0
    simulated: bool = True


class StrategyPerformance(Record):
    strategy_id: str
    trades: int = Field(ge=0)
    simulated_pnl: float
    realized_pnl: float = 0
    brier_score: float | None = Field(default=None, ge=0, le=1)
    max_drawdown: float = Field(ge=0)
    dataset_hash: str
    out_of_sample: bool = True
