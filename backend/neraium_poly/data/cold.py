"""Verified cold representations and bounded recovery; no original-removal API.

A cold proof is evidence, not retention authorization. Source paths are immutable;
only derived cache/publication temporaries are ever evicted by this module.
"""

import fcntl
import gzip
import hashlib
import json
import os
import shutil
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

from neraium_poly.data.segmented import CHUNK, NAME, _sha, _sync_dir

PROOF_VERSION = "phase15-cold-proof-v1"
CACHE_PURPOSE = "regenerable_verified_cold_cache"
RETENTION_CLASSES = {"retain_original", "proposed_raw_after_verified_cold"}


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _digest(value):
    return hashlib.sha256(_canonical(value).encode()).hexdigest()


def _time(value):
    value = value if isinstance(value, datetime) else datetime.fromisoformat(value)
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("aware UTC retention time required")
    return value.astimezone(UTC)


def _regular(path, *, required=True):
    path = Path(path).absolute()
    if path.is_symlink() or any(p.is_symlink() for p in path.parents):
        raise ValueError("symlinked cold archive path")
    if required and not path.is_file():
        raise ValueError("cold archive file missing")
    return path.resolve()


def _bounded_json(path):
    path = _regular(path)
    if path.stat().st_size > 32768:
        raise ValueError("cold metadata exceeds bound")
    return json.loads(path.read_text())


def _publish(path, value):
    """Publish once without replacing a completed proof, even after interruption."""
    payload = _canonical(value) + "\n"
    if path.exists():
        if _bounded_json(path) != value:
            raise ValueError("immutable cold proof changed")
        return
    pending = Path(str(path) + ".pending")
    if pending.exists():
        _regular(pending)
        pending.unlink()  # Owned regenerable publication, never an original.
    with pending.open("x") as f:
        f.write(payload)
        f.flush()
        os.fsync(f.fileno())
    os.link(pending, path)
    _sync_dir(path.parent)
    pending.unlink()
    _sync_dir(path.parent)


def _trusted(raw_path, row):
    raw = _regular(raw_path, required=False)
    row = dict(row)
    if row.get("status") != "sealed" or row.get("name") != raw.name or not NAME.fullmatch(raw.name):
        raise ValueError("only explicitly sealed managed segments support cold recovery")
    for field in ("raw_sha", "gzip_sha"):
        value = row.get(field)
        if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
            raise ValueError("trusted completed raw and gzip hashes required")
    for field in ("raw_size", "gzip_size", "records"):
        if type(row.get(field)) is not int or row[field] < (0 if field == "records" else 1):
            raise ValueError("trusted cold sizes and record count required")
    manifest_path = Path(str(raw) + ".manifest.json")
    manifest = _bounded_json(manifest_path)
    expected = {"schema_version": "1.0", "segment": raw.name, "raw_sha256": row["raw_sha"],
                "raw_bytes": row["raw_size"], "records": row["records"], "retention_policy": "retain_original"}
    if manifest != expected:
        raise ValueError("cold manifest does not match trusted archive catalog")
    compressed = _regular(str(raw) + ".gz")
    if compressed.stat().st_size != row["gzip_size"] or _sha(compressed) != row["gzip_sha"]:
        raise ValueError("cold compressed copy hash/length mismatch")
    if raw.exists():
        wal = Path(str(raw) + "-wal")
        if wal.exists() and wal.stat().st_size:
            raise ValueError("cannot verify active SQLite source as cold")
        if raw.stat().st_size != row["raw_size"] or _sha(raw) != row["raw_sha"]:
            raise ValueError("cold original hash/length mismatch")
    return raw, compressed, manifest_path, row


class ColdSegmentReader:
    """Recover exact SQLite bytes in a private bounded derived cache.

    Cooperative readers pin each cached inode with a shared flock. Eviction uses
    an exclusive nonblocking flock and requires its still-valid compressed source.
    Cache paths are an implementation detail, never historical source paths.
    """

    def __init__(self, cache_directory, *, min_free_bytes=8 * 1024**3, max_cache_bytes=64 * 1024**2):
        if type(min_free_bytes) is not int or min_free_bytes < 0 or type(max_cache_bytes) is not int or max_cache_bytes < 65536:
            raise ValueError("bounded cold cache configuration required")
        self.directory = _regular(cache_directory, required=False)
        if self.directory.exists() and not self.directory.is_dir():
            raise ValueError("cold cache requires a separate directory")
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.min_free_bytes, self.max_cache_bytes = min_free_bytes, max_cache_bytes
        self.owner = _regular(self.directory / ".cache.lock", required=False)

    @contextmanager
    def _lock(self):
        with self.owner.open("a+b") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)

    def _usage(self):
        total = 0
        for p in self.directory.iterdir():
            _regular(p)
            total += p.stat().st_size
        return total

    def _evict(self, extra):
        if extra > self.max_cache_bytes:
            raise ValueError("cold segment exceeds bounded cache")
        for path in sorted(self.directory.glob("*.sqlite"), key=lambda p: (p.stat().st_mtime_ns, p.name)):
            if self._usage() + extra <= self.max_cache_bytes:
                break
            marker = Path(str(path) + ".derived.json")
            value = _bounded_json(marker)
            if value.get("purpose") != CACHE_PURPOSE or value.get("raw_sha256") != _sha(path):
                raise ValueError("unknown or corrupt derived cache cannot be evicted")
            source = _regular(value["source_gzip"])
            if _sha(source) != value["gzip_sha256"]:
                raise ValueError("derived cache has no verified surviving source")
            with path.open("rb") as pin:
                try:
                    fcntl.flock(pin.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    continue
                path.unlink()
                marker.unlink()
                _sync_dir(self.directory)
        if self._usage() + extra > self.max_cache_bytes:
            raise ValueError("cold cache exhausted or readers pinned")
        if shutil.disk_usage(self.directory).free < self.min_free_bytes + extra:
            raise ValueError("cold cache filesystem safety floor reached")

    def _restore(self, compressed, row):
        path = self.directory / (row["raw_sha"] + ".sqlite")
        marker = Path(str(path) + ".derived.json")
        pending = Path(str(path) + ".pending")
        if path.exists():
            _regular(path)
            value = _bounded_json(marker)
            if (value.get("purpose") != CACHE_PURPOSE or value.get("raw_sha256") != row["raw_sha"]
                or value.get("source_gzip") != str(compressed) or value.get("gzip_sha256") != row["gzip_sha"]):
                raise ValueError("derived cache metadata mismatch")
            if path.stat().st_size != row["raw_size"] or _sha(path) != row["raw_sha"]:
                raise ValueError("corrupt derived cold cache")
            if pending.exists():
                _regular(pending)
                if _sha(pending) != row["raw_sha"]:
                    raise ValueError("unknown pending cache beside completed recovery")
                pending.unlink()
                _sync_dir(self.directory)
            return path
        if pending.exists():
            _regular(pending)
            pending.unlink()  # Revalidated compressed source can recreate this incomplete copy.
        if marker.exists():
            value = _bounded_json(marker)
            if (value.get("purpose") != CACHE_PURPOSE or value.get("raw_sha256") != row["raw_sha"]
                or value.get("source_gzip") != str(compressed) or value.get("gzip_sha256") != row["gzip_sha"]):
                raise ValueError("unknown orphan derived marker")
            marker.unlink()
        self._evict(row["raw_size"] + 32768)
        digest, size = hashlib.sha256(), 0
        with gzip.open(compressed, "rb") as source, pending.open("xb") as target:
            for block in iter(lambda: source.read(CHUNK), b""):
                size += len(block)
                if size > row["raw_size"] or self._usage() > self.max_cache_bytes:
                    raise ValueError("decompressed cold segment exceeds trusted bound")
                if shutil.disk_usage(self.directory).free < self.min_free_bytes + len(block):
                    raise ValueError("cold cache filesystem safety floor reached")
                digest.update(block)
                target.write(block)
            target.flush()
            os.fsync(target.fileno())
        if size != row["raw_size"] or digest.hexdigest() != row["raw_sha"]:
            raise ValueError("cold recovery roundtrip failed")
        derived = {"schema_version": "1.0", "purpose": CACHE_PURPOSE, "raw_sha256": row["raw_sha"],
                   "source_gzip": str(compressed), "gzip_sha256": row["gzip_sha"]}
        _publish(marker, derived)
        os.link(pending, path)
        _sync_dir(self.directory)
        pending.unlink()
        _sync_dir(self.directory)
        return path

    @contextmanager
    def open(self, raw_path, *, catalog_row):
        raw, compressed, _manifest, row = _trusted(raw_path, catalog_row)
        if self.directory == raw.parent or self.directory == raw:
            raise ValueError("derived cache must be separate from original segment directory")
        with self._lock():
            path = self._restore(compressed, row)
            pin = path.open("rb")
            fcntl.flock(pin.fileno(), fcntl.LOCK_SH)
        connection = None
        try:
            # This is a verified immutable DERIVED file, never the active source.
            connection = sqlite3.connect(f"file:{path.resolve()}?mode=ro&immutable=1", uri=True)
            connection.execute("PRAGMA query_only=ON")
            yield connection
        finally:
            if connection is not None:
                connection.close()
            fcntl.flock(pin.fileno(), fcntl.LOCK_UN)
            pin.close()

    def verify_metadata(self, raw_path, *, catalog_row, verify_records=True):
        raw, _compressed, manifest, row = _trusted(raw_path, catalog_row)
        if not verify_records:
            raise ValueError("cold completeness verification cannot be skipped")
        catalog_path = _regular(raw.parent.parent / "events-archive.sqlite")
        catalog = sqlite3.connect(f"file:{catalog_path.resolve()}?mode=ro", uri=True)
        identity, count = hashlib.sha256(), 0
        try:
            catalog.execute("PRAGMA cache_size=-32768")
            catalog.execute("BEGIN")
            expected_count = catalog.execute("SELECT count(*) FROM records WHERE segment=?", (raw.name,)).fetchone()[0]
            with self.open(raw, catalog_row=row) as restored:
                if restored.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
                    raise ValueError("cold restored SQLite integrity failed")
                for rid, kind, available, event, payload, digest in restored.execute(
                    "SELECT id,kind,available_at,event_time,payload,digest FROM events ORDER BY id"
                ):
                    parsed = json.loads(payload)
                    if (hashlib.sha256(payload.encode()).hexdigest() != digest or parsed.get("id") != rid
                        or _time(parsed["available_at"]) != _time(available) or _time(parsed["timestamp"]) != _time(event)):
                        raise ValueError("cold restored record identity/digest mismatch")
                    qualified = int(parsed["qualified"]) if type(parsed.get("qualified")) is bool else -1
                    expected = (rid, kind, available, event, digest, raw.name, qualified)
                    actual = catalog.execute("SELECT * FROM records WHERE id=?", (rid,)).fetchone()
                    if actual != expected:
                        raise ValueError("cold recovery record differs from global catalog")
                    identity.update((_canonical(list(expected)) + "\n").encode())
                    count += 1
            if count != row["records"] or count != expected_count:
                raise ValueError("cold recovery record completeness mismatch")
        finally:
            catalog.close()
        # Detect a source changed during a verification that must never authorize deletion.
        _trusted(raw, row)
        return {"schema_version": PROOF_VERSION, "segment": raw.name,
                "raw_sha256": row["raw_sha"], "raw_bytes": row["raw_size"],
                "gzip_sha256": row["gzip_sha"], "gzip_bytes": row["gzip_size"],
                "manifest_sha256": _sha(manifest), "records": count,
                "catalog_records_sha256": identity.hexdigest(), "catalog_match_count": count,
                "sqlite_quick_check": "ok", "recovery_tested": True,
                "raw_present": raw.exists(), "original_modified": False,
                "approval_required": True, "removal_authorized": False}


def verify_cold_segment(raw_path, *, catalog_row, cache_directory, min_free_bytes, max_cache_bytes):
    reader = ColdSegmentReader(cache_directory, min_free_bytes=min_free_bytes, max_cache_bytes=max_cache_bytes)
    proof = reader.verify_metadata(raw_path, catalog_row=catalog_row)
    if proof["raw_present"]:
        _publish(Path(str(Path(raw_path).absolute()) + ".cold-proof.json"), proof)
    return proof


def inventory(directory, *, now, warm_seconds):
    directory = _regular(directory, required=False)
    now = _time(now)
    if type(warm_seconds) is not int or not 0 <= warm_seconds <= 366 * 86400:
        raise ValueError("bounded explicit warm retention interval required")
    catalog = _regular(directory / "events-archive.sqlite")
    db = sqlite3.connect(f"file:{catalog.resolve()}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    try:
        db.execute("BEGIN")
        ages = {r[0]: r[1] for r in db.execute("SELECT segment,max(available_at) FROM records GROUP BY segment")}
        segments = [dict(r) for r in db.execute("SELECT * FROM segments ORDER BY name")]
    finally:
        db.close()
    rows = []
    for row in segments:
        if row["name"] == "legacy":
            rows.append({**row, "tier": "PROTECTED_LEGACY", "removal_authorized": False})
            continue
        raw = _regular(directory / "events-segments" / row["name"], required=False)
        entry = {**row, "raw_path": str(raw), "gzip_path": str(raw) + ".gz",
                 "manifest_path": str(raw) + ".manifest.json", "removal_authorized": False}
        if row["status"] == "active":
            entry.update(tier="ACTIVE", cold_verified=False, eligible_at=None)
        else:
            candidates = [_time(ages[row["name"]])] if ages.get(row["name"]) else []
            for path in [raw, Path(str(raw) + ".manifest.json")]:
                if path.exists():
                    _regular(path)
                    candidates.append(datetime.fromtimestamp(path.stat().st_mtime, UTC))
            if not candidates:
                raise ValueError("sealed segment has no retention age evidence")
            completed_bound = max(candidates)
            eligible_at = completed_bound + timedelta(seconds=warm_seconds)
            proof_path = Path(str(raw) + ".cold-proof.json")
            verified = False
            if proof_path.exists():
                proof = _bounded_json(proof_path)
                verified = (proof.get("schema_version") == PROOF_VERSION and proof.get("recovery_tested") is True
                            and proof.get("raw_sha256") == row["raw_sha"] and proof.get("gzip_sha256") == row["gzip_sha"]
                            and proof.get("records") == row["records"] and proof.get("catalog_match_count") == row["records"]
                            and proof.get("sqlite_quick_check") == "ok" and proof.get("original_modified") is False
                            and proof.get("approval_required") is True and proof.get("removal_authorized") is False
                            and isinstance(proof.get("catalog_records_sha256"), str) and len(proof["catalog_records_sha256"]) == 64
                            and proof.get("manifest_sha256") == _sha(Path(str(raw) + ".manifest.json")))
                if not verified:
                    raise ValueError("invalid cold verification proof")
            tier = "WARM" if now < eligible_at else ("COLD_VERIFIED_ORIGINAL_RETAINED" if verified else "COLD_PENDING_VERIFICATION")
            entry.update(tier=tier, cold_verified=verified, eligible_at=eligible_at.isoformat(),
                         age_seconds=max(0, (now-completed_bound).total_seconds()),
                         age_basis="max(catalog availability, raw mtime, seal-manifest mtime)",
                         cold_proof_path=str(proof_path))
            if raw.exists():
                st = raw.stat()
                entry.update(raw_device=st.st_dev, raw_inode=st.st_ino, raw_bytes_current=st.st_size)
        rows.append(entry)
    raw_bytes = sum(r.get("raw_size") or 0 for r in segments if r["status"] == "sealed")
    gzip_bytes = sum(r.get("gzip_size") or 0 for r in segments if r["status"] == "sealed")
    return {"schema_version": "phase15-archive-inventory-v1", "observed_at": now.isoformat(),
            "directory": str(directory), "warm_seconds": warm_seconds, "segments": rows,
            "closed_raw_bytes": raw_bytes, "completed_gzip_bytes": gzip_bytes,
            "gzip_to_raw_ratio": gzip_bytes/raw_bytes if raw_bytes else None,
            "catalog_bytes": sum(p.stat().st_size for p in directory.glob("events-archive.sqlite*") if p.is_file()),
            "original_removal_implemented": False, "trading_authority": False}


def process_references(paths):
    """Read only matching inode references; inaccessible namespaces fail closed."""
    wanted = {}
    for path in paths:
        path = _regular(path)
        st = path.stat()
        wanted[(st.st_dev, st.st_ino)] = str(path)
    references, incomplete = [], 0
    seen = 0
    for process in Path("/proc").iterdir():
        if not process.name.isdecimal():
            continue
        seen += 1
        if seen > 32768:
            incomplete += 1
            break
        try:
            for fd in (process / "fd").iterdir():
                try:
                    st = fd.stat()
                    matched = wanted.get((st.st_dev, st.st_ino))
                    if matched:
                        references.append({"pid": int(process.name), "kind": "fd", "path": matched})
                except FileNotFoundError:
                    continue
            with (process / "maps").open() as maps:
                for i, line in enumerate(maps):
                    if i >= 100000:
                        incomplete += 1
                        break
                    parts = line.split(None, 5)
                    if len(parts) < 5:
                        continue
                    major, minor = parts[3].split(":")
                    matched = wanted.get((os.makedev(int(major, 16), int(minor, 16)), int(parts[4])))
                    if matched:
                        references.append({"pid": int(process.name), "kind": "mapping", "path": matched})
        except FileNotFoundError:
            continue
        except (PermissionError, ProcessLookupError):
            incomplete += 1
    return {"scope": "procfs file descriptors and memory mappings", "complete": incomplete == 0,
            "inaccessible_or_truncated_processes": incomplete, "references": references}


def retention_proposal(directory, *, now, warm_seconds, retention_class):
    if retention_class not in RETENTION_CLASSES:
        raise ValueError("explicit supported retention class required")
    result = inventory(directory, now=now, warm_seconds=warm_seconds)
    candidates = [r for r in result["segments"] if r["tier"] == "COLD_VERIFIED_ORIGINAL_RETAINED"]
    audit = process_references([r["raw_path"] for r in candidates]) if candidates else {
        "scope": "no age-qualified verified candidates", "complete": True, "references": []}
    referenced = {r["path"] for r in audit["references"]}
    proposed = []
    for row in candidates:
        raw = Path(row["raw_path"])
        _, compressed, manifest, trusted = _trusted(raw, row)
        proof = _bounded_json(row["cold_proof_path"])
        catalog = sqlite3.connect(f"file:{(raw.parent.parent / 'events-archive.sqlite').resolve()}?mode=ro", uri=True)
        current_hash, current_count = hashlib.sha256(), 0
        try:
            for current in catalog.execute("SELECT * FROM records WHERE segment=? ORDER BY id", (raw.name,)):
                current_hash.update((_canonical(list(current)) + "\n").encode())
                current_count += 1
        finally:
            catalog.close()
        if current_count != proof["records"] or current_hash.hexdigest() != proof["catalog_records_sha256"]:
            raise ValueError("catalog changed since independent cold proof")
        if _sha(raw) != trusted["raw_sha"] or _sha(compressed) != proof["gzip_sha256"]:
            raise ValueError("retention candidate changed since cold proof")
        st = raw.stat()
        reasons = []
        if retention_class == "retain_original":
            reasons.append("retention_class_prohibits_original_removal")
        if not audit["complete"]:
            reasons.append("complete_privileged_process_reference_audit_required")
        if str(raw) in referenced:
            reasons.append("original_referenced_by_active_process")
        proposed.append({"raw_path": str(raw), "raw_sha256": trusted["raw_sha"], "raw_bytes": st.st_size,
                         "raw_device": st.st_dev, "raw_inode": st.st_ino, "raw_links": st.st_nlink,
                         "gzip_path": str(compressed), "gzip_sha256": trusted["gzip_sha"],
                         "gzip_bytes": compressed.stat().st_size, "manifest_path": str(manifest),
                         "manifest_sha256": _sha(manifest), "cold_proof_sha256": _digest(proof),
                         "records": trusted["records"], "catalog_records_sha256": proof["catalog_records_sha256"],
                         "eligible_at": row["eligible_at"], "approval_required": True,
                         "removal_authorized": False, "review_prerequisites_met": not reasons,
                         "rejection_reasons": reasons})
    proposal = {"schema_version": "phase15-retention-proposal-v1", "observed_at": result["observed_at"],
                "directory": result["directory"], "retention_class": retention_class,
                "warm_seconds": warm_seconds, "process_reference_audit": audit, "candidates": proposed,
                "raw_bytes_proposed": sum(r["raw_bytes"] for r in proposed),
                "approval_required": True, "removal_authorized": False,
                "required_owner_action": "Explicit approval of this exact proposal hash and named originals after revalidation; this program has no deletion API",
                "revalidate_before_any_future_action": True, "original_removal_implemented": False}
    proposal["proposal_sha256"] = _digest(proposal)
    return proposal
