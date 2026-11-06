"""Replay-qualified terminal-outcome calibration, separated from price-mark research.

The caller supplies an independent verifier of raw forecast, feature, market,
resolution and event-group evidence. No row can authenticate itself. This module
scores a frozen cohort; it cannot certify models or admit orders.
"""

import json
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from math import isfinite, log, sqrt

from neraium_poly.research.phase12.ledger import content_sha256

SEMANTICS = "binary_terminal_event_probability"
REQUIRED_EVENTS = 100


def _time(value):
    at = value if isinstance(value, datetime) else datetime.fromisoformat(value)
    if at.tzinfo is None or at.utcoffset() is None:
        raise ValueError("aware_time_required")
    return at.astimezone(UTC)


def _hash(value):
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def _probability(value):
    return type(value) in (float, int) and isfinite(value) and 0 <= value <= 1


def _loss(p, y):
    likelihood = p if y else 1 - p
    return -log(likelihood) if likelihood > 0 else None


def _mean_loss(rows, key):
    losses = [_loss(row[key], row["outcome"]) for row in rows]
    infinite = sum(v is None for v in losses)
    return {"value": None if infinite else sum(losses) / len(losses),
            "status": "positive_infinity" if infinite else "finite", "infinite_events": infinite}


def _metrics(rows):
    n = len(rows)
    deltas = [(r["probability"] - r["outcome"]) ** 2
              - (r["market_probability"] - r["outcome"]) ** 2 for r in rows]
    mean = sum(deltas) / n
    radius = sqrt(2 * log(40) / n)  # independent-group squared-loss differences in [-1,1]
    interval = [max(-1, mean - radius), min(1, mean + radius)]
    model_loss, market_loss = _mean_loss(rows, "probability"), _mean_loss(rows, "market_probability")
    bins = []
    for i in range(10):
        bucket = [r for r in rows if min(9, int(r["probability"] * 10)) == i]
        bins.append({"lower": i / 10, "upper": (i + 1) / 10, "count": len(bucket),
                     "mean_probability": sum(r["probability"] for r in bucket) / len(bucket) if bucket else None,
                     "observed_frequency": sum(r["outcome"] for r in bucket) / len(bucket) if bucket else None})
    return {"sample_unit": "one independently reviewed dependency group",
            "heldout_events": n,
            "brier": sum((r["probability"] - r["outcome"]) ** 2 for r in rows) / n,
            "market_brier": sum((r["market_probability"] - r["outcome"]) ** 2 for r in rows) / n,
            "paired_brier_difference": mean, "paired_brier_difference_95_bound": interval,
            "interval_method": "distribution-free Hoeffding bound; assumes independent reviewed groups",
            "model_log_loss": model_loss, "market_log_loss": market_loss,
            "reliability": bins,
            "forecasting_superiority_supported": interval[1] < 0,
            "trading_advantage": None}


def calibration_cohort(rows, *, cutoff, heldout_start, verify_raw=None, embargo_seconds=0):
    """Build a deterministic group-separated chronological calibration cohort.

    ``heldout_start`` is an externally fixed experiment boundary. Rows must bind
    terminal semantics, exact rule text/hash and matching verified outcome rules.
    Repeated forecasts collapse to the earliest eligible forecast per dependency
    group; a group spanning splits is quarantined completely. No current quote
    may replace an original contemporaneous market baseline.
    """
    cutoff, boundary = _time(cutoff), _time(heldout_start)
    if type(embargo_seconds) not in (float, int) or not isfinite(embargo_seconds) or not 0 <= embargo_seconds <= 86400:
        raise ValueError("bounded_embargo_required")
    if boundary > cutoff:
        raise ValueError("heldout_boundary_after_evaluation_cutoff")
    rejected, grouped, raw_hashes = Counter(), defaultdict(list), []
    total_bytes = 0
    for index, raw in enumerate(rows):
        if index >= 10000:
            raise ValueError("bounded_calibration_cohort_required")
        if not isinstance(raw, dict):
            raise TypeError("canonical_json_calibration_rows_required")
        encoded = json.dumps(raw, sort_keys=True, separators=(",", ":"), allow_nan=True).encode()
        total_bytes += len(encoded)
        if len(encoded) > 256 * 1024 or total_bytes > 32 * 1024**2:
            raise ValueError("bounded_calibration_byte_budget_required")
        raw_hashes.append(sha256(encoded).hexdigest())
        try:
            if raw.get("probability_semantics") != SEMANTICS or raw.get("uses_market_features") is not False:
                raise ValueError("independent_terminal_semantics_required")
            if raw.get("independence_reviewed") is not True:
                raise ValueError("independent_group_review_required")
            rules = raw["resolution_rules"]
            if not isinstance(rules, str) or not rules or sha256(rules.encode()).hexdigest() != raw["resolution_rules_sha256"]:
                raise ValueError("original_resolution_rules_hash_mismatch")
            if raw["outcome_rules_sha256"] != raw["resolution_rules_sha256"]:
                raise ValueError("outcome_resolution_rules_mismatch")
            if not all(_hash(raw[k]) for k in ("forecast_sha256", "model_sha256", "dataset_sha256", "outcome_proof_sha256")):
                raise ValueError("source_hashes_required")
            identity = tuple(raw[k] for k in ("forecast_id", "event_id", "market_id", "token_id", "dependency_group"))
            if any(not isinstance(v, str) or not v or len(v) > 256 for v in identity):
                raise ValueError("complete_event_identity_required")
            binding = tuple(raw[k] for k in ("domain", "model_version", "feature_version", "contract_type"))
            if any(not isinstance(v, str) or not v or len(v) > 256 for v in binding):
                raise ValueError("model_feature_contract_binding_required")
            times = {k: _time(raw[k]) for k in ("forecast_at", "recorded_at", "evidence_cutoff", "evidence_available_at",
                "model_training_cutoff", "market_at", "market_available_at", "outcome_at", "outcome_available_at")}
            if not (times["evidence_available_at"] <= times["evidence_cutoff"] <= times["forecast_at"]
                <= times["recorded_at"] <= times["forecast_at"] + timedelta(seconds=30)
                and times["model_training_cutoff"] <= times["evidence_cutoff"]
                and times["forecast_at"] < times["outcome_at"] <= times["outcome_available_at"] <= cutoff):
                raise ValueError("future_or_nonprospective_evidence")
            if not (times["market_at"] <= times["market_available_at"] <= times["forecast_at"]
                    and (times["forecast_at"] - times["market_at"]).total_seconds() <= 60):
                raise ValueError("contemporaneous_baseline_required")
            if not all(_probability(raw[k]) for k in ("probability", "market_probability")) or type(raw["outcome"]) is not int or raw["outcome"] not in (0, 1):
                raise ValueError("binary_scoring_values_required")
            split = raw["split"]
            if split not in ("train", "heldout"):
                raise ValueError("explicit_split_required")
            if (split == "train" and not times["forecast_at"] < boundary) or (split == "heldout" and times["forecast_at"] < boundary):
                raise ValueError("forecast_outside_declared_split")
            if not callable(verify_raw):
                rejected["independent_raw_replay_required"] += 1
                continue
            try:
                verified = verify_raw(raw)
            except Exception as error:  # Missing/corrupt evidence withholds scoring.
                raise ValueError("independent_raw_replay_failed") from error
            if verified is not True:
                raise ValueError("independent_raw_replay_required")
            grouped[raw["dependency_group"]].append({**raw, **times, "binding": binding})
        except (KeyError, TypeError, ValueError, OverflowError) as error:
            reason = str(error) if isinstance(error, ValueError) and len(str(error)) < 100 else "malformed_calibration_record"
            rejected[reason] += 1
    accepted, conflicts = [], 0
    for group in sorted(grouped):
        members = grouped[group]
        if len({r["split"] for r in members}) != 1:
            rejected["cross_split_dependency_group"] += len(members)
            conflicts += 1
            continue
        members.sort(key=lambda r: (r["forecast_at"], r["recorded_at"], r["forecast_id"]))
        accepted.append(members[0])
        if len(members) > 1:
            rejected["repeated_dependency_group"] += len(members) - 1
    train = [r for r in accepted if r["split"] == "train"]
    heldout = [r for r in accepted if r["split"] == "heldout"]
    blockers = []
    if len({r["binding"] for r in accepted}) > 1:
        blockers.append("mixed_model_or_contract_cohort")
    if conflicts:
        blockers.append("cross_split_dependency_groups")
    if any(r["outcome_available_at"] + timedelta(seconds=embargo_seconds) >= boundary for r in train):
        blockers.append("training_labels_cross_heldout_boundary")
    if train and heldout and max(r["outcome_available_at"] for r in train) > min(r["model_training_cutoff"] for r in heldout):
        blockers.append("heldout_model_training_cutoff_precedes_training_labels")
    if len(train) < REQUIRED_EVENTS:
        blockers.append("fewer_than_100_independent_training_events")
    if len(heldout) < REQUIRED_EVENTS:
        blockers.append("fewer_than_100_independent_heldout_events")
    return {"schema_version": "phase16-calibration-v1", "evaluated_at": cutoff.isoformat(),
            "dataset_sha256": content_sha256(sorted(raw_hashes)),
            "heldout_start": boundary.isoformat(), "embargo_seconds": embargo_seconds,
            "training_events": len(train), "heldout_events": len(heldout),
            "required_training_events": REQUIRED_EVENTS, "required_heldout_events": REQUIRED_EVENTS,
            "rejections": dict(rejected), "blockers": blockers,
            "metrics": _metrics(heldout) if not blockers else None,
            "cohort_sufficient": not blockers, "calibration_status": "research_cohort_scored" if not blockers else "insufficient_evidence",
            "accepted_forecast_ids": [r["forecast_id"] for r in sorted(accepted, key=lambda r: (r["forecast_at"], r["forecast_id"]))],
            "sample_unit": "independently reviewed parent-event dependency group; not quote snapshots",
            "research_only": True, "experimental_admission_authority": False,
            "certification_authority": False, "execution_cost_adjusted_performance": None}
