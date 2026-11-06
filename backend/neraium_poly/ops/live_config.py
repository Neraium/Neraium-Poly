"""Bounded single-owner real-market paper operation."""

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator

from neraium_poly.risk import RiskLimits


class LivePaperConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)
    data_dir: Path = Path("data/paper-live")
    host: str = "127.0.0.1"
    port: int = Field(default=18742, ge=1024, le=65535)
    max_markets: int = Field(default=50, ge=1, le=200)
    page_size: int = Field(default=50, ge=1, le=100)
    max_pages: int = Field(default=4, ge=1, le=10)
    books_per_cycle: int = Field(default=100, ge=1, le=400)
    cycle_interval_seconds: float = Field(default=5, ge=1, le=300)
    discovery_interval_seconds: float = Field(default=300, ge=10, le=3600)
    max_archive_mb: int = Field(default=512, ge=1, le=4096)
    min_free_disk_mb: int = Field(default=2048, ge=100)
    max_relationships: int = Field(default=200, ge=1, le=1000)
    max_book_age_seconds: float = Field(default=15, gt=0, le=60)
    max_fee_age_seconds: float = Field(default=300, gt=0, le=3600)
    owner_public_key: Path | None = None
    allow_simulated_settlement: bool = False
    settlement_rule_hashes: dict[str, str] = Field(default_factory=dict)
    settlement_review_actor: str = ""
    position_tier: str = "standard"
    position_notional: float = Field(default=2, gt=0, le=25)
    risk_limits: RiskLimits = Field(default_factory=RiskLimits)

    @model_validator(mode="after")
    def safety(self):
        if self.allow_simulated_settlement and (
            not self.settlement_rule_hashes or not self.settlement_review_actor.strip()
        ):
            raise ValueError("simulated settlement requires separately reviewed token rule hashes and actor")
        if self.host != "127.0.0.1":
            raise ValueError("operational API must bind loopback")
        if self.position_tier not in ("standard", "high", "exceptional"):
            raise ValueError("unknown allocation tier")
        low = getattr(self.risk_limits, self.position_tier + "_min")
        high = getattr(self.risk_limits, self.position_tier + "_max")
        if not low <= self.position_notional <= high:
            raise ValueError("notional outside configured risk tier")
        return self
