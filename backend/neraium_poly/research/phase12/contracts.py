"""Shared event, evidence, prospective forecast and verified outcome schemas."""

from datetime import datetime
from typing import Literal

from pydantic import Field, model_validator

from neraium_poly.contracts import Record

SHA = r"^[0-9a-f]{64}$"


class EventEvidence(Record):
    event_id: str
    market_id: str
    kind: Literal["market_price", "order_book", "resolution_rules", "external_context", "outcome", "metadata"]
    content_sha256: str = Field(pattern=SHA)
    payload: dict
    independent_of_market_price: bool = False


class CanonicalEvent(Record):
    event_id: str
    market_id: str
    question: str
    token_ids: tuple[str, ...] = ()
    outcomes: tuple[str, ...] = ()
    resolution_rules: str = ""
    resolution_source: str = ""
    created_at: datetime | None = None
    closes_at: datetime | None = None
    category: str = "Unknown"
    category_basis: str = "unverified"
    dependency_group: str
    independence_reviewed: bool = False
    evidence_ids: tuple[str, ...] = ()
    provenance: dict = Field(default_factory=dict)
    missing_fields: tuple[str, ...] = ()


class EventForecast(Record):
    event_id: str
    market_id: str
    token_id: str
    dependency_group: str
    independence_reviewed: bool = False
    category: str = "Unknown"
    kind: Literal["market_baseline", "historical_frequency", "independent_model"]
    probability: float = Field(ge=0, le=1)
    market_probability: float = Field(ge=0, le=1)
    evidence_cutoff: datetime
    model_version: str
    feature_version: str
    dataset_sha256: str = Field(pattern=SHA)
    model_sha256: str = Field(pattern=SHA)
    resolution_rules_sha256: str = Field(pattern=SHA)
    evidence_ids: tuple[str, ...]
    uncertainty: dict
    horizon_seconds: float | None = Field(default=None, gt=0)
    lower_probability: float | None = Field(default=None, ge=0, le=1)
    upper_probability: float | None = Field(default=None, ge=0, le=1)
    calibration_status: str = "unvalidated"
    certification_authority: Literal[False] = False

    @model_validator(mode="after")
    def causal(self):
        if self.evidence_cutoff.tzinfo is None or self.evidence_cutoff > self.timestamp:
            raise ValueError("aware preforecast evidence cutoff required")
        if not self.evidence_ids or not self.uncertainty:
            raise ValueError("forecast evidence and uncertainty required")
        if self.kind == "independent_model":
            if self.lower_probability is None or self.upper_probability is None:
                raise ValueError("independent forecast uncertainty bounds required")
            if not self.lower_probability <= self.probability <= self.upper_probability:
                raise ValueError("forecast outside uncertainty bounds")
        return self


class VerifiedEventOutcome(Record):
    event_id: str
    market_id: str
    token_id: str
    payout: Literal[0, 1]
    resolution_rules_sha256: str = Field(pattern=SHA)
    settled_at: datetime
    verification_source: str
    proof_sha256: str = Field(pattern=SHA)
    verification: dict

    @model_validator(mode="after")
    def finalized(self):
        if self.settled_at.tzinfo is None or self.settled_at > self.available_at:
            raise ValueError("verified past settlement time required")
        return self
