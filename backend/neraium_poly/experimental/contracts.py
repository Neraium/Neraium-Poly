"""Phase9 integration contracts. Monetary forecasts are not calibrated probabilities."""

from typing import Literal

from pydantic import Field, model_validator

from neraium_poly.contracts import MarketSnapshot, OrderBookSnapshot, Record


class ExperimentalSignal(Record):
    account_id: Literal["experimental-paper"] = "experimental-paper"
    validation_status: Literal["unvalidated"] = "unvalidated"
    strategy_id: str
    strategy_version: str = "1"
    market_id: str
    token_id: str
    event_id: str
    side: Literal["BUY"] = "BUY"
    tier: Literal["standard", "high", "exceptional"] = "standard"
    eligible: bool = False
    valuation_kind: Literal["horizon_mark", "terminal_probability", "payoff_constraint"] = "horizon_mark"
    forecast_value: float | None = Field(default=None, ge=0, le=1)
    lower_value: float | None = Field(default=None, ge=0, le=1)
    upper_value: float | None = Field(default=None, ge=0, le=1)
    estimated_net_edge: float | None = None
    fee_rate: float = Field(default=0, ge=0, le=1)
    slippage_per_share: float = Field(default=0.01, ge=0)
    horizon_seconds: float = Field(default=60, gt=0, le=86400)
    evidence_ids: tuple[str, ...] = ()
    independent_sources: tuple[str, ...] = ()
    hypothesis: str
    uncertainty: str
    assumptions: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()
    diagnostics: dict[str, float | str | int | None] = Field(default_factory=dict)

    @model_validator(mode="after")
    def values(self):
        if self.eligible and (
            self.forecast_value is None
            or self.lower_value is None
            or self.upper_value is None
            or self.estimated_net_edge is None
            or not self.evidence_ids
        ):
            raise ValueError("eligible signal requires bounded valuation and observed evidence")
        if (
            self.lower_value is not None
            and self.forecast_value is not None
            and self.lower_value > self.forecast_value
        ):
            raise ValueError("lower value exceeds forecast")
        if (
            self.upper_value is not None
            and self.forecast_value is not None
            and self.upper_value < self.forecast_value
        ):
            raise ValueError("upper value below forecast")
        return self


class SharedMarketFrame(Record):
    """Direct current public observations; never reconstructed from displayed prices."""

    mode: Literal["real_market_data"] = "real_market_data"
    producer_health: dict = Field(default_factory=dict)
    markets: tuple[MarketSnapshot, ...] = ()
    books: tuple[OrderBookSnapshot, ...] = ()
    fees: dict[str, dict] = Field(default_factory=dict)
    relationships: tuple[dict, ...] = ()
    evidence: tuple[dict, ...] = ()
    connectivity: dict = Field(default_factory=dict)


class ExperimentalPerformance(Record):
    account_id: Literal["experimental-paper"] = "experimental-paper"
    strategy_id: str
    validation_status: Literal["unvalidated"] = "unvalidated"
    signals: int = Field(default=0, ge=0)
    rejected: int = Field(default=0, ge=0)
    orders: int = Field(default=0, ge=0)
    fills: int = Field(default=0, ge=0)
    simulated_realized_pnl: float = 0
    simulated_unrealized_pnl: float = 0
    max_drawdown: float = Field(default=0, ge=0)
    suspended: bool = False
    suspension_reasons: tuple[str, ...] = ()
    baseline: str = "cash_hold_no_trade"
    certification_eligible: Literal[False] = False
