"""Bounded append-only research evidence; new models never acquire order authority."""

import json
from copy import deepcopy
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from threading import RLock

from pydantic import Field

from neraium_poly.contracts import Record
from neraium_poly.research.phase14.relationships import digest
from neraium_poly.research.phase16.execution import assess_execution
from neraium_poly.research.phase16.history import CausalHistory
from neraium_poly.research.phase16.readiness import build_readiness
from neraium_poly.research.phase16.relationships import RelationshipHistory


class QualificationStudy(Record):
    parent_id: str | None = None
    raw_frame: dict
    legacy_valuations: list[dict] = Field(default_factory=list)
    archive_measurement: dict = Field(default_factory=dict)
    result: dict
    checkpoint_sha256: str
    full_checkpoint: dict | None = None
    qualified: bool = False
    trading_authority: bool = False


class ContinuousQualification:
    """10second source studies; compact verified full checkpoints every300seconds.

    The last64records always cover the most recent full checkpoint at this
    cadence. A committed source study wins after an ambiguous write/restart.
    Entire original frames and all derived inputs are retained in the archive.
    """

    def __init__(self, store, *, interval=10, clock=None):
        if not 10 <= interval <= 60:
            raise ValueError("bounded qualification study cadence required")
        self.store, self.interval, self.clock = store, interval, clock
        self.code_sha256 = sha256(b"".join(Path(__file__).with_name(name).read_bytes() for name in (
            "continuous.py", "history.py", "relationships.py", "execution.py", "readiness.py", "checkpoints.py"))
            + Path(__file__).parents[1].joinpath("phase14/relationships.py").read_bytes()
            + Path(__file__).parents[1].joinpath("phase15/relationships.py").read_bytes()).hexdigest()
        self._lock = RLock()
        self._pending = None
        self.last_error = None
        self._initialize()
        rows = store.latest("QualificationStudy", limit=64)
        if rows:
            rows = list(reversed(rows))
            index = next((i for i in range(len(rows)-1, -1, -1) if rows[i].get("full_checkpoint")), None)
            if index is None:
                raise ValueError("research recovery checkpoint missing; history not reset")
            seed = QualificationStudy.model_validate(rows[index])
            from neraium_poly.research.phase16.checkpoints import unpack_checkpoint

            state = unpack_checkpoint(seed.full_checkpoint)
            if digest(state) != seed.checkpoint_sha256 or seed.qualified or seed.trading_authority:
                raise ValueError("qualification checkpoint integrity or authority mismatch")
            self._restore(state)
            if (self.last_at != seed.available_at.isoformat()
                or self.history.last_at != self.last_at or self.relationships.last_at != self.last_at
                or not self.last_full_at or datetime.fromisoformat(self.last_full_at) > seed.available_at):
                raise ValueError("qualification checkpoint time binding mismatch")
            self.last_id = seed.id
            for raw in rows[index+1:]:
                row = QualificationStudy.model_validate(raw)
                if (row.parent_id != self.last_id or row.qualified or row.trading_authority
                    or row.available_at <= datetime.fromisoformat(self.last_at)):
                    raise ValueError("qualification study chain mismatch")
                self._advance(row.raw_frame, now=row.available_at, valuations=row.legacy_valuations,
                              archive=row.archive_measurement)
                if digest(self._state()) != row.checkpoint_sha256:
                    raise ValueError("qualification deterministic recovery mismatch")
                self.last_id = row.id

    def _initialize(self):
        self.history = CausalHistory(max_tokens=8, history_size=96, max_labels=512)
        self.relationships = RelationshipHistory(max_pairs=3)
        self.cohort, self.storage_samples = [], []
        self.last_at = self.last_full_at = self.last_id = None
        self.latest_execution, self.latest_readiness = [], {}

    def _state(self):
        return deepcopy({"version": "phase16-continuous-v1", "interval": self.interval,
                "code_sha256": self.code_sha256,
                "history": self.history.checkpoint(), "relationships": self.relationships.checkpoint(),
                "cohort": self.cohort, "storage_samples": self.storage_samples,
                "last_at": self.last_at, "last_full_at": self.last_full_at,
                "execution": self.latest_execution, "readiness": self.latest_readiness})

    def _restore(self, value):
        if (value.get("version") != "phase16-continuous-v1" or value.get("interval") != self.interval
            or value.get("code_sha256") != self.code_sha256):
            raise ValueError("qualification checkpoint model policy differs")
        if len(value.get("cohort", [])) > 8 or len(value.get("storage_samples", [])) > 168:
            raise ValueError("bounded qualification checkpoint required")
        self.history.restore(value["history"])
        self.relationships.restore(value["relationships"])
        for key in ("cohort", "storage_samples", "last_at", "last_full_at"):
            setattr(self, key, deepcopy(value[key]))
        self.latest_execution, self.latest_readiness = deepcopy(value["execution"]), deepcopy(value["readiness"])

    def _select(self, frame, now):
        markets = {m["token_id"]: m for m in frame["markets"] if m.get("status") == "active"
                   and m.get("resolution_rules") and m.get("resolution_source")
                   and (not m.get("end_time") or datetime.fromisoformat(m["end_time"]) > now)}
        self.cohort = [t for t in self.cohort if t in markets]
        books = {b["token_id"]: b for b in frame["books"]}
        eligible = []
        for token in sorted(markets):
            if token in books:
                report = assess_execution(markets[token], books[token], now=now,
                                          fee_observation=frame.get("fees", {}).get(token))
                if report["execution_checks_pass"]:
                    eligible.append(token)
        # Deterministic same-parent YES pairs first; no target/outcome-based choice.
        groups = {}
        for token in eligible:
            m = markets[token]
            if m.get("outcome", "").casefold() == "yes":
                groups.setdefault(m["event_id"], []).append(token)
        preference = [t for group in sorted(groups) if len(groups[group]) >= 2 for t in groups[group][:2]]
        for token in dict.fromkeys(preference + eligible):
            if len(self.cohort) >= 8:
                break
            if token not in self.cohort:
                self.cohort.append(token)
        tokens = set(self.cohort)
        return {**{k: deepcopy(frame[k]) for k in ("id", "source", "timestamp", "available_at", "producer_health") if k in frame},
                "markets": [deepcopy(m) for m in frame["markets"] if m["token_id"] in tokens],
                "books": [deepcopy(b) for b in frame["books"] if b["token_id"] in tokens],
                "fees": {k: deepcopy(v) for k, v in frame.get("fees", {}).items() if k in tokens},
                "cohort_policy": "max8causal execution-compatible tokens; keep until inactive; shared-parent YES preference"}

    def _advance(self, frame, *, now, valuations, archive):
        self.last_at = now.isoformat()
        full_due = self.last_full_at is None or (now-datetime.fromisoformat(self.last_full_at)).total_seconds() >= 300
        if full_due:
            self.last_full_at = now.isoformat()
        self.history.observe(frame, now=now)
        self.relationships.observe(frame, now=now)
        self.cohort = [m["token_id"] for m in frame["markets"]]
        markets = {m["token_id"]: m for m in frame["markets"]}
        lower = {v["token_id"]: v.get("lower_value") for v in valuations
                 if v.get("strategy_id") == "short_horizon" and v.get("available_at")
                 and 0 <= (now-datetime.fromisoformat(v["available_at"])).total_seconds() <= 15}
        self.latest_execution = [assess_execution(markets[b["token_id"]], b, now=now,
            fee_observation=frame.get("fees", {}).get(b["token_id"]), forecast_lower_bid=lower.get(b["token_id"]))
            for b in frame["books"] if b["token_id"] in markets]
        eligible = set(build_readiness(self.history.summary(), now=now)["eligible_mark_tokens"])
        known = [r for r in self.latest_execution if r.get("estimated_net_edge_per_share") is not None
                 and r.get("token_id") in eligible and r.get("execution_checks_pass") is True]
        best = max(known, key=lambda r:r["estimated_net_edge_per_share"]) if known else {}
        self.latest_readiness = build_readiness(self.history.summary(), execution=best, now=now)
        if archive and (not self.storage_samples or (now-datetime.fromisoformat(self.storage_samples[-1]["at"])).total_seconds() >= 3600):
            self.storage_samples.append({"at": now.isoformat(), **{k: archive.get(k) for k in (
                "usage_bytes", "budget_bytes", "free_bytes", "global_floor_bytes", "records", "tier_usage_bytes")}})
            self.storage_samples = self.storage_samples[-168:]
        return full_due

    def observe(self, frame, *, now, signals=()):
        if now.tzinfo is None:
            raise ValueError("aware qualification cutoff required")
        now = now.astimezone(UTC)
        with self._lock:
            if self._pending is not None:
                row, state = self._pending
                self.store.append(row)
                self._restore(state)
                self.last_id = row.id
                self._pending = None
                self.last_error = None
            if self.last_at and (now-datetime.fromisoformat(self.last_at)).total_seconds() < self.interval:
                return False
            before, prior_id = self._state(), self.last_id
            try:
                small = self._select(frame, now)
                if not small["markets"]:
                    self.cohort = before["cohort"]
                    self.last_error = "no_execution_compatible_research_cohort"
                    return False
                tokens = set(self.cohort)
                valuations = [{k: getattr(v, k) for k in ("id", "strategy_id", "token_id", "lower_value", "estimated_net_edge", "eligible")}
                              | {"available_at": v.available_at.isoformat()} for v in signals if v.token_id in tokens]
                archive = self.store.status() if hasattr(self.store, "status") else {}
                full_due = self._advance(small, now=now, valuations=valuations, archive=archive)
                state = self._state()
                from neraium_poly.research.phase16.checkpoints import pack_checkpoint

                # Existing graph checkpoints contain tuples; canonical JSON
                # conversion is explicit before the strict lossless codec boundary.
                state = json.loads(json.dumps(state, sort_keys=True, allow_nan=False))
                encoded = pack_checkpoint(state) if full_due else None
                result = {"history": self.history.summary(), "relationships": self.relationships.summary(),
                          "execution": self.latest_execution, "qualification": self.latest_readiness}
                row = QualificationStudy(id=digest(["phase16-study", prior_id, self.last_at, digest(state)]),
                    timestamp=now, available_at=now, source="phase16-causal-qualification-research",
                    parent_id=prior_id, raw_frame=small, legacy_valuations=valuations, archive_measurement=archive,
                    result=result, checkpoint_sha256=digest(state), full_checkpoint=encoded)
                self._pending = (row, state)
                self.store.append(row)
                self._pending = None
                self.last_id, self.last_error = row.id, None
                return True
            except Exception:
                self._restore(before)
                self.last_id = prior_id
                self.last_error = "qualification_study_not_committed"
                raise

    def summary(self):
        with self._lock:
            return {"status": "research_only" if self.last_at else "warming_up", "last_study_at": self.last_at,
                    "history": self.history.summary(), "relationships": self.relationships.summary(),
                    "execution_checks": deepcopy(self.latest_execution), "qualification": deepcopy(self.latest_readiness),
                    "storage": {"hourly_measurements_retained": len(self.storage_samples),
                                "first_measurement_at": self.storage_samples[0]["at"] if self.storage_samples else None,
                                "scope": "service tree before study commit; includes archive copies/state/cache"},
                    "models": {"history": "phase16-causal-history-v1", "graph": "phase16-relationship-history-v1",
                               "challenger": "offline frozen-training bid-mark research; no operational authority"},
                    "model_code_sha256": self.code_sha256,
                    "interval_seconds": self.interval, "full_checkpoint_interval_seconds": 300,
                    "checkpoint_encoding": "bounded lossless canonical JSON gzip; existing archive retains original records",
                    "last_error": self.last_error, "trading_authority": False, "certification_authority": False}
