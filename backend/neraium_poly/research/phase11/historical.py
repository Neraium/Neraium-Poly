"""Immutable historical evidence audit; insufficient context never becomes certification."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from neraium_poly.research.qualification import _load_proofs
from neraium_poly.research.settlement_evidence import READ_METHODS


def audit_historical(dataset_dir, *, chain_dir=None, acquisition_dirs=()):
    root = Path(dataset_dir)
    manifest_raw = (root / "manifest.json").read_bytes()
    manifest = json.loads(manifest_raw)
    event_raw = (root / "events.jsonl").read_bytes()
    digest = hashlib.sha256(event_raw).hexdigest()
    if (
        len(event_raw) > 32 * 1024**2
        or digest != manifest["events_sha256"]
        or len(event_raw) != manifest["events_bytes"]
    ):
        raise ValueError("historical dataset integrity mismatch")
    report = json.loads((root / "report.json").read_text())
    if report["manifest_sha256"] != hashlib.sha256(manifest_raw).hexdigest():
        raise ValueError("historical report manifest mismatch")
    if (report.get("required_training_events"), report.get("required_heldout_events")) != (100, 100):
        raise ValueError("certification requirements differ")
    events = [json.loads(line) for line in event_raw.splitlines() if line]
    if len(events) > 10000 or len({r["event_id"] for r in events}) != len(events):
        raise ValueError("ambiguous or oversized historical event groups")
    proofs, proof_hash = _load_proofs(chain_dir)
    deficiencies = Counter()
    corroborated, api_verified = 0, 0
    rows = []
    for row in events:
        proof = proofs.get(row["condition_id"].lower())
        linked = bool(
            proof
            and row.get("chain_payout_matches_selected_outcome")
            and row.get("settlement_at") == proof["settlement_at"]
        )
        corroborated += linked
        api_verified += bool(row.get("official_source_outcome_verified"))
        reasons = list(row.get("deficiencies", []))
        if row.get("availability_basis") != "point_in_time_verified":
            reasons.append("historical_availability_not_certified")
        if not row.get("dependency_group_reviewed"):
            reasons.append("independent_event_group_not_reviewed")
        if not row.get("historical_depth_qualified"):
            reasons.append("historical_executable_depth_not_qualified")
        if not row.get("historical_rules_verified"):
            reasons.append("historical_rule_version_not_verified")
        if not linked:
            reasons.append("exact_finalized_resolution_timing_not_corroborated")
        deficiencies.update(set(reasons))
        rows.append(
            {
                "event_id": row["event_id"],
                "condition_id": row["condition_id"],
                "api_outcome_verified": bool(row.get("official_source_outcome_verified")),
                "chain_corroborated": linked,
                "settlement_at": proof["settlement_at"] if linked else None,
                "settlement_available_at": proof["available_at"] if linked else None,
                "historical_available_at": row.get("source_available_at"),
                "certification_eligible": False,
                "deficiencies": sorted(set(reasons)),
            }
        )
    acquisitions = []
    for directory in acquisition_dirs:
        directory = Path(directory)
        raw = (directory / "manifest.json").read_bytes()
        acquisition = json.loads(raw)
        for record in acquisition.get("responses", []):
            path = (directory / record["response_path"]).resolve()
            if not path.is_relative_to(directory.resolve()):
                raise ValueError("acquisition path escapes archive")
            payload = path.read_bytes()
            if record.get("request", {}).get("method") not in READ_METHODS:
                raise ValueError("non-read-only historical acquisition method")
            response = json.loads(payload)
            if response.get("jsonrpc") != "2.0" or response.get("id") != record["request"]["id"]:
                raise ValueError("historical request/response binding mismatch")
            if (
                len(payload) != record["bytes"]
                or hashlib.sha256(payload).hexdigest() != record["response_sha256"]
            ):
                raise ValueError("historical acquisition checksum mismatch")
        acquisitions.append(
            {
                "path": str(directory),
                "manifest_sha256": hashlib.sha256(raw).hexdigest(),
                "responses": len(acquisition.get("responses", [])),
            }
        )
    return {
        "schema_version": "1.0",
        "experiment_id": "phase11-historical-requalification-audit-v1",
        "created_at": datetime.now(UTC).isoformat(),
        "dataset_sha256": digest,
        "source_manifest_sha256": hashlib.sha256(manifest_raw).hexdigest(),
        "chain_proofs_sha256": proof_hash,
        "events": len(events),
        "official_verified_outcome_groups": api_verified,
        "chain_corroborated_exact_settlement_groups": corroborated,
        "certifiable_training_events": 0,
        "certifiable_heldout_events": 0,
        "required_training_events": 100,
        "required_heldout_events": 100,
        "chronological_split_status": "blocked: no independently qualified point-in-time training/heldout set",
        "deficiency_counts": dict(deficiencies),
        "event_audits": rows,
        "acquisitions": acquisitions,
        "certification_status": "blocked",
        "owner_approval_required": True,
        "strategy_promotion_authority": False,
        "certification_authority": False,
        "automatic_promotion": False,
        "limitations": [
            "Qualification audit cannot promote datasets or strategies",
            "No current source/label availability is backdated",
            "Exact settlement is only one of multiple required evidence gates",
            "Unreviewed grouping and price observations do not count as independent training events",
        ],
    }
