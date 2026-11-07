"""Bounded continuous relationship observations and research-only competition."""

import hashlib
import json
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from neraium_poly.contracts import Record
from neraium_poly.research.phase14.relationships import digest
from neraium_poly.research.phase16.checkpoints import pack_checkpoint, unpack_checkpoint


class CompetitionStudy(Record):
    operation: str = "research_competition"
    source_frame_id: str
    checkpoint: dict
    checkpoint_sha256: str
    trading_authority: Literal[False] = False
    certification_authority: Literal[False] = False



def competition_report(store, *, as_of, enrollments=None, evidence_root=None):
    """Read-only bounded report: reverify labels; never score asserted flags."""
    from .competition import build_leaderboard
    from .outcomes import verify_outcome

    retained = dict(enrollments or {})
    if not retained:
        prior = store.latest("CompetitionStudy", limit=1)
        if prior:
            row = CompetitionStudy.model_validate(prior[0])
            state = unpack_checkpoint(row.checkpoint)
            if digest(state) != row.checkpoint_sha256:
                raise ValueError("retained enrollment checkpoint integrity mismatch")
            retained = state.get("enrollments", {})
    studies = store.latest("ChallengerStudy", limit=256)
    for study in studies:
        if study.get("operation") == "enrollment":
            retained[study["id"]] = study
    ids = {s['id'] for s in studies}
    studies += [s for key,s in retained.items() if key not in ids]
    outcomes = [r for r in store.latest("ChallengerOutcomeStudy", limit=256) if r.get("outcome")]
    individual, errors = [], []
    def replay(row, _forecast):
        if evidence_root is None:
            raise ValueError("native proof directory required")
        raw = store.get(row['original_study_id'])
        if raw is None:
            raise ValueError("original forecast missing")
        study = raw if isinstance(raw, dict) else json.loads(raw[1])
        forecast = next(f for f in study['forecasts'] if f['id'] == row['forecast_id'])
        return verify_outcome(row,study,forecast,evidence_root=evidence_root,as_of=as_of)
    for row in outcomes:
        try:
            individual.append(replay(row,None))
        except (ValueError, KeyError, TypeError, OSError) as error:
            errors.append(str(error)[:160])
    report = build_leaderboard(studies,outcomes,as_of=as_of,outcome_verifier=replay)
    report['individual_verified_forecast_scores'] = individual
    report['individual_scores_scope'] = "descriptive verified forecasts; not independent events or statistical superiority"
    report['outcome_replay_errors'] = errors
    report['source_scope'] = "latest256 studies/outcomes plus immutable retained enrollments; not all-time performance"
    return report


class ContinuousCompetition:
    """No account or execution handles; bounded history is causal and recoverable."""

    def __init__(self, store, *, clock=None, can_write=None, interval=60, evidence_root=None):
        from .competition import build_leaderboard
        from .relationships import evaluate_relationships, project_frame

        if not 60 <= interval <= 3600:
            raise ValueError("bounded competition interval required")
        self.store, self.clock = store, clock or (lambda: datetime.now(UTC))
        self.evidence_root = evidence_root
        self.can_write, self.interval = can_write or (lambda: True), interval
        self.rank, self.relate, self.project = build_leaderboard, evaluate_relationships, project_frame
        self.code_sha = hashlib.sha256(b"".join(Path(__file__).with_name(x).read_bytes()
            for x in ("operations.py", "competition.py", "relationships.py"))).hexdigest()
        self.state = {"version": "phase23-competition-v1", "code_sha256": self.code_sha,
                      "cycles": 0, "last_at": None, "history": [], "enrollments": {}, "relationships": {}, "leaderboard": {}}
        rows = store.latest("CompetitionStudy", limit=1)
        if rows:
            row = CompetitionStudy.model_validate(rows[0])
            state = unpack_checkpoint(row.checkpoint)
            if digest(state) != row.checkpoint_sha256 or state.get("code_sha256") != self.code_sha:
                raise ValueError("competition checkpoint integrity or implementation mismatch")
            if state.get("last_at") != row.available_at.isoformat() or len(state.get("history", [])) > 16:
                raise ValueError("competition checkpoint bounds or timestamp mismatch")
            self.state = state

    def step(self, frame):
        frame = frame.model_dump(mode="json") if hasattr(frame, "model_dump") else frame
        now = self.clock()
        if now.tzinfo is None:
            raise ValueError("aware competition cutoff required")
        if self.state["last_at"] and (now-datetime.fromisoformat(self.state["last_at"])).total_seconds() < self.interval:
            return False
        if not self.can_write():
            return False
        state = deepcopy(self.state)
        projected = self.project(frame, cutoff=now)
        state["relationships"] = self.relate(frame, state["history"], cutoff=now)
        studies = self.store.latest("ChallengerStudy", limit=256)
        for study in studies:
            if study.get("operation") == "enrollment":
                previous = state["enrollments"].get(study["id"])
                if previous is not None and previous != study:
                    raise ValueError("immutable competition enrollment changed")
                state["enrollments"][study["id"]] = study
        source_ids = {study["id"] for study in studies}
        studies += [study for key, study in state["enrollments"].items() if key not in source_ids]
        state["leaderboard"] = competition_report(self.store, as_of=now, enrollments=state["enrollments"], evidence_root=self.evidence_root)
        state["history"] = (state["history"]+[projected])[-16:]
        state["last_at"], state["cycles"] = now.isoformat(), state["cycles"]+1
        row = CompetitionStudy(id=digest([self.code_sha, frame['id'], now.isoformat(), state['cycles']]),
            timestamp=now, available_at=now, source="neraium-poly/research-competition/v23",
            source_frame_id=frame['id'], checkpoint=pack_checkpoint(state), checkpoint_sha256=digest(state))
        if not self.can_write():
            return False
        # Publish state only after a successful durable append; failures leave the prior checkpoint intact.
        self.store.append(row)
        self.state = state
        return True

    def status(self):
        return {"status": "research_only", "last_at": self.state['last_at'], "cycles": self.state['cycles'],
                "history_frames": len(self.state['history']), "history_limit": 16,
                "relationships": deepcopy(self.state['relationships']),
                "leaderboard": deepcopy(self.state['leaderboard']),
                "code_sha256": self.code_sha, "trading_authority": False, "certification_authority": False}
