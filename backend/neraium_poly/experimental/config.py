"""Explicit bounded configuration for the isolated unvalidated account."""

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator

from neraium_poly.experimental.feed import loopback_url
from neraium_poly.risk import RiskLimits

STRATEGIES = (
    "cross_market_consistency",
    "persistent_relationship",
    "liquidity_spread",
    "event_driven",
    "short_horizon",
    "calibrated_forecast",
)


class ExperimentalConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)
    data_dir: Path = Path("data/experimental-paper")
    certified_directory: Path = Path("data/paper-live")
    qualification_report_path: Path | None = Path("data/phase9qualification/qualified-v2/report.json")
    research_report_path: Path | None = Path("data/phase11-results/latest.json")
    event_model_report_path: Path | None = Path("data/phase12-results/latest.json")
    event_research_enabled: bool = True
    sports_research_enabled: bool = True
    phase16_research_enabled: bool = False
    phase17_research_enabled: bool = False
    phase18_event_research_enabled: bool = False
    phase20_ab_research_enabled: bool = False
    phase21_early_outcomes_enabled: bool = False
    phase23_research_enabled: bool = False
    phase24_research_enabled: bool = False
    phase25_research_enabled: bool = False
    phase26_intelligence_enabled: bool = False
    phase16_execution_veto_enabled: bool = False
    phase15_relationship_research_enabled: bool = False
    domain_research_enabled: bool = False
    event_dataset_path: Path | None = Path("data/phase12/dataset-v3")
    event_forecast_interval: float = Field(default=300, ge=60, le=86400)
    event_forecasts_per_cycle: int = Field(default=6, ge=1, le=20)
    event_ledger_mb: int = Field(default=64, ge=1, le=128)
    source_url: str = "http://127.0.0.1:18742/api/market-frame"
    host: str = "127.0.0.1"
    port: int = Field(default=18743, ge=1024, le=65535)
    enabled_strategies: tuple[str, ...] = STRATEGIES
    max_tokens: int = Field(default=64, ge=2, le=400)
    poll_seconds: float = Field(default=5, ge=1, le=300)
    fee_batch: int = Field(default=8, ge=0, le=20)
    fee_ttl_seconds: float = Field(default=300, gt=0, le=300)
    max_archive_mb: int = Field(default=512, ge=1, le=2048)
    min_free_disk_mb: int = Field(default=8192, ge=512)
    archive_management_enabled: bool = False
    archive_budget_mb: int = Field(default=16384, ge=64, le=131072)
    archive_segment_mb: int = Field(default=8, ge=1, le=1024)
    archive_reserve_disk_mb: int = Field(default=65536, ge=8192)
    archive_compression_enabled: bool = True
    archive_cold_verification_enabled: bool = False
    position_notional: float = Field(default=2, ge=2, le=5)
    risk_limits: RiskLimits = Field(default_factory=RiskLimits)

    @model_validator(mode="after")
    def isolated(self):
        if self.archive_segment_mb >= self.archive_budget_mb:
            raise ValueError("archive segment must be smaller than total service budget")
        loopback_url(self.source_url)
        if self.host != "127.0.0.1" or self.port in (18740, 18741, 18742):
            raise ValueError("experimental API requires separate loopback port")
        a, b = self.data_dir.resolve(), self.certified_directory.resolve()
        if a == b or a in b.parents or b in a.parents:
            raise ValueError("experimental and certified storage must be disjoint")
        if len(set(self.enabled_strategies)) != len(self.enabled_strategies) or set(
            self.enabled_strategies
        ) - set(STRATEGIES):
            raise ValueError("unknown or duplicate experimental strategy")
        if self.risk_limits.bankroll != 500:
            raise ValueError("initial experimental bankroll must remain500; no silent migration")
        return self
