"""Bounded read-only archive evidence; integrity is not independent source truth."""

import gzip
import hashlib
import json
import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from neraium_poly.research.phase14.relationships import digest
from neraium_poly.research.phase16.history import CausalHistory

SEGMENT = re.compile(r"segment-[0-9]{8}\.sqlite\Z")


def _time(value):
    at = value if isinstance(value, datetime) else datetime.fromisoformat(value)
    if at.tzinfo is None or at.utcoffset() is None:
        raise ValueError("aware evidence timestamp required")
    return at.astimezone(UTC)


def _json(payload):
    def pairs(items):
        value = {}
        for key, item in items:
            if key in value:
                raise ValueError("duplicate evidence JSON key")
            value[key] = item
        return value
    def bad_constant(_value):
        raise ValueError("nonfinite evidence JSON value")
    return json.loads(payload, object_pairs_hook=pairs, parse_constant=bad_constant)


class ReadonlyArchive:
    """Read committed records without opening a store owner or restoring a DB.

    Raw sources must already exist. Every operation closes its SQLite handles;
    readers cannot hold a long transaction against the active WAL. Catalog hashes
    bind source payloads, while source times and identities are checked separately.
    This does not claim an archive hash independently proves an exchange assertion.
    """

    def __init__(self, directory, *, max_payload_bytes=16 * 1024**2, max_query_bytes=64 * 1024**2):
        self.directory = self._regular(directory, directory=True)
        self.catalog_path = self._regular(self.directory / "events-archive.sqlite")
        if (type(max_payload_bytes) is not int or not 1024 <= max_payload_bytes <= 32 * 1024**2
            or type(max_query_bytes) is not int or not max_payload_bytes <= max_query_bytes <= 128 * 1024**2):
            raise ValueError("bounded archive payload/query limits required")
        self.max_payload_bytes, self.max_query_bytes = max_payload_bytes, max_query_bytes
        self.closed = False

    @staticmethod
    def _regular(path, *, directory=False):
        path = Path(path).absolute()
        if path.is_symlink() or any(p.is_symlink() for p in path.parents):
            raise ValueError("symlinked archive path")
        if not (path.is_dir() if directory else path.is_file()):
            raise ValueError("existing archive source required")
        return path.resolve()

    def _connection(self, path):
        if self.closed:
            raise ValueError("archive reader closed")
        path = self._regular(path)
        c = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=3)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA query_only=ON")
        c.execute("PRAGMA cache_size=-2048")
        return c

    def _catalog_rows(self, sql, args):
        c = self._connection(self.catalog_path)
        try:
            return c.execute(sql, args).fetchall()
        finally:
            c.close()

    def _source_path(self, name):
        if name == "legacy":
            return self._regular(self.directory / "events.sqlite")
        if not isinstance(name, str) or not SEGMENT.fullmatch(name):
            raise ValueError("invalid archive segment identity")
        return self._regular(self.directory / "events-segments" / name)

    def _fetch(self, row):
        c = self._connection(self._source_path(row["segment"]))
        try:
            size = c.execute("SELECT length(CAST(payload AS BLOB)) FROM events WHERE id=?", (row["id"],)).fetchone()
            if size is None or not 0 < size[0] <= self.max_payload_bytes:
                raise ValueError("missing or oversized archive payload")
            value = c.execute("SELECT * FROM events WHERE id=?", (row["id"],)).fetchone()
        finally:
            c.close()
        if (value["kind"] != row["kind"] or value["digest"] != row["digest"]
            or value["available_at"] != row["available_at"] or value["event_time"] != row["event_time"]
            or hashlib.sha256(value["payload"].encode()).hexdigest() != row["digest"]):
            raise ValueError("archive catalog/payload integrity mismatch")
        record = _json(value["payload"])
        if (not isinstance(record, dict) or record.get("id") != row["id"]
            or _time(record.get("available_at")) != _time(row["available_at"])
            or _time(record.get("timestamp")) != _time(row["event_time"])
            or _time(record["timestamp"]) > _time(record["available_at"])):
            raise ValueError("archive record identity/time binding mismatch")
        expected_qualified = int(record["qualified"]) if type(record.get("qualified")) is bool else -1
        if "qualified" in dict(row) and row["qualified"] != expected_qualified:
            raise ValueError("archive qualified flag mismatch")
        return value["kind"], value["payload"], value["digest"]

    def get(self, record_id):
        if not isinstance(record_id, str) or not 1 <= len(record_id) <= 512:
            raise ValueError("bounded archive record identity required")
        rows = self._catalog_rows("SELECT * FROM records WHERE id=?", (record_id,))
        return self._fetch(rows[0]) if rows else None

    def latest(self, kind, limit=100):
        if not isinstance(kind, str) or not 1 <= len(kind) <= 128 or type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError("bounded archive latest query required")
        rows = self._catalog_rows(
            "SELECT * FROM records WHERE kind=? ORDER BY available_at DESC,id DESC LIMIT ?", (kind, limit))
        result, size = [], 0
        for row in rows:
            value = self._fetch(row)
            size += len(value[1].encode())
            if size > self.max_query_bytes:
                raise ValueError("archive query byte budget exceeded")
            result.append(_json(value[1]))
        return result

    def verify_study(self, study):
        """Authenticate exact stored study bytes semantically; no new truth label."""
        try:
            raw = self.get(study["id"])
            return bool(raw and raw[0] == "QualificationStudy" and digest(_json(raw[1])) == digest(study)
                        and study.get("qualified") is False and study.get("trading_authority") is False
                        and isinstance(study.get("raw_frame"), dict))
        except (KeyError, ValueError, TypeError, sqlite3.Error):
            return False

    def verify_chain(self, studies):
        """Authenticate a bounded chronological contiguous study window.

        The first record's external parent is allowed because a bounded window
        need not begin at archive genesis. All subsequent parent links must match
        the preceding supplied study, and both event/availability times increase.
        This verifies coverage between endpoints, not an unseen external prefix.
        """
        if not isinstance(studies, (list, tuple)) or not 1 <= len(studies) <= 1000:
            return False
        previous, seen, used = None, set(), 0
        try:
            for study in studies:
                if not isinstance(study, dict):
                    return False
                used += len(json.dumps(study, sort_keys=True, separators=(",", ":"),
                                       allow_nan=False).encode())
                if used > min(self.max_query_bytes, 64 * 1024**2) or not self.verify_study(study):
                    return False
                identity, parent = study["id"], study.get("parent_id")
                if identity in seen or parent == identity:
                    return False
                if parent is not None and (not isinstance(parent, str) or not 1 <= len(parent) <= 512):
                    return False
                available, event = _time(study["available_at"]), _time(study["timestamp"])
                if event > available:
                    return False
                if previous is not None and (parent != previous["id"]
                    or available <= _time(previous["available_at"])
                    or event <= _time(previous["timestamp"])):
                    return False
                seen.add(identity)
                previous = study
            return True
        except (KeyError, ValueError, TypeError, sqlite3.Error):
            return False

    def verify_point(self, point, study):
        """Recompute Phase16 point from authenticated raw market/book/fee context."""
        if not self.verify_study(study):
            return False
        try:
            result = CausalHistory(max_tokens=64, history_size=60).observe(study["raw_frame"], now=_time(study["available_at"]))
            return (_time(point["source_at"]) <= _time(point["available_at"]) <= _time(point["observed_at"])
                    and any(digest(p) == digest(point) for p in result["accepted"]))
        except (KeyError, ValueError, TypeError):
            return False

    def verify_pair(self, pair, decision_study, label_study):
        """Verify observed monetary horizon label, never terminal settlement.

        Two endpoint studies do not independently prove the chosen target was the
        first eligible quote. Callers retain/replay the intervening source chain.
        """
        try:
            a, b = pair["decision"], pair["label"]
            target = _time(a["observed_at"])
            lag = (_time(b["source_at"])-target).total_seconds()
            return (self.verify_point(a, decision_study) and self.verify_point(b, label_study)
                and all(a[key] == b[key] for key in ("token_id", "market_id", "event_id", "rules_sha256"))
                and pair.get("id") == digest([a["id"], b["id"], "60s-top3-bid-mark"])
                and a["bid_vwap"] is not None and a["ask_vwap"] is not None and b["bid_vwap"] is not None
                and pair.get("independent_outcome") is False and pair.get("trading_authority") is False
                and pair.get("label_semantics") == "observed_top3_depth_bid_mark_not_fill_or_settlement"
                and pair["event_id"] == a["event_id"] and pair["quantity"] == 5
                and 60 <= lag <= 90
                and _time(pair["forecast_cutoff"]) == target and _time(pair["decision_at"]) == target
                and (_time(pair["target_at"])-target).total_seconds() == 60
                and _time(pair["label_available_at"]) == _time(b["available_at"])
                and _time(pair["label_observed_at"]) == _time(b["observed_at"])
                and abs(pair["label_lag_seconds"]-(lag-60)) <= 1e-9
                and pair["actual_bid"] == b["bid_vwap"] and pair["unchanged_bid_baseline"] == a["bid_vwap"])
        except (KeyError, ValueError, TypeError):
            return False

    def verify_segment(self, name, *, max_raw_bytes=256 * 1024**2):
        """Hash raw and existing compressed bytes without creating/restoring files."""
        if type(max_raw_bytes) is not int or not 4096 <= max_raw_bytes <= 1024**3:
            raise ValueError("bounded segment verification required")
        rows = self._catalog_rows("SELECT * FROM segments WHERE name=?", (name,))
        if not rows or rows[0]["status"] not in ("sealed", "legacy"):
            raise ValueError("completed immutable segment required")
        row = rows[0]
        path = self._source_path(name)
        if not 0 < row["raw_size"] <= max_raw_bytes or path.stat().st_size != row["raw_size"]:
            raise ValueError("segment raw byte bound or size mismatch")
        def sha_file(source):
            h = hashlib.sha256()
            with source.open("rb") as f:
                for chunk in iter(lambda: f.read(1024**2), b""):
                    h.update(chunk)
            return h.hexdigest()
        if sha_file(path) != row["raw_sha"]:
            raise ValueError("segment original hash mismatch")
        if name != "legacy":
            manifest_path = self._regular(str(path)+".manifest.json")
            if manifest_path.stat().st_size > 32768:
                raise ValueError("bounded segment manifest required")
            manifest = _json(manifest_path.read_text())
            expected = {"schema_version": "1.0", "segment": name, "raw_sha256": row["raw_sha"],
                        "raw_bytes": row["raw_size"], "records": row["records"],
                        "retention_policy": "retain_original"}
            if manifest != expected:
                raise ValueError("segment manifest/catalog identity mismatch")
        c = self._connection(path)
        try:
            if c.execute("SELECT count(*) FROM events").fetchone()[0] != row["records"]:
                raise ValueError("segment manifest record count mismatch")
            if c.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise ValueError("segment SQLite integrity failed")
        finally:
            c.close()
        proof = {"segment": name, "raw_sha256": row["raw_sha"], "raw_bytes": row["raw_size"],
                 "gzip_roundtrip_verified": False, "original_retirement_authorized": False}
        if row["gzip_sha"]:
            compressed = self._regular(str(path)+".gz")
            if compressed.stat().st_size != row["gzip_size"] or sha_file(compressed) != row["gzip_sha"]:
                raise ValueError("segment compressed hash/size mismatch")
            h, size = hashlib.sha256(), 0
            with gzip.open(compressed, "rb") as f:
                for chunk in iter(lambda: f.read(1024**2), b""):
                    size += len(chunk)
                    if size > row["raw_size"]:
                        raise ValueError("compressed segment expands beyond trusted size")
                    h.update(chunk)
            if size != row["raw_size"] or h.hexdigest() != row["raw_sha"]:
                raise ValueError("compressed segment roundtrip mismatch")
            proof.update(gzip_sha256=row["gzip_sha"], gzip_roundtrip_verified=True)
        return proof

    def close(self):
        self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.close()
