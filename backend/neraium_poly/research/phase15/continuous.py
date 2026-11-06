"""Durable research-only SII cycles in the existing bounded evidence archive."""

from copy import deepcopy
from datetime import datetime
from threading import RLock

from neraium_poly.contracts import Record
from neraium_poly.research.phase15.relationships import RelationshipResearch, digest


class RelationshipStudy(Record):
    raw_sources: dict
    result: dict
    checkpoint: dict
    checkpoint_sha256: str
    qualified: bool = False
    trading_authority: bool = False


class ContinuousRelationships:
    def __init__(self, store, *, interval=20):
        if not 20 <= interval <= 3600:
            raise ValueError("bounded relationship cadence required")
        self.store, self.interval = store, interval
        self.engine = RelationshipResearch(max_pairs=3)
        self.last_error = None
        self._lock = RLock()
        self._pending = None
        previous = store.latest("RelationshipStudy", limit=1)
        if previous:
            row = RelationshipStudy.model_validate(previous[0])
            if row.checkpoint_sha256 != digest(row.checkpoint) or row.trading_authority or row.qualified:
                raise ValueError("research checkpoint authority or integrity mismatch")
            self.engine.restore(row.checkpoint)

    def observe(self, frame, *, now):
        with self._lock:
            return self._observe(frame, now=now)

    def _observe(self, frame, *, now):
        if self._pending is not None:
            # Reconcile an ambiguous segment-before-catalog commit idempotently
            # before advancing the research timeline. Restart uses durable latest.
            self.store.append(self._pending)
            self.engine.restore(self._pending.checkpoint)
            self._pending = None
            self.last_error = None
        if self.engine.last_at and (now - datetime.fromisoformat(self.engine.last_at)).total_seconds() < self.interval:
            return False
        before = self.engine.checkpoint()
        try:
            result = self.engine.observe(frame, observed_at=now)
            tokens = {d[side + "_id"] for d in self.engine.definitions.values() for side in ("left", "right")}
            # Persist the exact bounded inputs actually evaluated, independently of
            # the rolling service checkpoint. A committed study wins on restart.
            raw = {key: [deepcopy(v) for v in frame[key] if v.get("token_id") in tokens]
                   for key in ("markets", "books")}
            checkpoint = self.engine.checkpoint()
            self._pending = RelationshipStudy(
                id=digest(["phase15-study", now.isoformat(), digest(raw)]),
                timestamp=now, available_at=now, source="phase15-source-relationship-research",
                raw_sources=raw, result=result, checkpoint=checkpoint,
                checkpoint_sha256=digest(checkpoint))
            self.store.append(self._pending)
            self._pending = None
            self.last_error = None
            return True
        except Exception:
            self.engine = RelationshipResearch(max_pairs=3)
            self.engine.restore(before)
            self.last_error = "relationship_cycle_not_committed"
            raise

    def summary(self):
        with self._lock:
            return {**self.engine.summary(), "last_error": self.last_error,
                    "pending_commit_reconciliation": self._pending is not None,
                    "persistence": "append-only RelationshipStudy in managed service archive",
                    "interval_seconds": self.interval}
