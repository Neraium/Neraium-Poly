"""Phase13 integration contracts: external observations are never backdated."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class SportsRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)
    schema_version: Literal["1.0"] = "1.0"


class SourceArtifact(SportsRecord):
    provider: str
    source_id: str
    source_url: str
    source_timestamp: datetime | None = None
    retrieved_at: datetime
    available_at: datetime
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    raw_path: str
    quality: Literal["qualified", "quarantined"]
    missingness: tuple[str, ...] = ()
    availability_basis: Literal["first_observed_retrieval"] = "first_observed_retrieval"

    @model_validator(mode="after")
    def causal(self):
        for t in (self.retrieved_at, self.available_at, self.source_timestamp):
            if t is not None and (t.tzinfo is None or t.utcoffset() is None):
                raise ValueError("UTC-aware source times required")
        if self.available_at < self.retrieved_at:
            raise ValueError("retrieved sources cannot claim earlier availability")
        if self.source_timestamp and self.source_timestamp > self.retrieved_at:
            raise ValueError("future source timestamp")
        return self


class SportsGame(SportsRecord):
    provider: str
    game_id: str
    league: Literal["NBA", "NFL"]
    home_id: str
    away_id: str
    home_name: str
    away_name: str
    starts_at: datetime
    status: Literal["scheduled", "in_progress", "final", "postponed", "canceled", "unknown"]
    home_score: int | None = Field(default=None, ge=0)
    away_score: int | None = Field(default=None, ge=0)
    result_observed_at: datetime | None = None
    artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    available_at: datetime
    includes_overtime: bool = True

    @model_validator(mode="after")
    def valid(self):
        for t in (self.starts_at, self.available_at, self.result_observed_at):
            if t is not None and (t.tzinfo is None or t.utcoffset() is None):
                raise ValueError("aware game timestamps required")
        if self.home_id == self.away_id:
            raise ValueError("distinct participants required")
        if self.status == "final" and (
            self.home_score is None or self.away_score is None or self.result_observed_at is None
            or self.result_observed_at > self.available_at or self.starts_at >= self.result_observed_at
        ):
            raise ValueError("final result requires observed causal score")
        return self


class SportsMapping(SportsRecord):
    event_id: str
    market_id: str
    token_id: str
    game_id: str
    league: Literal["NBA", "NFL"]
    provider: str
    selected_team_id: str
    opponent_team_id: str
    event_start: datetime
    rules_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    mapping_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    method: Literal["exact_alias_schedule_rules_v1"] = "exact_alias_schedule_rules_v1"
    includes_overtime: Literal[True] = True


class SportsPrediction(SportsRecord):
    game_id: str
    selected_team_id: str
    probability: float = Field(gt=0, lt=1)
    lower_probability: float = Field(ge=0, le=1)
    upper_probability: float = Field(ge=0, le=1)
    cutoff: datetime
    model_version: str
    model_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    feature_version: str
    dataset_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    training_games: int = Field(ge=1)
    participant_games: dict[str, int]
    uncertainty: dict
    calibration_status: Literal["unvalidated_prospective_research"] = "unvalidated_prospective_research"
    research_only: Literal[True] = True

    @model_validator(mode="after")
    def valid(self):
        if self.cutoff.tzinfo is None or not self.lower_probability <= self.probability <= self.upper_probability:
            raise ValueError("aware cutoff and containing uncertainty required")
        return self
