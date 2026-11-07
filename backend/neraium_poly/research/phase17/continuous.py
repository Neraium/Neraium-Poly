"""Prospective challengers consuming the existing committed Phase16 research stream."""

import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from threading import RLock

from pydantic import Field

from neraium_poly.contracts import Record
from neraium_poly.research.phase14.relationships import digest
from neraium_poly.research.phase16.checkpoints import pack_checkpoint, unpack_checkpoint
from neraium_poly.research.phase17.economics import evaluate_roundtrip
from neraium_poly.research.phase17.models import causal_forecasts
from neraium_poly.research.phase17.storage import storage_growth


class EmpiricalResearchUpdate(Record):
    parent_id: str | None = None
    source_study_id: str
    forecasts: list[dict] = Field(default_factory=list)
    scores: list[dict] = Field(default_factory=list)
    expired_forecasts: list[str] = Field(default_factory=list)
    checkpoint: dict
    checkpoint_sha256: str
    trading_authority: bool = False
    certification_authority: bool = False


def _at(value):
    at = value if isinstance(value, datetime) else datetime.fromisoformat(value)
    if at.tzinfo is None:
        raise ValueError("aware research timestamp required")
    return at.astimezone(UTC)


class EmpiricalResearch:
    """Fixed challengers never learn from account P/L or acquire order authority.

    A bounded verified full checkpoint accompanies each <=30second update in the
    existing archive. Raw forecasts and matched marks are immutable in that record.
    Missing labels expire explicitly; later quotes are never interpolated.
    """

    def __init__(self, store, *, activation_at):
        self.store, self.lock = store, RLock()
        self.code_sha256 = sha256(b"".join(Path(__file__).with_name(n).read_bytes()
            for n in ("continuous.py", "models.py", "economics.py", "storage.py"))).hexdigest()
        self.last_id = self.pending_commit = None
        self.last_error = None
        self.state = {"version": "phase17-prospective-marks-v1", "code_sha256": self.code_sha256,
            "activation_at": _at(activation_at).isoformat(), "last_at": None, "last_study_id": None,
            "pending": {}, "seen_forecasts": [], "scored": [], "recent": [], "parent_groups": [],
            "updates": 0, "forecast_points": 0, "matured_points": 0, "unexecutable_marks": 0,
            "expired": 0, "models": {}, "storage_samples": []}
        rows = store.latest("EmpiricalResearchUpdate", limit=1)
        if rows:
            row = EmpiricalResearchUpdate.model_validate(rows[0])
            state = unpack_checkpoint(row.checkpoint)
            if (digest(state) != row.checkpoint_sha256 or row.trading_authority or row.certification_authority
                or state.get("last_at") != row.available_at.isoformat()
                or state.get("last_study_id") != row.source_study_id):
                raise ValueError("empirical checkpoint integrity/time/source mismatch")
            self._restore(state)
            self.last_id = row.id

    def _restore(self, state):
        if state.get("version") != "phase17-prospective-marks-v1" or state.get("code_sha256") != self.code_sha256:
            raise ValueError("empirical model policy changed; evidence preserved, no silent reset")
        for field, limit in (("pending", 128), ("seen_forecasts", 256), ("scored", 256),
                             ("recent", 128), ("parent_groups", 128), ("models", 4), ("storage_samples", 128)):
            if not isinstance(state.get(field), (dict, list)) or len(state[field]) > limit:
                raise ValueError("bounded empirical checkpoint required")
        self.state = deepcopy(state)

    def observe(self, study, *, now):
        now = _at(now)
        with self.lock:
            if self.pending_commit:
                row, state = self.pending_commit
                self.store.append(row)
                self._restore(state)
                self.last_id, self.pending_commit = row.id, None
            before = deepcopy(self.state)
            if not study.last_at or not 0 <= (now-_at(study.last_at)).total_seconds() <= 15:
                self.last_error = "committed_source_study_stale"
                return False
            if (self.state["last_study_id"] == study.last_id or not study.last_id
                or self.state["last_at"] and (now-_at(self.state["last_at"])).total_seconds() < 30):
                return False
            forecasts, scores, expired = [], [], []
            try:
                # A forecast created now cannot retrospectively forecast old points.
                points = study.history.points()
                by_id = {p["id"]: p for p in points}
                for f in causal_forecasts(points, cutoff=now):
                    point_id = f["point_id"]
                    point = by_id[point_id]
                    if (point_id in self.state["seen_forecasts"] or point.get("execution_evidence_complete") is not True
                        or _at(point["observed_at"]) < _at(self.state["activation_at"])
                        or not 0 <= (now-_at(point["observed_at"])).total_seconds() <= 15
                        or not 0 <= (now-_at(point["source_at"])).total_seconds() <= 15):
                        continue
                    if len(forecasts) >= 8:
                        break
                    row = {**f, "decision": point, "created_at": now.isoformat(),
                           "target_at": (_at(point["observed_at"])+timedelta(seconds=60)).isoformat(),
                           "forecast_lead_seconds": 60-(now-_at(point["observed_at"])).total_seconds(),
                           "source_study_id": study.last_id, "semantics": "research monetary bid marks, not event probabilities",
                           "trading_authority": False}
                    self.state["pending"][point_id] = row
                    self.state["seen_forecasts"].append(point_id)
                    self.state["forecast_points"] += 1
                    forecasts.append(row)
                for pair in study.history.matured():
                    decision_id = pair["decision"]["id"]
                    forecast = self.state["pending"].get(decision_id)
                    if not forecast or pair["id"] in self.state["scored"]:
                        continue
                    if (digest(pair["decision"]) != digest(forecast["decision"])
                        or _at(forecast["created_at"]) >= _at(pair["label"]["source_at"])
                        or _at(pair["label_observed_at"]) > now):
                        raise ValueError("prospective forecast/label identity or cutoff mismatch")
                    costs = evaluate_roundtrip(pair["decision"], pair["label"])
                    actual, baseline = pair["actual_bid"], pair["unchanged_bid_baseline"]
                    detail = {"pair_id": pair["id"], "decision_id": decision_id,
                              "forecast_study_id": forecast["source_study_id"], "label_study_id": study.last_id,
                              "forecast_created_at": forecast["created_at"], "label": pair,
                              "costs": costs, "models": {}}
                    for name, value in forecast["forecasts"].items():
                        error, base_error = abs(value-actual), abs(baseline-actual)
                        model = self.state["models"].setdefault(name, {"scored": 0, "absolute_error_sum": 0.,
                            "baseline_absolute_error_sum": 0., "cost_observations": 0, "net_mark_sum_per_share": 0.})
                        model["scored"] += 1
                        model["absolute_error_sum"] += error
                        model["baseline_absolute_error_sum"] += base_error
                        net = costs.get("net_per_share")
                        if net is not None:
                            model["cost_observations"] += 1
                            model["net_mark_sum_per_share"] += net
                        detail["models"][name] = {"forecast": value, "actual_bid_mark": actual,
                            "absolute_error": error, "baseline_absolute_error": base_error}
                    self.state["matured_points"] += 1
                    self.state["unexecutable_marks"] += int(costs.get("net_per_share") is None)
                    self.state["scored"].append(pair["id"])
                    self.state["recent"].append({"event_id": pair["event_id"], "models": detail["models"]})
                    if pair["event_id"] not in self.state["parent_groups"]:
                        if len(self.state["parent_groups"]) >= 128:
                            raise ValueError("parent review capacity reached; new inference withheld")
                        self.state["parent_groups"].append(pair["event_id"])
                    self.state["pending"].pop(decision_id)
                    scores.append(detail)
                for key, pending in list(self.state["pending"].items()):
                    if (now-_at(pending["created_at"])).total_seconds() > 180:
                        expired.append(key)
                        self.state["pending"].pop(key)
                        self.state["expired"] += 1
                if len(self.state["pending"]) > 128:
                    raise ValueError("pending research capacity reached")
                for key, limit in (("seen_forecasts", 256), ("scored", 256), ("recent", 128)):
                    self.state[key] = self.state[key][-limit:]
                self.state["updates"] += 1
                self.state["last_at"], self.state["last_study_id"] = now.isoformat(), study.last_id
                if hasattr(self.store, "status"):
                    archive = self.store.status()
                    self.state["storage_samples"].append({"at": now.isoformat(), **{k: archive.get(k) for k in (
                        "usage_bytes", "tier_usage_bytes", "budget_bytes", "free_bytes", "global_floor_bytes")}})
                    self.state["storage_samples"] = self.state["storage_samples"][-128:]
                state = json.loads(json.dumps(self.state, sort_keys=True, allow_nan=False))
                row = EmpiricalResearchUpdate(id=digest(["phase17-update", self.last_id, study.last_id, digest(state)]),
                    timestamp=now, available_at=now, source="phase17-existing-phase16-research-stream",
                    parent_id=self.last_id, source_study_id=study.last_id, forecasts=forecasts, scores=scores,
                    expired_forecasts=expired, checkpoint=pack_checkpoint(state), checkpoint_sha256=digest(state))
                self.pending_commit = row, state
                self.store.append(row)
                self.last_id, self.pending_commit, self.last_error = row.id, None, None
                return True
            except Exception:
                self.state = before
                self.last_error = "empirical_update_not_committed"
                raise

    def summary(self):
        with self.lock:
            s = self.state
            models = {}
            for name, row in s["models"].items():
                n = row["scored"]
                recent = [r["models"][name] for r in s["recent"] if name in r["models"]]
                recent_difference = sum(r["absolute_error"]-r["baseline_absolute_error"] for r in recent)
                models[name] = {"scored_marks": n, "mae": row["absolute_error_sum"]/n if n else None,
                    "unchanged_bid_mae": row["baseline_absolute_error_sum"]/n if n else None,
                    "mean_observed_net_mark_per_share": row["net_mark_sum_per_share"]/row["cost_observations"] if row["cost_observations"] else None,
                    "brier": None, "log_loss": None, "confidence_interval": None,
                    "calibration_status": "not applicable to monetary marks",
                    "drift": "insufficient evidence" if len(recent) < 20 else
                        "research underperforms unchanged bid" if recent_difference > 0 else
                        "no independently supported improvement"}
            storage = {"status": "unavailable", "reason": "no verified storage samples"}
            if s["storage_samples"]:
                latest = s["storage_samples"][-1]
                storage = storage_growth(s["storage_samples"], now=datetime.now(UTC),
                    budget_bytes=latest["budget_bytes"], free_bytes=latest["free_bytes"],
                    min_free_bytes=latest["global_floor_bytes"])
            return {"status": "research_only", "activation_at": s["activation_at"], "last_evaluation_at": s["last_at"],
                "last_source_study_id": s["last_study_id"], "updates": s["updates"],
                "forecast_points": s["forecast_points"], "matured_points": s["matured_points"],
                "pending_points": len(s["pending"]), "expired_points": s["expired"],
                "unexecutable_marks": s["unexecutable_marks"], "unreviewed_parent_groups": len(s["parent_groups"]),
                "reviewed_independent_events": 0, "models": models, "code_sha256": self.code_sha256,
                "storage": storage,
                "counter_scope": "cumulative since persisted research activation; drift uses last128 matched marks; no account P/L inputs",
                "uncertainty_status": "insufficient reviewed independent groups; inferential scores unavailable",
                "last_error": self.last_error, "trading_authority": False, "certification_authority": False,
                "account_pnl": None, "threshold_change_authority": False}
