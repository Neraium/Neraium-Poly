"""Versioned multi-domain evidence/model boundaries with explicit probability semantics."""
from datetime import datetime
from typing import Literal, Protocol

from pydantic import Field, model_validator

from neraium_poly.contracts import Record

Domain = Literal["weather", "crypto", "finance", "economics", "politics", "sports", "esports",
                 "technology", "science", "geopolitics", "entertainment", "other"]
SHA = r"^[0-9a-f]{64}$"


class DomainMarket(Record):
    event_id: str
    market_id: str
    token_ids: tuple[str, ...]
    domain: Domain
    classification_basis: str
    classification_review_required: bool = True
    question: str
    resolution_rules: str
    resolution_source: str
    rules_sha256: str = Field(pattern=SHA)
    status: str
    metadata: dict = Field(default_factory=dict)
    support_status: str = "interpretation_review_required"


class DomainContract(Record):
    domain: Domain
    event_id: str
    market_id: str
    token_id: str
    contract_type: str
    probability_semantics: Literal["binary_event_probability", "expected_payout", "outcome_distribution", "unsupported"]
    rules_sha256: str = Field(pattern=SHA)
    parameters: dict
    compatible: bool = False
    review_required: bool = True
    reasons: tuple[str, ...] = ()


class DomainEvidence(Record):
    domain: Domain
    provider: str
    source_id: str
    retrieved_at: datetime
    source_timestamp: datetime | None = None
    content_sha256: str = Field(pattern=SHA)
    payload: dict
    availability_basis: Literal["first_observed_retrieval"] = "first_observed_retrieval"
    independent_of_polymarket: bool = False
    qualification: Literal["qualified_research", "unqualified", "unavailable"] = "unqualified"
    missingness: tuple[str, ...] = ()

    @model_validator(mode="after")
    def causal(self):
        if self.retrieved_at.tzinfo is None or self.available_at < self.retrieved_at:
            raise ValueError("external evidence availability cannot precede actual retrieval")
        if self.source_timestamp and (self.source_timestamp.tzinfo is None or self.source_timestamp > self.retrieved_at):
            raise ValueError("aware nonfuture publication timestamp required")
        return self


class DomainForecast(Record):
    domain: Domain
    event_id: str
    market_id: str
    token_id: str
    contract_type: str
    probability_semantics: Literal["binary_event_probability", "expected_payout", "outcome_distribution"]
    probability: float | None = Field(default=None, ge=0, le=1)
    outcome_probabilities: dict[str, float] = Field(default_factory=dict)
    evidence_cutoff: datetime
    model_version: str
    model_sha256: str = Field(pattern=SHA)
    feature_version: str
    dataset_sha256: str = Field(pattern=SHA)
    rules_sha256: str = Field(pattern=SHA)
    evidence_ids: tuple[str, ...]
    uncertainty: dict
    calibration_status: str = "unvalidated_research"
    independent_of_polymarket: bool = False
    dependency_group: str
    independence_reviewed: Literal[False] = False
    contemporaneous_market: dict
    research_only: Literal[True] = True
    trading_authority: Literal[False] = False
    certification_authority: Literal[False] = False

    @model_validator(mode="after")
    def qualified_shape(self):
        if self.evidence_cutoff.tzinfo is None or self.evidence_cutoff > self.timestamp:
            raise ValueError("aware preforecast cutoff required")
        if not self.evidence_ids or not self.uncertainty:
            raise ValueError("supporting evidence and uncertainty required")
        if self.probability_semantics != "outcome_distribution" and self.probability is None:
            raise ValueError("typed probability required")
        if self.probability_semantics == "outcome_distribution":
            values = self.outcome_probabilities.values()
            if not self.outcome_probabilities or any(not 0 <= p <= 1 for p in values) or abs(sum(values)-1) > 1e-10:
                raise ValueError("normalized outcome distribution required")
        return self


class DomainModel(Protocol):
    domain: str
    model_version: str
    supported_contract_types: tuple[str, ...]

    def forecast(self, contract: DomainContract, evidence: tuple[DomainEvidence, ...], *, cutoff: datetime) -> dict:
        """Return independently derived probabilities or explicit qualification failures."""
        ...
