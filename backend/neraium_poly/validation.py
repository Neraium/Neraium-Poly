"""Explicit, hash-bound validation and durable approval of real-data research.

Passing checks do not establish that a supplied file is authentic. Provenance
review is an explicit human/research attestation, retained with the data hashes.
No data, model or approval is bundled; no market price becomes its own label.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from statistics import mean, stdev
from threading import RLock
from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator

from neraium_poly.contracts import MarketRelationship, MarketSnapshot, OrderBookSnapshot
from neraium_poly.strategy import HistogramCalibrator, LabeledForecast, ModelRegistry, ProtocolFeeModel


def _now(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("timezone required")
    return value.astimezone(UTC)


def _hash(data: bytes) -> str:
    return sha256(data).hexdigest()


def _json(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _source(value: str) -> bool:
    parsed = urlparse(value)
    return (
        parsed.scheme == "https"
        and bool(parsed.hostname)
        and not any(term in value.lower() for term in ("synthetic", "fixture", "localhost", "127.0.0.1"))
    )


class ValidationPolicy(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)
    minimum_train_events: int = Field(default=100, ge=100)
    minimum_heldout_events: int = Field(default=100, ge=100)
    minimum_bin_samples: int = Field(default=30, ge=30)
    bins: int = Field(default=5, ge=2, le=100)
    minimum_brier_improvement: float = Field(default=0.005, ge=0.005)
    maximum_brier: float = Field(default=0.20, gt=0, le=0.20)
    maximum_calibration_error: float = Field(default=0.08, gt=0, le=0.08)
    maximum_interval_width: float = Field(default=0.35, gt=0, le=0.35)
    maximum_book_age_seconds: float = Field(default=15, gt=0, le=15)
    minimum_heldout_trades: int = Field(default=20, ge=20)
    minimum_net_edge: float = Field(default=0.03, ge=0.03)
    latency_slippage_per_share: float = Field(default=0.01, ge=0.005)
    maximum_approval_days: int = Field(default=7, ge=1, le=30)
    maximum_dataset_bytes: int = Field(default=20_000_000, gt=0, le=100_000_000)


class ValidationObservation(LabeledForecast):
    partition: Literal["train", "heldout"]
    book: OrderBookSnapshot
    independent_evidence_source: str
    independent_evidence_ref: str
    independent_evidence_available_at: datetime
    settlement_source: str
    settlement_ref: str
    settlement_verified: bool

    @field_validator("independent_evidence_available_at")
    @classmethod
    def evidence_clock(cls, value):
        return _now(value)

    def forecast(self) -> LabeledForecast:
        return LabeledForecast.model_validate({k: getattr(self, k) for k in LabeledForecast.model_fields})


class ValidationManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal["1.0"] = "1.0"
    data_origin: Literal["real", "synthetic", "unknown"]
    exchange: Literal["polymarket"] = "polymarket"
    dataset_sha256: str
    train_cutoff: datetime
    expires_at: datetime
    provenance_reviewed: bool = False
    provenance_reviewer: str = ""
    collection_description: str = ""
    independent_signal_description: str = ""
    label_method: str = ""
    relationships: tuple[MarketRelationship, ...] = ()
    relationship_tokens: dict[str, str] = {}
    settlement_reviews: dict[str, bool] = {}
    correlation_groups: dict[str, str] = {}
    allowed_tiers: tuple[Literal["standard", "high", "exceptional"], ...] = ("standard",)

    @field_validator("train_cutoff", "expires_at")
    @classmethod
    def clocks(cls, value):
        return _now(value)


class ValidationReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)
    id: str
    timestamp: datetime
    passed: bool
    reasons: tuple[str, ...]
    dataset_hash: str
    manifest_hash: str
    model_id: str | None = None
    train_events: int = 0
    heldout_events: int = 0
    heldout_trades: int = 0
    brier_score: float | None = None
    market_brier_score: float | None = None
    brier_improvement_lower95: float | None = None
    calibration_error: float | None = None
    simulated_pnl: float = 0
    trade_pnl_lower95: float | None = None
    policy: ValidationPolicy


@dataclass(frozen=True)
class Activation:
    registry: ModelRegistry
    model_id: str
    relationships: tuple[MarketRelationship, ...]
    relationship_tokens: dict[str, str]
    settlement_reviews: dict[str, bool]
    correlation_groups: dict[str, str]
    report_id: str
    approved_at: datetime
    expires_at: datetime
    allowed_tiers: tuple[str, ...]


def _lower95(values: Sequence[float]) -> float:
    return mean(values) - 1.96 * stdev(values) / len(values) ** 0.5 if len(values) > 1 else float("-inf")


class ValidationStore:
    """SQLite stores immutable input bytes, reports, reviews and active identity.

    Validation does not approve. Explicit approval revalidates the exact stored
    inputs under the exact stored policy. Loading verifies every bound digest.
    """

    def __init__(self, path: str | Path, policy: ValidationPolicy | None = None):
        self.policy = policy or ValidationPolicy()
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path), isolation_level=None, check_same_thread=False, timeout=10)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS validation_reports (
            id TEXT PRIMARY KEY, report TEXT NOT NULL, dataset BLOB NOT NULL,
            manifest BLOB NOT NULL, policy TEXT NOT NULL, payload_digest TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS strategy_reviews (
            seq INTEGER PRIMARY KEY, timestamp TEXT NOT NULL, actor TEXT NOT NULL,
            action TEXT NOT NULL, report_id TEXT, reason TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS active_strategy (
            id INTEGER PRIMARY KEY CHECK(id=1), report_id TEXT NOT NULL,
            approved_at TEXT NOT NULL, actor TEXT NOT NULL);
        """)
        self._lock = RLock()
        self.last_error: str | None = None

    def validate(
        self, dataset_path: str | Path, manifest_path: str | Path, now: datetime
    ) -> ValidationReport:
        _now(now)
        paths = [Path(dataset_path), Path(manifest_path)]
        if any(p.stat().st_size > self.policy.maximum_dataset_bytes for p in paths):
            raise ValueError("validation input exceeds size budget")
        return self._validate(paths[0].read_bytes(), paths[1].read_bytes(), now, self.policy, save=True)

    def _validate(
        self, dataset: bytes, manifest_raw: bytes, now: datetime, policy: ValidationPolicy, *, save: bool
    ) -> ValidationReport:
        now = _now(now)
        dataset_hash, manifest_hash = _hash(dataset), _hash(manifest_raw)
        identity = _hash((dataset_hash + manifest_hash + policy.model_dump_json() + now.isoformat()).encode())
        reasons = []
        metrics = {}
        model = None
        try:
            manifest = ValidationManifest.model_validate_json(manifest_raw)
            raw = json.loads(dataset)
            if not isinstance(raw, list) or not raw:
                raise ValueError("nonempty observation array required")
            observations = [ValidationObservation.model_validate(row) for row in raw]
        except (ValueError, TypeError, KeyError):
            reasons.append("malformed_dataset_or_manifest")
            manifest, observations = None, []
        if manifest:
            if manifest.dataset_sha256 != dataset_hash:
                reasons.append("dataset_hash_mismatch")
            if manifest.data_origin != "real":
                reasons.append("real_observations_required")
            if not manifest.provenance_reviewed or not manifest.provenance_reviewer.strip():
                reasons.append("independent_provenance_review_required")
            if (
                len(manifest.collection_description.strip()) < 20
                or len(manifest.independent_signal_description.strip()) < 20
            ):
                reasons.append("independent_signal_and_collection_description_required")
            if manifest.label_method != "verified_final_resolution":
                reasons.append("verified_resolution_labels_required")
            if manifest.train_cutoff >= now or not now < manifest.expires_at <= now + timedelta(
                days=policy.maximum_approval_days
            ):
                reasons.append("invalid_validation_window")
            if not manifest.relationships or not manifest.allowed_tiers:
                reasons.append("explicit_strategy_scope_required")
            if len({r.id for r in manifest.relationships}) != len(manifest.relationships):
                reasons.append("duplicate_relationship_scope")
            for relationship in manifest.relationships:
                if relationship.available_at > now or len(set(relationship.market_ids)) < 2:
                    reasons.append("invalid_relationship_scope")
                if relationship.kind != "statistical" and (
                    not relationship.rule_verified
                    or not relationship.rule_description
                    or not manifest.settlement_reviews.get(relationship.id, False)
                ):
                    reasons.append("unsupported_settlement_assumption")
        train = [r for r in observations if r.partition == "train"]
        heldout = [r for r in observations if r.partition == "heldout"]
        if len({r.id for r in observations}) != len(observations) or len(
            {r.event_id for r in observations}
        ) != len(observations):
            reasons.append("duplicate_or_correlated_events")
        if len(train) < policy.minimum_train_events:
            reasons.append("insufficient_training_events")
        if len(heldout) < policy.minimum_heldout_events:
            reasons.append("insufficient_heldout_events")
        for row in observations:
            if (
                not _source(row.source)
                or not _source(row.independent_evidence_source)
                or not _source(row.settlement_source)
            ):
                reasons.append("untrusted_or_synthetic_provenance")
            if (urlparse(row.independent_evidence_source).hostname or "").endswith("polymarket.com"):
                reasons.append("market_prices_are_not_independent_evidence")
            if not row.independent_evidence_ref or not row.settlement_ref or not row.settlement_verified:
                reasons.append("missing_evidence_or_verified_settlement")
            if row.independent_evidence_available_at > row.available_at or row.label_available_at > now:
                reasons.append("unavailable_independent_evidence_or_label")
            if manifest and (
                (
                    row.partition == "train"
                    and (
                        row.available_at >= manifest.train_cutoff
                        or row.label_available_at > manifest.train_cutoff
                    )
                )
                or (row.partition == "heldout" and row.available_at <= manifest.train_cutoff)
            ):
                reasons.append("training_or_holdout_leakage")
            book = row.book
            if (
                book.source != "https://clob.polymarket.com"
                or book.market_id != row.market_id
                or not book.complete
                or not book.asks
                or not book.bids
            ):
                reasons.append("missing_executable_order_book")
            age = (row.available_at - book.timestamp).total_seconds()
            if book.available_at > row.available_at or not 0 <= age <= policy.maximum_book_age_seconds:
                reasons.append("stale_or_future_validation_book")
            if row.executable_price is None or row.executable_quantity <= 0 or row.protocol_fee_rate is None:
                reasons.append("missing_executable_cost_inputs")
            elif book.asks and (
                abs(row.executable_price - book.asks[0].price) > 1e-9
                or row.executable_quantity > book.asks[0].size + 1e-9
            ):
                reasons.append("unsupported_executable_depth")
        if not reasons and manifest:
            forecasts = [r.forecast() for r in train]
            model = HistogramCalibrator.fit(
                forecasts, manifest.train_cutoff, policy.bins, policy.minimum_bin_samples
            )
            errors, baseline_errors, improvements, trade_pnls, calibration = [], [], [], [], []
            for row in sorted(heldout, key=lambda r: (r.available_at, r.id)):
                market = MarketSnapshot(
                    id=row.id,
                    timestamp=row.timestamp,
                    available_at=row.available_at,
                    source=row.source,
                    market_id=row.market_id,
                    event_id=row.event_id,
                    token_id=row.book.token_id,
                    question="Held-out labeled observation",
                    probability=row.probability,
                )
                estimate = model.estimate(market, row.available_at)
                if not estimate.calibrated or estimate.upper - estimate.lower > policy.maximum_interval_width:
                    reasons.append("uncalibrated_or_uncertain_heldout_bin")
                error = (estimate.probability - row.outcome) ** 2
                baseline = (row.probability - row.outcome) ** 2
                errors.append(error)
                baseline_errors.append(baseline)
                improvements.append(baseline - error)
                calibration.append((estimate.probability, row.outcome))
                # The same conservative notional bound as paper execution, plus latency/slippage.
                price = row.executable_price
                fee = price * ProtocolFeeModel(row.protocol_fee_rate).effective_notional_bound()
                cost = price + fee + policy.latency_slippage_per_share
                if estimate.lower - cost >= policy.minimum_net_edge:
                    qty = min(2 / cost, row.executable_quantity * 0.10)
                    trade_pnls.append(qty * (row.outcome - cost))
            calibration_error = 0.0
            for bucket in range(policy.bins):
                entries = [
                    (p, y) for p, y in calibration if min(policy.bins - 1, int(p * policy.bins)) == bucket
                ]
                if entries:
                    calibration_error += (
                        len(entries)
                        / len(calibration)
                        * abs(mean(p for p, _ in entries) - mean(y for _, y in entries))
                    )
            improvement = _lower95(improvements)
            trade_lower = _lower95(trade_pnls) if len(trade_pnls) > 1 else None
            if mean(errors) > policy.maximum_brier or calibration_error > policy.maximum_calibration_error:
                reasons.append("heldout_calibration_failed")
            if improvement < policy.minimum_brier_improvement:
                reasons.append("heldout_improvement_not_supported")
            if len(trade_pnls) < policy.minimum_heldout_trades or trade_lower is None or trade_lower <= 0:
                reasons.append("cost_adjusted_heldout_edge_not_supported")
            metrics = {
                "brier_score": mean(errors),
                "market_brier_score": mean(baseline_errors),
                "brier_improvement_lower95": improvement,
                "calibration_error": calibration_error,
                "heldout_trades": len(trade_pnls),
                "simulated_pnl": sum(trade_pnls),
                "trade_pnl_lower95": trade_lower,
            }
        report = ValidationReport(
            id=identity,
            timestamp=now,
            passed=not reasons,
            reasons=tuple(sorted(set(reasons))),
            dataset_hash=dataset_hash,
            manifest_hash=manifest_hash,
            model_id=model.provenance.id if model else None,
            train_events=len(train),
            heldout_events=len(heldout),
            policy=policy,
            **metrics,
        )
        if save:
            report_json = report.model_dump_json()
            digest = _hash(dataset + manifest_raw + policy.model_dump_json().encode() + report_json.encode())
            with self._lock:
                existing = self.db.execute(
                    "SELECT id FROM validation_reports WHERE id=?", (identity,)
                ).fetchone()
                if existing:
                    return self._stored(identity)[0]
                self.db.execute(
                    "INSERT INTO validation_reports VALUES(?,?,?,?,?,?)",
                    (identity, report_json, dataset, manifest_raw, policy.model_dump_json(), digest),
                )
        return report

    def _stored(self, report_id):
        row = self.db.execute("SELECT * FROM validation_reports WHERE id=?", (report_id,)).fetchone()
        if row is None:
            raise ValueError("validation report missing")
        digest = _hash(
            bytes(row["dataset"]) + bytes(row["manifest"]) + row["policy"].encode() + row["report"].encode()
        )
        if digest != row["payload_digest"]:
            raise ValueError("validation storage integrity failure")
        report = ValidationReport.model_validate_json(row["report"])
        return (
            report,
            bytes(row["dataset"]),
            bytes(row["manifest"]),
            ValidationPolicy.model_validate_json(row["policy"]),
        )

    def approve(self, report_id: str, actor: str, now: datetime) -> str:
        now = _now(now)
        if not actor.strip():
            raise ValueError("explicit approval actor required")
        with self._lock:
            report, data, raw, policy = self._stored(report_id)
            if now < report.timestamp:
                raise ValueError("approval precedes validation")
            checked = self._validate(data, raw, now, policy, save=False)
            if not report.passed or not checked.passed or checked.model_id != report.model_id:
                raise ValueError(
                    "strategy validation has not passed: " + ",".join(checked.reasons or report.reasons)
                )
            if policy != self.policy:
                raise ValueError("active validation policy differs; validate again")
            self.db.execute("BEGIN IMMEDIATE")
            try:
                self.db.execute(
                    "INSERT INTO strategy_reviews(timestamp,actor,action,report_id,reason) VALUES(?,?,?,?,?)",
                    (now.isoformat(), actor, "approve", report_id, "explicit passing real-data approval"),
                )
                self.db.execute(
                    "INSERT OR REPLACE INTO active_strategy VALUES(1,?,?,?)",
                    (report_id, now.isoformat(), actor),
                )
                self.db.execute("COMMIT")
            except BaseException:
                self.db.execute("ROLLBACK")
                raise
        return report_id

    def revoke(self, actor: str, now: datetime, reason: str):
        now = _now(now)
        if not actor.strip() or not reason.strip():
            raise ValueError("actor and revocation reason required")
        with self._lock:
            self.db.execute("BEGIN IMMEDIATE")
            try:
                self.db.execute(
                    "INSERT INTO strategy_reviews(timestamp,actor,action,report_id,reason) SELECT ?,?,'revoke',report_id,? FROM active_strategy WHERE id=1",
                    (now.isoformat(), actor, reason),
                )
                self.db.execute("DELETE FROM active_strategy WHERE id=1")
                self.db.execute("COMMIT")
            except BaseException:
                self.db.execute("ROLLBACK")
                raise

    def load_active(self, now: datetime) -> Activation | None:
        now = _now(now)
        self.last_error = None
        try:
            with self._lock:
                active = self.db.execute("SELECT * FROM active_strategy WHERE id=1").fetchone()
                if active is None:
                    self.last_error = "no_explicit_real_strategy_approval"
                    return None
                review = self.db.execute(
                    "SELECT * FROM strategy_reviews ORDER BY seq DESC LIMIT 1"
                ).fetchone()
                if (
                    review is None
                    or review["action"] != "approve"
                    or any(review[column] != active[column] for column in ("report_id", "actor"))
                    or review["timestamp"] != active["approved_at"]
                ):
                    raise ValueError("explicit_approval_audit_missing_or_changed")
                report, data, raw, policy = self._stored(active["report_id"])
                manifest = ValidationManifest.model_validate_json(raw)
                at = datetime.fromisoformat(active["approved_at"])
                if (
                    not report.passed
                    or policy != self.policy
                    or not report.timestamp <= at <= now < manifest.expires_at
                ):
                    raise ValueError("strategy_approval_expired_or_invalid")
                train = [
                    ValidationObservation.model_validate(r).forecast()
                    for r in json.loads(data)
                    if r["partition"] == "train"
                ]
                model = HistogramCalibrator.fit(
                    train, manifest.train_cutoff, policy.bins, policy.minimum_bin_samples
                )
                if model.provenance.id != report.model_id:
                    raise ValueError("model_artifact_hash_mismatch")
                registry = ModelRegistry()
                model_id = registry.register(model)
                registry.approve(model_id, active["actor"], at)
                return Activation(
                    registry,
                    model_id,
                    manifest.relationships,
                    manifest.relationship_tokens,
                    manifest.settlement_reviews,
                    manifest.correlation_groups,
                    report.id,
                    at,
                    manifest.expires_at,
                    manifest.allowed_tiers,
                )
        except (ValueError, TypeError, KeyError, sqlite3.Error):
            self.last_error = "approval_integrity_expiry_or_storage_failure"
            return None

    def status(self, now: datetime) -> dict:
        active = self.load_active(now)
        try:
            with self._lock:
                rows = self.db.execute("SELECT report FROM validation_reports").fetchall()
                reports = [ValidationReport.model_validate_json(r[0]) for r in rows]
            return {
                "active": active is not None,
                "report_id": active.report_id if active else None,
                "model_id": active.model_id if active else None,
                "reports": len(reports),
                "passing_reports": sum(r.passed for r in reports),
                "latest_report": reports[-1].model_dump(mode="json") if reports else None,
                "blockers": [] if active else [self.last_error or "no_approved_strategy"],
                "requirements": [
                    "At least 100 independent training events and 100 heldout events",
                    "Point-in-time executable books and independent evidence with verified final labels",
                    "Heldout calibration, confidence-bounded improvement and cost-adjusted edge",
                    "Explicit provenance review and separate actor approval; no automatic promotion",
                ],
            }
        except (ValueError, TypeError, sqlite3.Error):
            return {"active": False, "blockers": ["validation_storage_unavailable"]}

    def close(self):
        self.db.close()
