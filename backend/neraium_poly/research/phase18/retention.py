"""Policy-bound dry-run/audit manifests. There is deliberately no deletion API."""

import hashlib
import json
import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from neraium_poly.data.cold import process_references
from neraium_poly.research.phase17.provenance import ReadonlyArchive

POLICY_VERSION = "phase18-proposed-verified-redundant-original-v1"


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(1024**2), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _metadata(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 32768:
        raise ValueError("bounded regular immutable proof required")
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise TypeError("proof mapping required")
    return value


def proposed_policy(*, minimum_warm_seconds=86400):
    if type(minimum_warm_seconds) is not int or not 86400 <= minimum_warm_seconds <= 366*86400:
        raise ValueError("explicit proposed minimum warm interval at least24hours required")
    return {"version": POLICY_VERSION, "retention_class": "proposed_raw_after_verified_cold",
            "minimum_warm_seconds": minimum_warm_seconds,
            "protected": ["active databases/WAL", "legacy evidence", "account records", "forecast journals",
                          "settlements", "provenance manifests", "catalog indexes", "audit trails"],
            "required": ["sealed original", "unchanged raw/hash/manifest", "lossless gzip copy",
                         "independent restore verified", "record completeness verified", "warm interval passed",
                         "complete active-process reference scan", "no open references",
                         "separate explicit owner approval of exact proposal hash and named originals"],
            "irreversible_actions_enabled": False, "owner_approval_required": True,
            "change_to_existing_retain_all_policy": "proposal only; existing policy remains effective"}


def _verify_cold_completeness(directory, row, proof):
    catalog = sqlite3.connect((Path(directory)/"events-archive.sqlite").as_uri()+"?mode=ro", uri=True, timeout=3)
    try:
        catalog.execute("PRAGMA query_only=ON")
        catalog.execute("PRAGMA cache_size=-2048")
        # Stop malformed indexes or unexpected enormous scans rather than
        # holding production metadata readers indefinitely.
        steps = [0]
        def progress():
            steps[0] += 1
            return steps[0] > 20000
        catalog.set_progress_handler(progress, 1000)
        count, identity = 0, hashlib.sha256()
        for record in catalog.execute("SELECT * FROM records WHERE segment=? ORDER BY id LIMIT 100001", (row["name"],)):
            count += 1
            if count > 100000:
                raise ValueError("retention record completeness budget exceeded")
            identity.update((json.dumps(list(record), sort_keys=True, separators=(",", ":"), allow_nan=False)+"\n").encode())
        if count != row["records"] or count != proof["catalog_match_count"] or identity.hexdigest() != proof["catalog_records_sha256"]:
            raise ValueError("cold restore completeness proof no longer matches catalog")
    finally:
        catalog.close()


def retention_plan(directory, *, now, mode="dry_run", policy=None, max_segments=512,
                   max_verified_segments=8, max_verification_bytes=64*1024**2, after_segment=None):
    """Produce a hash-bound review proposal, never authorize removal.

    Dry-run catalogs are bounded metadata only and cannot mark a segment ready.
    Audit independently verifies existing gzip restoration byte-for-byte, original
    SQLite integrity and the earlier successful restored-SQLite/catalog proof.
    Active references and inaccessible procfs namespaces fail closed. No proof,
    cache, source, database, manifest or retention configuration is written here.
    """
    if mode not in ("dry_run", "audit"):
        raise ValueError("only non-destructive dry_run/audit modes exist")
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("aware retention cutoff required")
    now = now.astimezone(UTC)
    policy = proposed_policy() if policy is None else policy
    if policy != proposed_policy(minimum_warm_seconds=policy.get("minimum_warm_seconds")):
        raise ValueError("explicit unchanged non-destructive proposal policy required")
    if (type(max_segments) is not int or not 1 <= max_segments <= 2048
        or type(max_verified_segments) is not int or not 1 <= max_verified_segments <= 32
        or type(max_verification_bytes) is not int or not 4096 <= max_verification_bytes <= 512*1024**2):
        raise ValueError("bounded retention inventory/verification required")
    if after_segment is not None and (not isinstance(after_segment, str) or not re.fullmatch(r"(?:legacy|segment-[0-9]{8}\.sqlite)", after_segment)):
        raise ValueError("bounded valid segment continuation cursor required")
    directory = Path(directory).absolute()
    results, verified, verified_bytes = [], 0, 0
    with ReadonlyArchive(directory) as archive:
        rows = archive._catalog_rows("SELECT * FROM segments WHERE name>? ORDER BY name LIMIT ?", (after_segment or "", max_segments+1))
        truncated = len(rows) > max_segments
        for stored in rows[:max_segments]:
            row = dict(stored)
            entry = {"segment": row["name"], "catalog_status": row["status"], "retention_class": "PROTECTED",
                     "raw_sha256": row["raw_sha"], "gzip_sha256": row["gzip_sha"],
                     "raw_bytes": row["raw_size"], "records": row["records"], "reasons": [],
                     "review_prerequisites_met": False, "removal_authorized": False}
            results.append(entry)
            if row["name"] == "legacy" or row["status"] != "sealed":
                entry["reasons"].append("legacy_or_active_original_protected")
                continue
            try:
                raw = archive._source_path(row["name"])
                compressed, manifest_path = Path(str(raw)+".gz"), Path(str(raw)+".manifest.json")
                proof_path = Path(str(raw)+".cold-proof.json")
                paths = (raw, compressed, manifest_path, proof_path)
                if any(p.is_symlink() or not p.is_file() for p in paths):
                    raise ValueError("completed original/gzip/manifest/restore proof required")
                if any(Path(str(raw)+s).exists() and Path(str(raw)+s).stat().st_size for s in ("-wal", "-journal")):
                    raise ValueError("open_or_uncheckpointed_SQLite_original_protected")
                stat = raw.stat()
                completed_bound = max(p.stat().st_mtime for p in paths)
                if completed_bound > now.timestamp():
                    raise ValueError("future archive completion metadata")
                age = now.timestamp()-completed_bound
                entry.update(retention_class="WARM_ORIGINAL_RETAINED", raw_path=str(raw), gzip_path=str(compressed),
                    manifest_path=str(manifest_path), cold_proof_path=str(proof_path),
                    raw_device=stat.st_dev, raw_inode=stat.st_ino, raw_links=stat.st_nlink,
                    completed_time_bound=datetime.fromtimestamp(completed_bound, UTC).isoformat(),
                    age_seconds=age, age_basis="max(original,gzip,manifest,restore-proof filesystem mtimes)",
                    eligible_at=datetime.fromtimestamp(completed_bound+policy["minimum_warm_seconds"], UTC).isoformat())
                if age < policy["minimum_warm_seconds"]:
                    entry["reasons"].append("minimum_warm_retention_not_reached")
                    continue
                entry["retention_class"] = "PROPOSED_REDUNDANT_ORIGINAL_RETAINED"
                if mode == "dry_run":
                    entry["reasons"].append("independent_audit_required_before_review")
                    continue
                if verified >= max_verified_segments or verified_bytes+stat.st_size > max_verification_bytes:
                    entry["reasons"].append("bounded_independent_verification_budget_reached")
                    continue
                verified += 1
                verified_bytes += stat.st_size
                fresh = archive.verify_segment(row["name"], max_raw_bytes=max_verification_bytes)
                proof = _metadata(proof_path)
                if (not fresh["gzip_roundtrip_verified"] or fresh["raw_sha256"] != row["raw_sha"]
                    or fresh["gzip_sha256"] != row["gzip_sha"]
                    or proof.get("schema_version") != "phase15-cold-proof-v1"
                    or proof.get("segment") != row["name"] or proof.get("raw_sha256") != row["raw_sha"]
                    or proof.get("gzip_sha256") != row["gzip_sha"] or proof.get("raw_bytes") != row["raw_size"]
                    or proof.get("gzip_bytes") != row["gzip_size"] or proof.get("records") != row["records"]
                    or proof.get("sqlite_quick_check") != "ok" or proof.get("recovery_tested") is not True
                    or proof.get("original_modified") is not False or proof.get("approval_required") is not True
                    or proof.get("removal_authorized") is not False
                    or proof.get("manifest_sha256") != _sha(manifest_path)):
                    raise ValueError("trusted successful cold restoration proof required")
                _verify_cold_completeness(directory, row, proof)
                after = raw.stat()
                if (stat.st_ino, stat.st_dev, stat.st_size, stat.st_mtime_ns) != (
                    after.st_ino, after.st_dev, after.st_size, after.st_mtime_ns):
                    raise ValueError("immutable original changed during audit")
                entry.update(independent_verification=fresh, raw_sha256=_sha(raw), gzip_sha256=_sha(compressed),
                    manifest_sha256=_sha(manifest_path), cold_proof_sha256=_digest(proof),
                    catalog_records_sha256=proof["catalog_records_sha256"], restore_verified=True)
            except (OSError, ValueError, KeyError, TypeError, sqlite3.Error) as exc:
                entry["reasons"].append("audit_withheld:"+str(exc)[:160])
        candidates = [r for r in results if r.get("restore_verified") and not r["reasons"]]
        references = process_references([r["raw_path"] for r in candidates]) if candidates else {
            "scope": "no age/audit-qualified original candidates", "complete": True, "references": []}
        referenced = {r["path"] for r in references["references"]}
        for entry in candidates:
            if not references["complete"]:
                entry["reasons"].append("complete_privileged_process_reference_audit_required")
            if entry["raw_path"] in referenced:
                entry["reasons"].append("original_referenced_by_active_process")
            entry["review_prerequisites_met"] = not entry["reasons"]
    ready = [r for r in results if r["review_prerequisites_met"]]
    value = {"schema_version": "phase18-retention-audit-v1", "mode": mode, "observed_at": now.isoformat(),
        "directory": str(directory), "policy": policy, "segments": results,
        "inventory_truncated": truncated, "after_segment": after_segment,
        "next_cursor": results[-1]["segment"] if truncated and results else None,
        "independently_verified_segments": verified,
        "verification_bytes": verified_bytes, "review_ready_segments": len(ready),
        "raw_bytes_proposed_for_separate_review": sum(r["raw_bytes"] for r in ready),
        "process_reference_audit": references, "owner_approval_required": True,
        "removal_authorized": False, "original_removal_implemented": False,
        "existing_retention_policy_changed": False,
        "required_owner_action": "Review exact proposal hash, named originals and current proofs; separately authorize any irreversible action after revalidation"}
    value["proposal_sha256"] = _digest(value)
    return value
