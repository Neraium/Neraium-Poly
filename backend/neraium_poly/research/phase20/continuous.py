"""Crash-safe prospective SII enrollment in the existing managed event archive.

An unavailable frozen challenger produces a durable rejection, never an invented
probability. Existing forecasts are not retroactively enrolled as prospective.
"""

import json
from copy import deepcopy
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

from neraium_poly.contracts import Record
from neraium_poly.research.phase14.relationships import digest
from neraium_poly.research.phase19.qualification import replay_event_forecast
from neraium_poly.research.phase20.ab import declare_experiment, prospective_pair


def _at(value):
    at = value if isinstance(value, datetime) else datetime.fromisoformat(value)
    if at.tzinfo is None:
        raise ValueError("aware prospective research time required")
    return at.astimezone(UTC)


class PairedForecastStudy(Record):
    parent_id: str | None = None
    operation: str
    experiment: dict
    result: dict
    checkpoint: dict
    checkpoint_sha256: str
    trading_authority: bool = False
    certification_authority: bool = False


class ProspectiveABResearch:
    """Observe new original forecasts only; no broker, risk or account dependency."""

    def __init__(self, store, *, baseline_model_sha256, clock=None, can_write=None):
        self.store, self.clock = store, clock or (lambda: datetime.now(UTC))
        self.can_write = can_write or (lambda: True)
        self.code_sha256 = sha256(b"".join(Path(__file__).with_name(n).read_bytes()
            for n in ("continuous.py", "ab.py"))).hexdigest()
        self.last_id = self.pending = self.last_error = None
        rows = store.latest("PairedForecastStudy", limit=1)
        if rows:
            row = PairedForecastStudy.model_validate(rows[0])
            state = row.checkpoint
            if (digest(state) != row.checkpoint_sha256 or state.get("code_sha256") != self.code_sha256
                or state.get("last_at") != row.available_at.isoformat()
                or state.get("experiment_sha256") != digest(row.experiment)
                or row.trading_authority or row.certification_authority
                or (baseline_model_sha256 is not None and row.experiment.get("baseline_model_sha256") != baseline_model_sha256)):
                raise ValueError("paired research checkpoint policy or integrity mismatch; no reset")
            self.state, self.experiment, self.last_id = deepcopy(state), deepcopy(row.experiment), row.id
        else:
            now = _at(self.clock())
            self.experiment = declare_experiment(experiment_id="phase20-sii-controlled-v1",
                declared_at=now, heldout_start=now, baseline_model_sha256=baseline_model_sha256,
                execution_assumptions={"source": "same original native book for both arms",
                    "fees": "native evidence required; missing costs deny executable edge",
                    "slippage": "depth sweep plus existing conservative controls",
                    "account_authority": False, "sii_critical_trading_path": False})
            self.state = {"code_sha256": self.code_sha256, "experiment_sha256": digest(self.experiment),
                "declared_at": now.isoformat(), "last_at": None, "last_source_id": None, "last_source_at": None,
                "observations": 0, "paired": 0, "withheld": 0, "rejections": {}}
            if not self._ready():
                raise ValueError("paired declaration storage backpressure")
            self._commit(operation="experiment_declaration", result={"status": "awaiting_qualified_sii_challenger"})
        # An original committed immediately before a crash remains discoverable.
        # Late enrollment is an explicit gap rejection, never a backdated pair.
        self.catch_up(store.latest("EventProbabilityStudy", limit=1000))


    def _ready(self):
        try:
            return self.can_write() is True
        except Exception:  # noqa: BLE001 - unavailable storage cannot create prospective records
            return False

    def _reconcile(self):
        if self.pending:
            self.store.append(self.pending)
            self.state, self.last_id = deepcopy(self.pending.checkpoint), self.pending.id
            self.pending, self.last_error = None, None

    def _commit(self, *, operation, result):
        now = _at(self.clock())
        self.state["last_at"] = now.isoformat()
        row = PairedForecastStudy(id=digest(["phase20-study", self.last_id, self.state, result]),
            timestamp=now, available_at=now, source="neraium-poly/controlled-sii-research/v20",
            parent_id=self.last_id, operation=operation, experiment=deepcopy(self.experiment),
            result=deepcopy(result), checkpoint=deepcopy(self.state), checkpoint_sha256=digest(self.state))
        self.pending = row
        self.store.append(row)
        self.last_id, self.pending, self.last_error = row.id, None, None
        return True

    def catch_up(self, originals):
        if not isinstance(originals, list) or len(originals) > 1000 or len(json.dumps(originals)) > 64*1024**2:
            raise ValueError("bounded paired recovery snapshot required")
        frontier = self.state["last_source_at"] or self.state["declared_at"]
        if len(originals) == 1000 and min(_at(s["available_at"]) for s in originals) > _at(frontier):
            raise ValueError("paired recovery archive gap; no silent enrollment loss")
        for original in sorted(originals, key=lambda s: (s["available_at"], s["id"])):
            if _at(original["available_at"]) <= _at(self.clock()):
                self.observe(original)

    def observe(self, original):
        self._reconcile()
        if not self._ready():
            self.last_error = "paired_research_storage_backpressure"
            return False
        if not original.get("forecast") or original.get("operation") != "forecast_scan":
            return False
        source_id = original.get("id")
        if not source_id or source_id == self.state["last_source_id"]:
            return False
        # Enrollment begins at the immutable declaration, never at an old forecast.
        if _at(original["forecast"]["timestamp"]) <= _at(self.state["declared_at"]):
            return False
        if self.state["last_source_at"] and _at(original["available_at"]) <= _at(self.state["last_source_at"]):
            return False
        before = deepcopy(self.state)
        try:
            result = prospective_pair(original, experiment=self.experiment, now=_at(self.clock()),
                verify_forecast=replay_event_forecast)
            if (_at(self.clock())-_at(original["forecast"]["timestamp"])).total_seconds() > 15:
                result.update(status="withheld", pair=None, reasons=["missed_timely_enrollment_after_recovery"])
                result.pop("record_sha256", None)
                result["record_sha256"] = digest(result)
            self.state["observations"] += 1
            self.state["last_source_id"] = source_id
            self.state["last_source_at"] = original["available_at"]
            paired = result["status"] == "paired_research"
            self.state["paired"] += paired
            self.state["withheld"] += not paired
            for reason in result.get("reasons", []):
                rejections = self.state["rejections"]
                key = reason[:160] if reason[:160] in rejections or len(rejections) < 32 else "other_bounded_rejection"
                rejections[key] = rejections.get(key, 0)+1
            return self._commit(operation="prospective_pair", result=result)
        except Exception:
            self.state = before
            self.last_error = "paired_record_not_committed"
            raise

    def summary(self):
        return {"status": "research_only", "declared_at": self.state["declared_at"],
            "last_evaluation_at": self.state["last_at"], "experiment_sha256": digest(self.experiment),
            "observations": self.state["observations"], "paired": self.state["paired"],
            "withheld": self.state["withheld"], "rejections": deepcopy(self.state["rejections"]),
            "sii_challenger": "unavailable; frozen trained model and qualified relationship evidence required",
            "brier_improvement": None, "log_loss_improvement": None, "after_cost_edge": None,
            "sii_in_trading_path": False, "last_error": self.last_error,
            "counter_scope": "new prospective forecasts since declaration; no historical backfill",
            "trading_authority": False, "certification_authority": False}
