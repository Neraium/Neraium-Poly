"""Frozen Phase11 interchange; operational contracts and strategy gates unchanged."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from neraium_poly.contracts import MarketSnapshot, OrderBookSnapshot


class ResearchObservation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)
    schema_version: Literal["1.0"] = "1.0"
    book: OrderBookSnapshot
    market: MarketSnapshot | None = None
    fee: dict | None = None

    @model_validator(mode="after")
    def causal_context(self):
        if self.market is not None:
            if (self.market.market_id, self.market.token_id) != (self.book.market_id, self.book.token_id):
                raise ValueError("research metadata identity mismatch")
            if self.market.available_at > self.book.available_at:
                raise ValueError("future metadata cannot be research feature")
        if self.fee is not None:
            at = datetime.fromisoformat(self.fee["observed_at"])
            if at.tzinfo is None or at > self.book.available_at:
                raise ValueError("future fee cannot be research feature")
        return self


class ExperimentSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)
    schema_version: Literal["1.0"] = "1.0"
    experiment_id: str
    hypothesis: str
    dataset_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    model_version: str
    feature_definitions: dict[str, str]
    target_definitions: dict[str, str]
    split_policy: str
    training_interval: tuple[str, str] | None = None
    validation_interval: tuple[str, str] | None = None
    heldout_interval: tuple[str, str] | None = None
    grouping: dict = Field(default_factory=dict)
    transaction_cost_assumptions: dict = Field(default_factory=dict)
    failure_conditions: tuple[str, ...]
    limitations: tuple[str, ...]
    certification_authority: Literal[False] = False
    automatic_promotion: Literal[False] = False
