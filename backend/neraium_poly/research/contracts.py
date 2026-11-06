"""Shared Phase8 evidence contracts. Unknown availability is never backdated."""

from datetime import datetime
from typing import Literal

from pydantic import Field, field_validator

from neraium_poly.contracts import OrderBookSnapshot, Record


class ResearchEvent(Record):
    market_id: str
    event_id: str
    token_id: str
    question: str
    category: str = "unknown"
    created_at: datetime | None = None
    closed_at: datetime | None = None
    resolution_rules: str = ""
    resolution_source: str = ""
    outcome: int | None = Field(default=None, ge=0, le=1)
    outcome_verified: bool = False
    settlement_at: datetime | None = None
    settlement_ref: str = ""
    volume: float | None = Field(default=None, ge=0)
    liquidity: float | None = Field(default=None, ge=0)
    availability_basis: Literal["collected_now", "verified_archive"] = "collected_now"
    raw_sha256: str
    raw_ref: str

    @field_validator("created_at", "closed_at", "settlement_at")
    @classmethod
    def optional_time(cls, value):
        if value is not None and value.tzinfo is None:
            raise ValueError("timezone required")
        return value


class ResearchPrice(Record):
    market_id: str
    event_id: str
    token_id: str
    probability: float = Field(ge=0, le=1)
    availability_basis: Literal["collected_now", "verified_archive"] = "collected_now"
    raw_sha256: str
    raw_ref: str


class ResearchContext(Record):
    event_id: str
    kind: str
    value: float | None = None
    reference: str
    independent: bool
    availability_basis: Literal["collected_now", "verified_archive"] = "collected_now"
    raw_sha256: str


class ResearchBundle(Record):
    events: tuple[ResearchEvent, ...] = ()
    prices: tuple[ResearchPrice, ...] = ()
    books: tuple[OrderBookSnapshot, ...] = ()
    context: tuple[ResearchContext, ...] = ()
    manifest_sha256: str
    deficiencies: tuple[str, ...] = ()
