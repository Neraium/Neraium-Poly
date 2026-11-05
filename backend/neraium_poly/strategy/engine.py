"""Research models and opportunity qualification; no execution transport exists."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from math import isfinite, sqrt
from typing import Literal, Protocol

from pydantic import Field, field_validator, model_validator

from neraium_poly.contracts import (
    MarketSnapshot,
    ModelProvenance,
    OrderBookSnapshot,
    ProbabilityEstimate,
    Record,
    RelationshipEvidence,
    StrategyPerformance,
    TradingOpportunity,
)


def _id(*values: object) -> str:
    return sha256(repr(values).encode()).hexdigest()


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("timezone required")
    return value


class LabeledForecast(Record):
    """Historical forecast and separately timed settlement label.

    ``timestamp`` is forecast event time; ``available_at`` its availability, never
    settlement availability. One independent event per calibration observation.
    """

    market_id: str
    event_id: str
    probability: float = Field(ge=0, le=1)
    outcome: Literal[0, 1]
    label_available_at: datetime
    executable_price: float | None = Field(default=None, gt=0, lt=1)
    executable_quantity: float = Field(default=0, ge=0)
    protocol_fee_rate: float | None = Field(default=None, ge=0, le=1)

    @field_validator("label_available_at")
    @classmethod
    def label_timezone(cls, value):
        return _aware(value)

    @model_validator(mode="after")
    def label_after_prediction(self):
        if self.label_available_at <= self.available_at:
            raise ValueError("settlement label must follow forecast availability")
        return self


@dataclass(frozen=True)
class HistogramCalibrator:
    """Laplace-smoothed event-frequency calibration with Wilson uncertainty."""

    counts: tuple[int, ...]
    successes: tuple[int, ...]
    bins: int
    min_samples: int
    provenance: ModelProvenance

    @classmethod
    def fit(
        cls,
        records: Sequence[LabeledForecast],
        cutoff: datetime,
        bins: int = 5,
        min_samples: int = 30,
    ) -> "HistogramCalibrator":
        _aware(cutoff)
        if not 2 <= bins <= 100 or min_samples < 10:
            raise ValueError("invalid calibration policy")
        usable = sorted(
            (r for r in records if r.available_at < cutoff and r.label_available_at <= cutoff),
            key=lambda r: (r.available_at, r.id),
        )
        if not usable:
            raise ValueError("no labels available before cutoff")
        if len({r.id for r in usable}) != len(usable):
            raise ValueError("duplicate forecast ID")
        if len({r.event_id for r in usable}) != len(usable):
            raise ValueError("correlated labels: one observation per event required")
        counts, successes = [0] * bins, [0] * bins
        for record in usable:
            bucket = min(bins - 1, int(record.probability * bins))
            counts[bucket] += 1
            successes[bucket] += record.outcome
        artifact = _id(
            "histogram-calibrator/v1", bins, min_samples, tuple(r.model_dump_json() for r in usable)
        )
        provenance = ModelProvenance(
            id=artifact,
            timestamp=cutoff,
            available_at=cutoff,
            source="calibration-training/v1",
            model_name="histogram-event-frequency",
            model_version="1.0",
            training_end=cutoff,
            artifact_hash=artifact,
            approved=False,
            calibration_samples=len(usable),
        )
        return cls(tuple(counts), tuple(successes), bins, min_samples, provenance)

    def estimate(
        self, market: MarketSnapshot, now: datetime, evidence_ids: tuple[str, ...] = ()
    ) -> ProbabilityEstimate:
        _aware(now)
        if self.provenance.training_end >= now or market.available_at > now:
            raise ValueError("model or market unavailable at decision time")
        bucket = min(self.bins - 1, int(market.probability * self.bins))
        n, wins = self.counts[bucket], self.successes[bucket]
        probability = (wins + 1) / (n + 2)
        # Smoothed Wilson interval. Empty/small bins remain uncalibrated and broad.
        observations = n + 2
        z = 1.96
        denominator = 1 + z * z / observations
        center = (probability + z * z / (2 * observations)) / denominator
        radius = (
            z
            * sqrt(probability * (1 - probability) / observations + z * z / (4 * observations**2))
            / denominator
        )
        lower, upper = (
            max(0.0, min(probability, center - radius)),
            min(1.0, max(probability, center + radius)),
        )
        return ProbabilityEstimate(
            id=_id(self.provenance.id, market.id, now.isoformat(), evidence_ids),
            timestamp=now,
            available_at=now,
            source="histogram-calibrator/v1",
            market_id=market.market_id,
            token_id=market.token_id,
            probability=probability,
            lower=lower,
            upper=upper,
            model_id=self.provenance.id,
            calibrated=n >= self.min_samples,
            evidence_ids=evidence_ids,
        )


class ModelRegistry:
    """Registration never promotes; approval/rollback require actor audit records."""

    def __init__(self):
        self.models: dict[str, HistogramCalibrator] = {}
        self.approvals: dict[str, ModelProvenance] = {}
        self.active_id: str | None = None
        self.audit: list[dict] = []

    def register(self, model: HistogramCalibrator) -> str:
        mid = model.provenance.id
        if model.provenance.approved:
            raise ValueError("registered artifacts cannot self-approve")
        if mid in self.models and self.models[mid] != model:
            raise ValueError("model artifact collision")
        self.models[mid] = model
        return mid

    def approve(self, model_id: str, actor: str, now: datetime) -> ModelProvenance:
        _aware(now)
        if not actor.strip():
            raise ValueError("approval actor required")
        model = self.models[model_id]
        if model.provenance.available_at > now:
            raise ValueError("model unavailable")
        if model.provenance.calibration_samples < model.min_samples:
            raise ValueError("insufficient calibration samples")
        approved = model.provenance.model_copy(update={"approved": True, "available_at": now})
        self.approvals[model_id] = approved
        self.active_id = model_id
        self.audit.append(
            {"action": "approve", "actor": actor, "timestamp": now.isoformat(), "model_id": model_id}
        )
        return approved

    def rollback(self, model_id: str, actor: str, now: datetime) -> None:
        _aware(now)
        if model_id not in self.approvals or not actor.strip():
            raise ValueError("rollback requires previously approved model and actor")
        if self.approvals[model_id].available_at > now:
            raise ValueError("approval not yet available")
        self.active_id = model_id
        self.audit.append(
            {"action": "rollback", "actor": actor, "timestamp": now.isoformat(), "model_id": model_id}
        )

    def estimate(
        self, model_id: str, market: MarketSnapshot, now: datetime, evidence_ids: tuple[str, ...] = ()
    ) -> ProbabilityEstimate:
        if model_id != self.active_id or model_id not in self.approvals:
            raise ValueError("model not explicitly active and approved")
        if self.approvals[model_id].available_at > now:
            raise ValueError("approval not yet available")
        return self.models[model_id].estimate(market, now, evidence_ids)


class FeeModel(Protocol):
    def fee_per_share(self, price: float) -> float: ...
    def effective_notional_bound(self) -> float: ...


@dataclass(frozen=True)
class ProtocolFeeModel:
    """Explicit per-market protocol rate; no assumed category or default rate."""

    protocol_rate: float
    maker: bool = False

    def __post_init__(self):
        if not isfinite(self.protocol_rate) or not 0 <= self.protocol_rate <= 1:
            raise ValueError("invalid protocol fee rate")

    def effective_notional_bound(self) -> float:
        """Global BUY bound valid for all price improvements 0 < p < 1."""
        return 0 if self.maker else self.protocol_rate

    def fee_per_share(self, price: float) -> float:
        if not isfinite(price) or not 0 < price < 1:
            raise ValueError("invalid execution price")
        return 0 if self.maker else self.protocol_rate * price * (1 - price)


@dataclass(frozen=True)
class OpportunityPolicy:
    minimum_net_edge: float = 0.03
    latency_buffer: float = 0.005
    max_interval_width: float = 0.35
    max_spread: float = 0.1
    max_slippage: float = 0.03
    max_age_seconds: float = 30
    minimum_evidence_confidence: float = 0.7
    minimum_calibration_samples: int = 30

    def __post_init__(self):
        for name in (
            "minimum_net_edge",
            "latency_buffer",
            "max_interval_width",
            "max_spread",
            "max_slippage",
            "max_age_seconds",
            "minimum_evidence_confidence",
        ):
            value = getattr(self, name)
            if not isfinite(value) or value < 0:
                raise ValueError(f"invalid {name}")
        if self.minimum_calibration_samples < 10:
            raise ValueError("invalid sample policy")


class OpportunityRanker:
    """BUY-only expected net value at conservative fill price and lower probability."""

    def __init__(self, policy: OpportunityPolicy | None = None):
        self.policy = policy or OpportunityPolicy()
        self.last_reasons: tuple[str, ...] = ()

    def rank(
        self,
        market: MarketSnapshot,
        book: OrderBookSnapshot,
        estimate: ProbabilityEstimate,
        evidence: Sequence[RelationshipEvidence],
        provenance: ModelProvenance,
        now: datetime,
        quantity: float = 10,
        fee_model: FeeModel | None = None,
        tier: Literal["standard", "high", "exceptional"] = "standard",
    ) -> TradingOpportunity | None:
        _aware(now)
        reasons = []
        if not isfinite(quantity) or quantity <= 0:
            reasons.append("invalid_quantity")
        if quantity < market.min_order_size:
            reasons.append("below_exchange_minimum")
        if market.end_time is not None and (market.end_time.tzinfo is None or now >= market.end_time):
            reasons.append("market_expired_or_invalid_end_time")
        if market.exchange != book.exchange:
            reasons.append("exchange_mismatch")
        if market.status != "active" or not market.resolution_rules or not market.resolution_source:
            reasons.append("unverified_active_settlement")
        if (market.market_id, market.token_id) != (book.market_id, book.token_id) or (
            market.market_id,
            market.token_id,
        ) != (estimate.market_id, estimate.token_id):
            reasons.append("instrument_mismatch")
        records = [market, book, estimate, *evidence, provenance]
        if any(r.available_at > now or r.timestamp > now for r in records):
            reasons.append("future_input")
        if any(
            (now - r.timestamp).total_seconds() > self.policy.max_age_seconds
            for r in [market, book, estimate, *evidence]
        ):
            reasons.append("stale_input")
        if not book.complete or not book.asks or not book.bids:
            reasons.append("incomplete_order_book")
        if not provenance.approved or provenance.id != estimate.model_id or not provenance.artifact_hash:
            reasons.append("unapproved_model")
        if provenance.training_end.tzinfo is None or provenance.training_end >= now:
            reasons.append("training_lookahead")
        if (
            not estimate.calibrated
            or provenance.calibration_samples < self.policy.minimum_calibration_samples
        ):
            reasons.append("uncalibrated_estimate")
        if estimate.upper - estimate.lower > self.policy.max_interval_width:
            reasons.append("excessive_model_uncertainty")
        ids = {item.id for item in evidence}
        if (
            len(ids) != len(evidence)
            or not evidence
            or not set(estimate.evidence_ids)
            or set(estimate.evidence_ids) != ids
        ):
            reasons.append("missing_or_duplicate_evidence")
        if any(not e.qualified or e.confidence < self.policy.minimum_evidence_confidence for e in evidence):
            reasons.append("unqualified_evidence")
        sources = set()
        seen_observations = set()
        for item in evidence:
            if not item.observation_ids:
                reasons.append("evidence_provenance_missing")
            if (
                item.qualified
                and item.source not in sources
                and not (set(item.observation_ids) & seen_observations)
            ):
                sources.add(item.source)
                seen_observations.update(item.observation_ids)
        if tier == "exceptional" and len(sources) < 2:
            reasons.append("exceptional_independent_evidence_required")
        if fee_model is None:
            reasons.append("unknown_fee_schedule")
        if isinstance(fee_model, ProtocolFeeModel) and fee_model.maker:
            # An immediately marketable quote is taker liquidity, never maker.
            reasons.append("maker_fee_incompatible_with_taker_quote")
        if book.asks and book.bids and book.asks[0].price - book.bids[0].price > self.policy.max_spread:
            reasons.append("wide_spread")
        if reasons:
            self.last_reasons = tuple(reasons)
            return None
        assert fee_model is not None
        best = book.asks[0].price
        remaining = quantity
        levels = []
        for level in book.asks:
            if level.price - best > self.policy.max_slippage:
                break
            taken = min(remaining, level.size)
            levels.append((level.price, taken))
            remaining -= taken
            if remaining <= 1e-9:
                break
        if remaining > 1e-9:
            self.last_reasons = ("insufficient_executable_liquidity",)
            return None
        worst = levels[-1][0]
        # A proportional simulation reserve must cover every possible price
        # improvement, including later books. A spot fee/price ratio cannot.
        try:
            fee_bound = fee_model.effective_notional_bound()
            fee = worst * fee_bound
        except (AttributeError, ValueError, TypeError, ArithmeticError):
            self.last_reasons = ("invalid_fee_model",)
            return None
        if not isfinite(fee_bound) or not 0 <= fee_bound <= 1:
            self.last_reasons = ("invalid_fee_model",)
            return None
        net_edge = estimate.lower - worst - fee - self.policy.latency_buffer
        if net_edge < self.policy.minimum_net_edge:
            self.last_reasons = ("net_value_below_uncertainty_adjusted_threshold",)
            return None
        liquidity = sum(level.size for level in book.asks if level.price <= worst)
        self.last_reasons = ()
        return TradingOpportunity(
            id=_id(market.id, book.id, estimate.id, tuple(sorted(ids)), quantity, fee, worst, tier),
            timestamp=now,
            available_at=now,
            source="conservative-opportunity/v1",
            market_id=market.market_id,
            token_id=market.token_id,
            event_id=market.event_id,
            estimate_id=estimate.id,
            evidence_ids=tuple(sorted(ids)),
            side="BUY",
            market_probability=worst,
            estimated_probability=estimate.probability,
            conservative_probability=estimate.lower,
            net_edge=net_edge,
            fee_rate=fee_bound,
            slippage=worst - best,
            liquidity=liquidity,
            tier=tier,
            calibrated=estimate.calibrated,
            independent_evidence=len(sources),
        )


@dataclass(frozen=True)
class BacktestResult:
    performance: StrategyPerformance
    predictions: tuple[dict, ...]
    excluded_unsettled: int


def walk_forward(
    records: Sequence[LabeledForecast],
    evaluation_end: datetime,
    min_samples: int = 30,
    bins: int = 5,
    minimum_edge: float = 0.03,
    latency_buffer: float = 0.005,
) -> BacktestResult:
    """Expanding, event-purged walk-forward baseline on supplied executable quotes.

    At each decision only earlier forecasts with already available labels train.
    The test event is purged entirely. Results settle only by evaluation_end.
    This tests a fixed BUY rule on supplied quote depth, not queue/maker dynamics.
    """
    _aware(evaluation_end)
    if not isfinite(minimum_edge) or minimum_edge < 0 or not isfinite(latency_buffer) or latency_buffer < 0:
        raise ValueError("invalid backtest cost policy")
    if len({r.id for r in records}) != len(records):
        raise ValueError("duplicate replay record")
    ordered = sorted(records, key=lambda r: (r.available_at, r.id))
    result = []
    pnl = 0.0
    peak = 0.0
    drawdown = 0.0
    trades = 0
    brier = []
    excluded = 0
    traded_events = set()
    for row in ordered:
        if row.available_at > evaluation_end or row.label_available_at > evaluation_end:
            excluded += 1
            continue
        train = [r for r in ordered if r.event_id != row.event_id and r.label_available_at < row.available_at]
        if len(train) < min_samples:
            continue
        model = HistogramCalibrator.fit(train, row.available_at, bins, min_samples)
        # Estimate at decision time while provenance cutoff is epsilon earlier;
        # fit sees strictly earlier labels, with no test-event contamination.
        bucket = min(bins - 1, int(row.probability * bins))
        n, wins = model.counts[bucket], model.successes[bucket]
        p = (wins + 1) / (n + 2)
        if n < min_samples:
            continue
        z = 1.96
        d = 1 + z * z / (n + 2)
        lower = (p + z * z / (2 * (n + 2)) - z * sqrt(p * (1 - p) / (n + 2) + z * z / (4 * (n + 2) ** 2))) / d
        brier.append((p - row.outcome) ** 2)
        trade_pnl = 0.0
        traded = False
        price = row.executable_price
        if (
            price is not None
            and row.protocol_fee_rate is not None
            and row.executable_quantity > 0
            and row.event_id not in traded_events
        ):
            fee = ProtocolFeeModel(row.protocol_fee_rate).fee_per_share(price)
            if lower - price - fee - latency_buffer >= minimum_edge:
                # Fixed $2 target, clipped to documented executable shares.
                quantity = min(2 / (price + fee + latency_buffer), row.executable_quantity)
                trade_pnl = quantity * (row.outcome - price - fee - latency_buffer)
                pnl += trade_pnl
                trades += 1
                traded = True
                traded_events.add(row.event_id)
        result.append(
            {
                "record_id": row.id,
                "decision_at": row.available_at.isoformat(),
                "training_ids": tuple(r.id for r in train),
                "probability": p,
                "lower": lower,
                "outcome": row.outcome,
                "traded": traded,
                "simulated_pnl": trade_pnl,
                "settled_at": row.label_available_at.isoformat(),
            }
        )
    equity = 0.0
    for item in sorted(result, key=lambda item: (item["settled_at"], item["record_id"])):
        equity += item["simulated_pnl"]
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    dataset_hash = _id(tuple(r.model_dump_json() for r in ordered))
    performance = StrategyPerformance(
        id=_id(
            "walk-forward/v1",
            dataset_hash,
            evaluation_end.isoformat(),
            min_samples,
            bins,
            minimum_edge,
            latency_buffer,
        ),
        timestamp=evaluation_end,
        available_at=evaluation_end,
        source="walk-forward-synthetic-or-user-data/v1",
        strategy_id="calibrated-lower-bound-buy/v1",
        trades=trades,
        simulated_pnl=pnl,
        realized_pnl=0,
        max_drawdown=drawdown,
        brier_score=sum(brier) / len(brier) if brier else None,
        dataset_hash=dataset_hash,
        out_of_sample=True,
    )
    return BacktestResult(performance, tuple(result), excluded)
