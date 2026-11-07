"""Strict parent-event separation over the existing verified calibration contract."""

import json
from collections import Counter, defaultdict
from datetime import UTC, datetime

from neraium_poly.research.phase16.calibration import calibration_cohort


def _at(value):
    at = value if isinstance(value, datetime) else datetime.fromisoformat(value)
    if at.tzinfo is None or at.utcoffset() is None:
        raise ValueError("aware event validation timestamp required")
    return at.astimezone(UTC)


def event_disjoint_validation(rows, *, training_end, heldout_start, cutoff, verify_row=None):
    """Only independently replayed terminal outcomes can enter calibration.

    Parent aliases cannot inflate counts through multiple tokens/dependency IDs.
    Parents seen in validation or training never become held-out events. Group
    review and outcome/native-proof replay remain the caller's responsibility;
    URLs, hashes or booleans alone cannot authenticate a record.
    """
    training_end, heldout_start, cutoff = map(_at, (training_end, heldout_start, cutoff))
    if not training_end < heldout_start <= cutoff:
        raise ValueError("ordered predeclared event split boundaries required")
    if not isinstance(rows, (list, tuple)) or len(rows) > 10000:
        raise ValueError("bounded event validation rows required")
    total_bytes = 0
    for row in rows:
        encoded = json.dumps(row, sort_keys=True, allow_nan=False).encode()
        total_bytes += len(encoded)
        if len(encoded) > 256*1024 or total_bytes > 32*1024**2:
            raise ValueError("bounded event validation bytes required")
    accepted, rejected, parent_groups, group_partitions = [], Counter(), defaultdict(set), defaultdict(set)
    for row in rows:
        try:
            if not callable(verify_row) or verify_row(row) is not True:
                raise ValueError("independent_forecast_outcome_replay_required")
            parent, group = row["event_id"], row["dependency_group"]
            if any(not isinstance(v, str) or not 1 <= len(v) <= 256 for v in (parent, group)):
                raise ValueError("parent_and_dependency_identity_required")
            at = _at(row["forecast_at"])
            if at > cutoff:
                raise ValueError("future_forecast_not_evaluable")
            partition = "training" if at <= training_end else "validation" if at < heldout_start else "heldout"
            parent_groups[parent].add(group)
            group_partitions[group].add(partition)
            accepted.append((row, partition))
        except (KeyError, TypeError, ValueError) as exc:
            rejected[str(exc)[:120]] += 1
        except Exception:  # noqa: BLE001 - source-verifier faults cannot qualify outcomes
            rejected["source_replay_failed"] += 1
    ambiguous = {parent for parent, groups in parent_groups.items() if len(groups) != 1}
    overlapping = {group for group, partitions in group_partitions.items()
                   if "heldout" in partitions and len(partitions) > 1}
    by_model = defaultdict(list)
    validation_only = training_labels_late = 0
    for row, partition in accepted:
        if row["event_id"] in ambiguous:
            rejected["same_parent_has_inconsistent_dependency_groups"] += 1
            continue
        if row["dependency_group"] in overlapping:
            rejected["parent_dependency_seen_before_heldout"] += 1
            continue
        if partition == "validation":
            validation_only += 1
            continue
        try:
            if partition == "training" and _at(row["outcome_available_at"]) > training_end:
                training_labels_late += 1
                rejected["training_outcome_unavailable_at_training_cutoff"] += 1
                continue
            if partition == "heldout" and _at(row["model_training_cutoff"]) >= heldout_start:
                rejected["heldout_model_not_frozen_before_evaluation"] += 1
                continue
            key = tuple(row[k] for k in ("domain", "model_version", "model_sha256", "feature_version", "contract_type"))
            if any(not isinstance(v, str) or not v for v in key):
                raise ValueError("complete_model_identity_required")
            by_model[key].append(row)
        except (KeyError, ValueError, TypeError):
            rejected["incomplete_model_or_outcome_binding"] += 1
    reports = []
    for key, cohort in sorted(by_model.items()):
        verified_ids = {id(r) for r in cohort}
        report = calibration_cohort(cohort, cutoff=cutoff, heldout_start=heldout_start,
                                    verify_raw=lambda r, ids=verified_ids: id(r) in ids and verify_row(r) is True)
        reports.append({"domain": key[0], "model_version": key[1], "model_sha256": key[2],
                        "feature_version": key[3], "contract_type": key[4], "calibration": report})
    return {"schema_version": "phase18-event-disjoint-v1", "evaluated_at": cutoff.isoformat(),
        "training_end": training_end.isoformat(), "heldout_start": heldout_start.isoformat(),
        "input_rows": len(rows), "raw_replayed_rows": len(accepted), "cohorts": reports,
        "ambiguous_parent_ids": sorted(ambiguous), "cross_split_groups": sorted(overlapping),
        "validation_only_rows": validation_only, "training_labels_late": training_labels_late,
        "rejections": dict(rejected), "required_training_events": 100, "required_heldout_events": 100,
        "metrics": None, "score_scope": "per homogeneous verified model cohort only",
        "certification_authority": False, "trading_authority": False,
        "limitations": ["Independent features, independent source lineages and independent event groups are different requirements",
                        "No monetary mark or terminal quote can substitute for a verified settlement outcome",
                        "Multiple models sharing one parent do not create additional independent events"]}
