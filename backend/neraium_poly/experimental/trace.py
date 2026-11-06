"""Bounded diagnostic counters, never a trading authorization mechanism."""

from collections import deque
from copy import deepcopy
from datetime import datetime
from math import isfinite

from neraium_poly.experimental.trace_contracts import COUNTER_SCOPE, STAGES


def category_for(reason):
    """Classify a gate, not an assertion that its input is defective."""
    if reason in {"changed_book_identity", "book_market_identity_mismatch", "wrong_token"}:
        return "BUG"
    if "not_supported" in reason:
        return "STRATEGY LIMITATION"
    if any(s in reason for s in ("calibration", "verified_labels", "certified", "approval")):
        return "CERTIFICATION DEPENDENCY"
    if any(
        s in reason for s in ("edge_insufficient", "large_spread", "inactive", "market_ended", "uncertainty")
    ):
        return "MARKET CONDITION"
    if any(
        s in reason
        for s in (
            "risk_",
            "exposure",
            "concentration",
            "kill",
            "suspend",
            "drawdown",
            "loss_limit",
            "capital",
            "reservation",
        )
    ):
        return "RISK REJECTION"
    return "MISSING EVIDENCE"


class DecisionTrace:
    """Persisted Phase10 epoch; per-cycle counts replace, epoch counts accumulate.

    Idempotency covers the most recent 8192 admission/execution identifiers. The
    durable broker ledger remains the authoritative lifetime idempotency guard.
    Samples and reason cardinality are bounded independently from counters.
    """

    def __init__(self, *, epoch_started_at=None, max_samples=3):
        if not 0 <= max_samples <= 8:
            raise ValueError("bounded trace sample count required")
        self.epoch_started_at = self._time(epoch_started_at) if epoch_started_at else None
        self.last_evaluation_at = None
        self.max_samples = max_samples
        self.phase10_epoch = {"strategies": {}}
        self.latest_cycle = {"strategies": {}}
        self._seen = deque(maxlen=8192)
        self._seen_set = set()

    @staticmethod
    def _time(now):
        if isinstance(now, str):
            now = datetime.fromisoformat(now)
        if not isinstance(now, datetime) or now.tzinfo is None:
            raise ValueError("aware trace time required")
        return now.isoformat()

    def _once(self, event):
        if event in self._seen_set:
            return False
        if len(self._seen) == self._seen.maxlen:
            self._seen_set.remove(self._seen[0])
        self._seen.append(event)
        self._seen_set.add(event)
        return True

    def _rows(self, strategy):
        if not isinstance(strategy, str) or len(strategy) > 80:
            raise ValueError("invalid trace strategy")
        for scope in (self.phase10_epoch, self.latest_cycle):
            if strategy not in scope["strategies"] and len(scope["strategies"]) >= 16:
                raise ValueError("trace strategy bound exceeded")
            yield scope["strategies"].setdefault(strategy, {**dict.fromkeys(STAGES, 0), "reasons": {}})

    def _reason(self, row, reason, count=1, sample=None, category=None):
        reason = str(reason).split(":", 1)[0][:120]
        if reason not in row["reasons"] and len(row["reasons"]) >= 128:
            reason = "other_bounded_reasons"
        entry = row["reasons"].setdefault(
            reason, {"category": category or category_for(reason), "count": 0, "samples": []}
        )
        entry["count"] += count
        if sample and len(entry["samples"]) < self.max_samples and sample not in entry["samples"]:
            entry["samples"].append(sample)

    def record_engine(self, frame, signals, engine_status, now, details=None):
        at = self._time(now)
        self.epoch_started_at = self.epoch_started_at or at
        self.last_evaluation_at = at
        self.latest_cycle = {"strategies": {}}
        details = details if details is not None else engine_status.get("latest_cycle", {})
        if not details:
            # Compatibility fallback describes emitted signals only; considered
            # counters stay unknown/zero rather than invent pre-dedup counts.
            details = {}
            for signal in signals:
                row = details.setdefault(signal.strategy_id, {"reasons": {}})
                for key, value in (
                    ("rejected_signals", not signal.eligible),
                    ("qualified_opportunities", signal.eligible),
                ):
                    row[key] = row.get(key, 0) + int(value)
                for reason in signal.reasons:
                    row["reasons"][reason] = row["reasons"].get(reason, 0) + 1
        for strategy, counts in details.items():
            for row in self._rows(strategy):
                for key in (*STAGES, "emitted_signals", "duplicate_signals"):
                    value = counts.get(key, 0)
                    if not isinstance(value, int) or value < 0:
                        raise ValueError("invalid trace counter")
                    row[key] = row.get(key, 0) + value
                for reason, count in counts.get("reasons", {}).items():
                    if not isinstance(count, int) or count < 0:
                        raise ValueError("invalid trace reason count")
                    examples = [s for s in signals if s.strategy_id == strategy and reason in s.reasons]
                    sample = self._sample(examples[0]) if examples else None
                    self._reason(row, reason, count, sample)

    @staticmethod
    def _sample(signal):
        return {
            "signal_id": signal.id,
            "market_id": signal.market_id,
            "token_id": signal.token_id,
            "timestamp": signal.timestamp.isoformat(),
            "estimated_net_edge": signal.estimated_net_edge,
            "diagnostics": dict(signal.diagnostics),
        }

    def record_admission(self, signal, result, now):
        self._time(now)
        if not self._once("admission:" + signal.id):
            return
        intent = result.get("intent")
        attempted = bool(intent or result.get("risk_evaluated"))
        risk = result.get("risk_decision") or {}
        risk_rejected = attempted and (
            risk.get("approved") is False
            or any(str(r).startswith("risk_unavailable") for r in result.get("reasons", []))
        )
        for row in self._rows(signal.strategy_id):
            row["order_attempts"] += int(attempted)
            row["submitted_orders"] += int(result.get("status") == "submitted")
            row["risk_rejections"] += int(risk_rejected)
            for reason in set(result.get("reasons", [])):
                self._reason(
                    row,
                    reason,
                    sample=self._sample(signal),
                    category="RISK REJECTION" if risk_rejected else None,
                )

    def record_execution(self, strategy_id, eventid, status, filled_delta, now, **details):
        self._time(now)
        if not isinstance(eventid, str) or not eventid or len(eventid) > 256:
            raise ValueError("execution event identity required")
        if not isfinite(filled_delta) or filled_delta < 0:
            raise ValueError("nonnegative fill delta required")
        if not self._once("execution:" + eventid):
            return
        for row in self._rows(strategy_id):
            row["fills"] += int(filled_delta > 0)
            side = str(details.get("side", "BUY")).upper()
            key = "exit_fills" if side == "SELL" else "entry_fills"
            row[key] = row.get(key, 0) + int(filled_delta > 0)
            row["expired_orders"] += int(status == "expired")
            row["cancelled_orders"] += int(status in {"cancelled", "canceled"})

    def status(self):
        return deepcopy(
            {
                "schema_version": "1.0",
                "epoch_started_at": self.epoch_started_at,
                "last_evaluation_at": self.last_evaluation_at,
                "counter_scope": COUNTER_SCOPE,
                "phase10_epoch": self.phase10_epoch,
                "latest_cycle": self.latest_cycle,
            }
        )

    def checkpoint(self):
        return {**self.status(), "recent_event_ids": list(self._seen), "max_samples": self.max_samples}

    def restore(self, data):
        if data.get("schema_version") != "1.0" or len(data.get("recent_event_ids", [])) > 8192:
            raise ValueError("invalid trace checkpoint")
        # Bound the entire diagnostic payload before adopting persisted data.
        import json

        if len(json.dumps(data)) > 4_000_000:
            raise ValueError("oversized trace checkpoint")
        for scope in ("phase10_epoch", "latest_cycle"):
            rows = data[scope]["strategies"]
            if len(rows) > 16:
                raise ValueError("oversized trace strategies")
            for row in rows.values():
                if len(row.get("reasons", {})) > 128:
                    raise ValueError("oversized trace reasons")
                if any(not isinstance(row.get(k, 0), int) or row.get(k, 0) < 0 for k in STAGES):
                    raise ValueError("invalid restored trace count")
                if any(len(r.get("samples", [])) > 8 for r in row.get("reasons", {}).values()):
                    raise ValueError("oversized trace samples")
        self.epoch_started_at = self._time(data["epoch_started_at"]) if data["epoch_started_at"] else None
        self.last_evaluation_at = (
            self._time(data["last_evaluation_at"]) if data["last_evaluation_at"] else None
        )
        self.phase10_epoch = deepcopy(data["phase10_epoch"])
        self.latest_cycle = deepcopy(data["latest_cycle"])
        self._seen = deque(data["recent_event_ids"], maxlen=8192)
        self._seen_set = set(self._seen)
