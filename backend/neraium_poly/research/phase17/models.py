"""Frozen causal quote-mark hypotheses; never independent event probabilities."""

import hashlib
import json
from collections import defaultdict, deque
from datetime import UTC, datetime
from math import isfinite
from statistics import median

CANDIDATES = ("unchanged", "reversion20", "momentum20", "depthimbalance")
MODEL_VERSION = "phase17-fixed-bid-mark-family-v1"
FEATURE_VERSION = "prior20-causal-depth-bids-current-imbalance-v1"


def _at(value):
    at = datetime.fromisoformat(value) if isinstance(value, str) else value
    if not isinstance(at, datetime) or at.tzinfo is None:
        raise ValueError("aware_research_time_required")
    return at.astimezone(UTC)


def _number(value):
    return type(value) in (float, int) and isfinite(value)


def _sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    allow_nan=False).encode()).hexdigest()


def causal_forecasts(points, *, cutoff):
    """Reconstruct fixed forecasts using twenty strictly prior, available points.

    Inputs are Phase16 CausalHistory points. Independent raw-source verification
    belongs to the caller/evaluator; a forecast is not evidence that it happened
    prospectively. No labels, market outcomes or fitted coefficients are used.
    Invalid, duplicate-conflicting, future, stale or incomplete points are omitted.
    """
    cutoff = _at(cutoff)
    if not isinstance(points, (list, tuple)) or len(points) > 20000:
        raise ValueError("bounded_point_sequence_required")
    valid, identities, conflicts = [], {}, set()
    for raw in points:
        try:
            if not isinstance(raw, dict):
                continue
            if any(not isinstance(raw.get(k), str) or not 0 < len(raw[k]) <= 256
                   for k in ("id", "book_id", "token_id", "market_id", "event_id", "rules_sha256")):
                continue
            source, available, observed = (_at(raw[k]) for k in ("source_at", "available_at", "observed_at"))
            if not source <= available <= observed <= cutoff or (observed-source).total_seconds() > 15:
                continue
            bid, ask, imbalance = (raw.get(k) for k in ("bid_vwap", "ask_vwap", "imbalance"))
            if (not all(_number(v) for v in (bid, ask, imbalance)) or not 0 < bid < ask < 1
                or not -1 <= imbalance <= 1 or raw.get("execution_evidence_complete") is not True):
                continue
            fingerprint = _sha(raw)
            identity = (raw["token_id"], raw["book_id"])
            if identity in identities:
                if identities[identity] != fingerprint:
                    conflicts.add(identity)
                continue
            identities[identity] = fingerprint
            valid.append((observed, source, available, raw, fingerprint))
        except (TypeError, ValueError, OverflowError):
            continue
    valid = [r for r in valid if (r[3]["token_id"], r[3]["book_id"]) not in conflicts]
    valid.sort(key=lambda r: (r[0], r[3]["token_id"], r[3]["book_id"]))
    history, result = defaultdict(lambda: deque(maxlen=20)), []
    last_context = {}
    for observed, source, available, raw, fingerprint in valid:
        token = raw["token_id"]
        context = (raw["market_id"], raw["event_id"], raw["rules_sha256"])
        if last_context.get(token) != context:
            history[token].clear()
        last_context[token] = context
        prior = history[token]
        if prior and (source <= prior[-1][1] or observed <= prior[-1][0]):
            continue
        if prior and (source-prior[-1][1]).total_seconds() > 120:
            prior.clear()
        if len(prior) == 20:
            center = median(p[3]["bid_vwap"] for p in prior)
            bid = raw["bid_vwap"]
            predictions = {"unchanged": bid, "reversion20": center,
                           "momentum20": min(1., max(0., 2*bid-center)),
                           "depthimbalance": min(1., max(0., bid+.01*raw["imbalance"]))}
            feature_ids = [p[3]["id"] for p in prior]
            result.append({"point_id": raw["id"], "event_id": raw["event_id"], "token_id": token,
                           "market_id": raw["market_id"], "decision_at": observed.isoformat(),
                           "forecasts": predictions, "baseline": bid,
                           "model_version": MODEL_VERSION, "feature_version": FEATURE_VERSION,
                           "feature_point_ids": feature_ids,
                           "feature_cutoff": observed.isoformat(),
                           "latest_prior_source_at": prior[-1][1].isoformat(),
                           "provenance": {"decision_point_sha256": fingerprint,
                               "feature_points_sha256": _sha([p[4] for p in prior]),
                               "rules_sha256": raw["rules_sha256"],
                               "source_verification": "caller_raw_replay_required"},
                           "uncertainty": {"status": "uncalibrated_monetary_mark_hypotheses",
                                           "interval": None},
                           "semantics": "USD_per_share_bid_mark_not_event_probability",
                           "reconstructed": True, "research_only": True,
                           "trading_authority": False, "certification_authority": False})
        prior.append((observed, source, available, raw, fingerprint))
    return result
