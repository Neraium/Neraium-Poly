"""Lossless SQLite segments with a durable all-history index and no purge policy.

A committed segment row precedes its catalogue row. Recovery verifies immutable
sources and reconciles that single-owner write ordering before accepting writes.
Original legacy/segment files are never moved, replaced, compressed while open,
or deleted. Gzip files are additional verified copies, not a retention shortcut.
"""

import fcntl
import gzip
import hashlib
import json
import os
import re
import shutil
import sqlite3
import stat
from collections import deque
from contextlib import ExitStack, contextmanager
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock

from neraium_poly.data.store import EventStore

NAME = re.compile(r"segment-[0-9]{8}\.sqlite\Z")
CHUNK = 1024 * 1024


def _sha(path):
    result = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK), b""):
            result.update(chunk)
    return result.hexdigest()


def _sync_dir(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _readonly(path):
    if path.is_symlink() or not path.is_file():
        raise ValueError("archive source missing or symlinked")
    return sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True, timeout=10)


def _tree_size(directory):
    """One metadata lookup per entry, never follow a swapped directory symlink."""
    def visit(fd):
        total = 0
        with os.scandir(fd) as entries:
            for entry in entries:
                try:
                    metadata = entry.stat(follow_symlinks=False)
                    if stat.S_ISLNK(metadata.st_mode):
                        raise ValueError("symlink inside managed service archive")
                    if stat.S_ISDIR(metadata.st_mode):
                        nested = os.open(entry.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                        try:
                            total += visit(nested)
                        finally:
                            os.close(nested)
                    elif stat.S_ISREG(metadata.st_mode):
                        total += metadata.st_size
                except FileNotFoundError:  # SQLite/cache sidecars may disappear concurrently.
                    continue
        return total
    fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        return visit(fd)
    finally:
        os.close(fd)


class ManagedEventStore:
    """Single-owner append-only event archive; budgets include the service tree."""

    def __init__(self, path, *, segment_bytes, budget_bytes, min_free_bytes, compress=True, clock=None, cold_verification_enabled=False):
        if segment_bytes < 4096 or budget_bytes < segment_bytes or min_free_bytes < 0:
            raise ValueError("invalid bounded archive configuration")
        self.path = Path(path).absolute()
        self.directory = self.path.parent
        self.segment_dir = self.directory / "events-segments"
        self.catalog_path = self.directory / "events-archive.sqlite"
        self.segment_bytes, self.budget_bytes = segment_bytes, budget_bytes
        self.min_free_bytes, self.compress = min_free_bytes, compress
        self.clock = clock or (lambda: datetime.now(UTC))
        self._lock = RLock()
        self.active = self.catalog = self._owner = None
        self.active_name = None
        self._dirty = False
        self._last_error = None
        self._usage_at = None
        self._usage = self._pending = 0
        self._samples = deque(maxlen=64)
        self._cold = None
        self._cold_verified = {}
        if type(cold_verification_enabled) is not bool:
            raise ValueError("explicit boolean cold verification configuration required")
        self.cold_verification_enabled = cold_verification_enabled
        self._cold_scan_at = self._cold_success_at = self._cold_proof_name = None
        self._cold_error = None
        self.directory.mkdir(parents=True, exist_ok=True)
        try:
            for p in [self.path, self.segment_dir, self.catalog_path, self.directory / "events-archive.lock"]:
                if p.is_symlink():
                    raise ValueError("archive paths must not be symlinks")
            self._owner = (self.directory / "events-archive.lock").open("a+b")
            try:
                fcntl.flock(self._owner.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise ValueError("another archive owner is active") from error
            self._check_budget(256 * 1024, refresh=True)
            self.segment_dir.mkdir(exist_ok=True)
            if not self.catalog_path.exists() and any(self.segment_dir.iterdir()):
                raise ValueError("archive catalogue missing beside existing segments")
            self.catalog = sqlite3.connect(self.catalog_path, check_same_thread=False, timeout=10)
            self.catalog.row_factory = sqlite3.Row
            self.catalog.execute("PRAGMA journal_mode=WAL")
            self.catalog.execute("PRAGMA synchronous=FULL")
            self.catalog.execute("PRAGMA cache_size=-65536")  # Bounded64MiB; keep normal cache spilling.
            self.catalog.executescript("""
                CREATE TABLE IF NOT EXISTS segments(
                  name TEXT PRIMARY KEY,status TEXT NOT NULL,raw_sha TEXT,raw_size INTEGER,
                  records INTEGER NOT NULL DEFAULT 0,gzip_sha TEXT,gzip_size INTEGER);
                CREATE TABLE IF NOT EXISTS records(
                  id TEXT PRIMARY KEY,kind TEXT NOT NULL,available_at TEXT NOT NULL,
                  event_time TEXT NOT NULL,digest TEXT NOT NULL,segment TEXT NOT NULL,
                  qualified INTEGER NOT NULL);
                CREATE INDEX IF NOT EXISTS records_kind_time ON records(kind,available_at,id);
                CREATE INDEX IF NOT EXISTS records_segment ON records(segment);
                CREATE TABLE IF NOT EXISTS archive_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
                CREATE TRIGGER IF NOT EXISTS records_no_update BEFORE UPDATE ON records
                  BEGIN SELECT RAISE(ABORT,'append only archive index'); END;
                CREATE TRIGGER IF NOT EXISTS records_no_delete BEFORE DELETE ON records
                  BEGIN SELECT RAISE(ABORT,'append only archive index'); END;
                CREATE TRIGGER IF NOT EXISTS segments_no_delete BEFORE DELETE ON segments
                  BEGIN SELECT RAISE(ABORT,'archive sources cannot be deleted'); END;
            """)
            version = self.catalog.execute("SELECT value FROM archive_meta WHERE key='version'").fetchone()
            if version and version[0] != "1":
                raise ValueError("unsupported archive catalogue version")
            with self.catalog:
                self.catalog.execute("INSERT OR IGNORE INTO archive_meta VALUES('version','1')")
            if self.catalog.execute("PRAGMA quick_check").fetchall()[0][0] != "ok":
                raise ValueError("corrupt archive catalogue")
            self._recover()
            _sync_dir(self.directory)
            self._usage_at = None
            self._measure()
            self._samples.append((self.clock(), self._usage))
        except BaseException:
            self.close()
            raise

    def _measure(self):
        now = self.clock()
        if self._usage_at is None or (now - self._usage_at).total_seconds() >= 1:
            self._usage, self._pending, self._usage_at = _tree_size(self.directory), 0, now
        return self._usage + self._pending

    def _check_budget(self, extra=0, *, refresh=False):
        if refresh:
            self._usage_at = None
        usage = self._measure()
        if usage + extra >= self.budget_bytes:
            raise ValueError("archive_service_budget_exhausted")
        if shutil.disk_usage(self.directory).free < self.min_free_bytes + extra:
            raise ValueError("archive_global_free_floor_reached")

    def _source(self, name):
        if name == "legacy":
            return self.path
        if not NAME.fullmatch(name):
            raise ValueError("invalid archive segment path")
        return self.segment_dir / name

    def _cold_reader(self):
        if self._cold is None:
            # Delayed import: cold helpers depend on the segment format constants.
            from neraium_poly.data.cold import ColdSegmentReader

            self._cold = ColdSegmentReader(self.directory / "events-cold-cache",
                                            min_free_bytes=max(self.min_free_bytes, 8 * 1024**3),
                                            max_cache_bytes=64 * 1024**2)
        return self._cold

    def _verify_cold(self, name, row):
        identity = (row["raw_sha"], row["gzip_sha"], row["records"])
        if self._cold_verified.get(name) != identity:
            # Cold-only recovery must prove every indexed payload before accepting writes.
            self._check_budget(row["raw_size"] + 32768, refresh=True)
            self._cold_reader().verify_metadata(self._source(name), catalog_row=row)
            self._cold_verified[name] = identity

    @contextmanager
    def _open_source(self, name):
        path = self._source(name)
        if path.exists() or path.is_symlink():
            source = _readonly(path)
            try:
                yield source
            finally:
                source.close()
            return
        row = self.catalog.execute("SELECT * FROM segments WHERE name=?", (name,)).fetchone()
        if name == "legacy" or row is None or row["status"] != "sealed":
            raise ValueError("missing archive source segment")
        self._verify_cold(name, row)
        with self._cold_reader().open(path, catalog_row=row) as source:
            yield source

    def _maintain_cold_proof(self):
        if not self.cold_verification_enabled:
            if self._cold_error:
                raise ValueError(self._cold_error)
            return
        now = self.clock()
        if self._cold_scan_at is not None and (now - self._cold_scan_at).total_seconds() < 60:
            if self._cold_error:
                raise ValueError(self._cold_error)
            return
        self._cold_scan_at = now
        for row in self.catalog.execute("SELECT * FROM segments WHERE status='sealed' AND gzip_sha IS NOT NULL ORDER BY name"):
            path = self._source(row["name"])
            if path.exists() and not Path(str(path) + ".cold-proof.json").exists():
                from neraium_poly.data.cold import verify_cold_segment

                try:
                    self._check_budget(row["raw_size"] + 32768, refresh=True)
                    verify_cold_segment(path, catalog_row=row, cache_directory=self.directory / "events-cold-cache",
                                        min_free_bytes=max(self.min_free_bytes, 8 * 1024**3), max_cache_bytes=64 * 1024**2)
                except Exception as error:  # Retain failed integrity admission between scans.
                    self._cold_error = f"cold_verification:{type(error).__name__}:{str(error)[:160]}"
                    raise
                self._cold_error = None
                self._cold_success_at, self._cold_proof_name = now, row["name"]
                self._usage_at = None
                return  # One complete independent restoration per scan, never an unbounded batch.
        if self._cold_error:
            raise ValueError(self._cold_error)

    def _catalog_record(self, row, segment):
        # Deliberately separate from segment commit: an orphan durable row is replayed.
        rid, kind, available, event, payload, digest = row
        if hashlib.sha256(payload.encode()).hexdigest() != digest:
            raise ValueError("corrupt archive payload digest")
        parsed = json.loads(payload)
        if (parsed.get("id") != rid
            or datetime.fromisoformat(parsed["timestamp"]) != datetime.fromisoformat(event)
            or datetime.fromisoformat(parsed["available_at"]) != datetime.fromisoformat(available)):
            raise ValueError("archive row metadata does not match original payload")
        qualified = int(parsed["qualified"]) if type(parsed.get("qualified")) is bool else -1
        previous = self.catalog.execute("SELECT * FROM records WHERE id=?", (rid,)).fetchone()
        expected = (rid, kind, available, event, digest, segment, qualified)
        if previous:
            if tuple(previous) != expected:
                raise ValueError("archive identity collision or catalogue mismatch")
            return False
        self.catalog.execute("INSERT INTO records VALUES(?,?,?,?,?,?,?)", expected)
        return True

    def _index_segment(self, path, name=None):
        name = name or ("legacy" if path == self.path else path.name)
        source = _readonly(path)
        total = 0
        try:
            if source.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise ValueError("corrupt archive segment")
            with self.catalog:
                for row in source.execute("SELECT id,kind,available_at,event_time,payload,digest FROM events"):
                    if total % 1000 == 0:
                        # Pure verification allocates no new source/catalogue rows.
                        # Retain the existing <=1s tree accounting and fresh global
                        # floor check instead of rescanning thousands of paths for
                        # every1000already-indexed records. Any orphan insertion
                        # invalidates accounting before the next batch/write.
                        self._check_budget(512 * 1024)
                    if self._catalog_record(row, name):
                        self._usage_at = None
                    total += 1
                    if total % 1000 == 0:
                        self.catalog.commit()
                indexed = self.catalog.execute("SELECT count(*) FROM records WHERE segment=?", (name,)).fetchone()[0]
                if indexed != total:
                    raise ValueError("catalogue references missing archive records")
                self.catalog.execute("UPDATE segments SET records=? WHERE name=? AND records<>?", (total, name, total))
        finally:
            source.close()
        return total

    def _manifest(self, name, *, digest, size, records):
        return {"schema_version": "1.0", "segment": name, "raw_sha256": digest,
                "raw_bytes": size, "records": records, "retention_policy": "retain_original"}

    def _read_manifest(self, path):
        if path.is_symlink() or path.stat().st_size > 16384:
            raise ValueError("invalid immutable archive manifest")
        return json.loads(path.read_text())

    def _write_manifest(self, name, digest, size, records):
        path = Path(str(self._source(name)) + ".manifest.json")
        expected = self._manifest(name, digest=digest, size=size, records=records)
        if path.exists():
            if self._read_manifest(path) != expected:
                raise ValueError("immutable archive manifest changed")
            return
        pending = Path(str(path) + ".pending")
        if pending.exists():
            if pending.is_symlink():
                raise ValueError("symlinked pending archive manifest")
            pending.unlink()
        with pending.open("x") as handle:
            handle.write(json.dumps(expected, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.link(pending, path)
        _sync_dir(path.parent)
        pending.unlink()
        _sync_dir(path.parent)

    def _recover(self):
        known = {r["name"]: r for r in self.catalog.execute("SELECT * FROM segments")}
        if self.path.exists() and "legacy" not in known:
            if Path(str(self.path) + "-wal").exists() and Path(str(self.path) + "-wal").stat().st_size:
                raise ValueError("legacy archive must be closed and checkpointed before adoption")
            total = self._index_segment(self.path, "legacy")
            with self.catalog:
                self.catalog.execute(
                    "INSERT INTO segments(name,status,raw_sha,raw_size,records) VALUES(?,?,?,?,?)",
                    ("legacy", "legacy", _sha(self.path), self.path.stat().st_size, total),
                )
        known = {r["name"]: dict(r) for r in self.catalog.execute("SELECT * FROM segments")}
        unknown = [p for p in self.segment_dir.iterdir() if NAME.fullmatch(p.name) and p.name not in known]
        if len(unknown) > 1:
            raise ValueError("ambiguous interrupted archive rotation")
        for p in unknown:
            total = self._index_segment(p)
            with self.catalog:
                self.catalog.execute("INSERT INTO segments(name,status,records) VALUES(?,?,?)", (p.name, "active", total))
            known[p.name] = dict(self.catalog.execute("SELECT * FROM segments WHERE name=?", (p.name,)).fetchone())
        for name, row in known.items():
            path = self._source(name)
            if not path.exists() and row["status"] == "sealed":
                self._verify_cold(name, row)
                continue  # Catalog is complete; never rehydrate or recreate the original.
            if not path.is_file() or path.is_symlink():
                raise ValueError("missing archive source segment")
            manifest_path = Path(str(path) + ".manifest.json")
            if row["status"] in {"sealed", "legacy"} or manifest_path.exists():
                wal = Path(str(path) + "-wal")
                if wal.exists() and wal.stat().st_size:
                    raise ValueError("immutable archive has an uncheckpointed writer")
            if row["status"] in {"sealed", "legacy"}:
                if path.stat().st_size != row["raw_size"] or _sha(path) != row["raw_sha"]:
                    raise ValueError("immutable archive source changed")
            elif row["status"] != "active":
                raise ValueError("invalid archive segment state")
            total = self._index_segment(path, name)
            if name != "legacy" and (row["status"] == "sealed" or manifest_path.exists()):
                if not manifest_path.exists():
                    raise ValueError("sealed archive manifest missing")
                actual = self._manifest(name, digest=_sha(path), size=path.stat().st_size, records=total)
                if self._read_manifest(manifest_path) != actual:
                    raise ValueError("immutable archive manifest changed")
                if row["status"] == "active":
                    with self.catalog:
                        self.catalog.execute("UPDATE segments SET status='sealed',raw_sha=?,raw_size=? WHERE name=?", (actual["raw_sha256"], actual["raw_bytes"], name))
                    row = dict(self.catalog.execute("SELECT * FROM segments WHERE name=?", (name,)).fetchone())
            if row["gzip_sha"]:
                self._verify_compressed(row)
            elif row["status"] == "sealed" and Path(str(path) + ".gz").exists():
                # A published copy can precede its catalogue metadata commit.
                self._compress(row)
        orphan = self.catalog.execute("SELECT count(*) FROM records r LEFT JOIN segments s ON r.segment=s.name WHERE s.name IS NULL").fetchone()[0]
        if orphan:
            raise ValueError("catalogue references an unknown archive source")
        active = [r[0] for r in self.catalog.execute("SELECT name FROM segments WHERE status='active'")]
        if len(active) > 1:
            raise ValueError("ambiguous interrupted archive rotation")
        if active:
            self.active_name = active[0]
            self.active = EventStore(self._source(self.active_name))
        else:
            self._create_active()

    def _create_active(self):
        names = {p.name for p in self.segment_dir.iterdir() if NAME.fullmatch(p.name)}
        names.update(r[0] for r in self.catalog.execute("SELECT name FROM segments") if NAME.fullmatch(r[0]))
        number = max([int(name[8:16]) for name in names] or [0]) + 1
        if number > 99999999:
            raise ValueError("archive segment identity space exhausted")
        name = f"segment-{number:08d}.sqlite"
        path = self._source(name)
        self._check_budget(128 * 1024)
        active = EventStore(path)
        try:
            _sync_dir(self.segment_dir)
            with self.catalog:
                self.catalog.execute("INSERT INTO segments(name,status) VALUES(?,'active')", (name,))
        except BaseException:
            active.close()
            raise
        self.active, self.active_name = active, name

    def _seal_active(self):
        if self.active is None:
            return
        path, name = self._source(self.active_name), self.active_name
        with self.active._lock:
            result = self.active.connection.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
            if result[0]:
                raise ValueError("active archive checkpoint busy")
            self.active.close()
        self.active = None
        with path.open("rb") as source:
            os.fsync(source.fileno())
        records = self._index_segment(path, name)
        digest, size = _sha(path), path.stat().st_size
        self._write_manifest(name, digest, size, records)
        with self.catalog:
            self.catalog.execute("UPDATE segments SET status='sealed',raw_sha=?,raw_size=? WHERE name=?",
                                 (digest, size, name))
        _sync_dir(self.segment_dir)

    def _publish_compression(self, temporary, target):
        # Existing copies are never replaced, including after interrupted publication.
        os.link(temporary, target)
        _sync_dir(target.parent)
        temporary.unlink()  # Disposable duplicate pending output, not original evidence.
        _sync_dir(target.parent)

    def _verify_compressed(self, row):
        target = Path(str(self._source(row["name"])) + ".gz")
        if not target.is_file() or target.is_symlink() or _sha(target) != row["gzip_sha"]:
            raise ValueError("corrupt compressed archive copy")
        digest = hashlib.sha256()
        length = 0
        with gzip.open(target, "rb") as handle:
            for chunk in iter(lambda: handle.read(CHUNK), b""):
                digest.update(chunk)
                length += len(chunk)
        if digest.hexdigest() != row["raw_sha"] or length != row["raw_size"]:
            raise ValueError("compressed archive roundtrip mismatch")

    def _compress(self, row):
        source = self._source(row["name"])
        target = Path(str(source) + ".gz")
        temporary = Path(str(target) + ".pending")
        if row["status"] != "sealed" or self.active_name == row["name"]:
            raise ValueError("cannot compress an open or legacy archive")
        if _sha(source) != row["raw_sha"]:
            raise ValueError("immutable archive source changed")
        if not target.exists():
            self._check_budget(row["raw_size"] + 256 * 1024, refresh=True)
            # An interrupted pending copy is disposable only after its source validates.
            if temporary.exists():
                if temporary.is_symlink():
                    raise ValueError("symlinked pending archive copy")
                temporary.unlink()
            with source.open("rb") as raw, temporary.open("xb") as output:
                with gzip.GzipFile(fileobj=output, mode="wb", compresslevel=1, mtime=0) as compressed:
                    for chunk in iter(lambda: raw.read(CHUNK), b""):
                        self._check_budget(len(chunk) + 65536)
                        compressed.write(chunk)
                output.flush()
                os.fsync(output.fileno())
            # Validate exact source bytes before publishing under the final name.
            digest = hashlib.sha256()
            length = 0
            with gzip.open(temporary, "rb") as handle:
                for chunk in iter(lambda: handle.read(CHUNK), b""):
                    digest.update(chunk)
                    length += len(chunk)
            if digest.hexdigest() != row["raw_sha"] or length != row["raw_size"]:
                raise ValueError("pending compressed archive roundtrip mismatch")
            self._publish_compression(temporary, target)
        verified = dict(row)
        verified["gzip_sha"] = _sha(target)
        self._verify_compressed(verified)
        if temporary.exists():
            if temporary.is_symlink():
                raise ValueError("symlinked pending archive copy")
            temporary.unlink()
            _sync_dir(target.parent)
        with self.catalog:
            self.catalog.execute("UPDATE segments SET gzip_sha=?,gzip_size=? WHERE name=?",
                                 (verified["gzip_sha"], target.stat().st_size, row["name"]))
        self._usage_at = None

    def append(self, record):
        payload = record.model_dump_json()
        digest = hashlib.sha256(payload.encode()).hexdigest()
        if len(payload.encode()) > 8 * CHUNK:
            raise ValueError("archive record exceeds bounded payload size")
        with self._lock:
            if self._dirty:
                self._index_segment(self._source(self.active_name))
                self._dirty = False
                self._last_error = None
            previous = self.get(record.id)
            if previous:
                if previous[2] != digest:
                    raise ValueError("event ID collision with different payload")
                return False
            if self._last_error:
                raise ValueError(self._last_error)
            self._check_budget(len(payload.encode()) * 3 + 256 * 1024)
            if self.active is None:
                self._recover()
            active_size = sum(p.stat().st_size for p in self.segment_dir.glob(self.active_name + "*") if p.is_file())
            if active_size + len(payload.encode()) * 2 + 8192 > self.segment_bytes and self.active.count():
                self._seal_active()
                self._create_active()
            row = (record.id, type(record).__name__, record.available_at.isoformat(), record.timestamp.isoformat(), payload, digest)
            self.active.append(record)
            self._dirty = True
            try:
                with self.catalog:
                    self._catalog_record(row, self.active_name)
                    self.catalog.execute("UPDATE segments SET records=records+1 WHERE name=?", (self.active_name,))
                self._dirty = False
                self._pending += len(payload.encode()) * 3 + 256 * 1024
            except BaseException:
                self._last_error = "archive catalogue recovery required"
                raise
            return True

    def can_write(self):
        """Cheap fail-closed admission; exact usage reporting belongs to status()."""
        with self._lock:
            try:
                if self._last_error:
                    return False
                self._check_budget(256 * 1024)
                return True
            except (OSError, ValueError) as error:
                self._last_error = f"archive_admission:{type(error).__name__}:{str(error)[:160]}"
                return False

    def maintain(self):
        with self._lock:
            try:
                self._check_budget(256 * 1024, refresh=True)
                if self._dirty:
                    self._index_segment(self._source(self.active_name))
                    self._dirty = False
                if self.active is None:
                    self._recover()
                active_size = sum(p.stat().st_size for p in self.segment_dir.glob(self.active_name + "*") if p.is_file())
                if active_size >= self.segment_bytes and self.active.count():
                    self._seal_active()
                    self._create_active()
                if self.compress:
                    row = self.catalog.execute("SELECT * FROM segments WHERE status='sealed' AND gzip_sha IS NULL ORDER BY name LIMIT 1").fetchone()
                    if row:
                        self._compress(row)
                self._maintain_cold_proof()
                self._last_error = None
            except Exception as error:  # noqa: BLE001 - a maintenance failure must stop archive writes
                self._last_error = f"archive_maintenance:{type(error).__name__}:{str(error)[:160]}"
            return self.status()

    def _fetch(self, row):
        with self._open_source(row["segment"]) as source:
            value = source.execute("SELECT kind,payload,digest FROM events WHERE id=?", (row["id"],)).fetchone()
        if value is None or value[0] != row["kind"] or value[2] != row["digest"] or hashlib.sha256(value[1].encode()).hexdigest() != value[2]:
            raise ValueError("corrupt or missing indexed archive record")
        return value

    def get(self, record_id):
        with self._lock:
            row = self.catalog.execute("SELECT * FROM records WHERE id=?", (record_id,)).fetchone()
            return self._fetch(row) if row else None

    def count(self, *, kind=None, qualified=None):
        clauses, values = [], []
        if kind is not None:
            clauses.append("kind=?")
            values.append(kind)
        if qualified is not None:
            clauses.append("qualified=?")
            values.append(int(qualified))
        with self._lock:
            return self.catalog.execute("SELECT count(*) FROM records" + (" WHERE " + " AND ".join(clauses) if clauses else ""), values).fetchone()[0]

    def latest(self, kind, limit=100):
        if not 1 <= limit <= 10000:
            raise ValueError("bounded latest archive query required")
        with self._lock:
            rows = self.catalog.execute("SELECT * FROM records WHERE kind=? ORDER BY available_at DESC,id DESC LIMIT ?", (kind, limit)).fetchall()
            return [json.loads(self._fetch(row)[1]) for row in rows]

    def iter_replay(self, *, until=None, kind=None):
        """Stream historical records; caller should exhaust/close this locked iterator."""
        if until is not None and until.tzinfo is None:
            raise ValueError("timezone required")
        clauses, values = [], []
        if until is not None:
            clauses.append("available_at<=?")
            values.append(until.astimezone(UTC).isoformat())
        if kind is not None:
            clauses.append("kind=?")
            values.append(kind)
        query = "SELECT * FROM records" + (" WHERE " + " AND ".join(clauses) if clauses else "") + " ORDER BY available_at,event_time,id"
        with self._lock:
            connection, segment = None, None
            with ExitStack() as sources:
                for row in self.catalog.execute(query, values):
                    if segment != row["segment"]:
                        sources.close()  # Unpin previous cold inode before another restore.
                        segment = row["segment"]
                        connection = sources.enter_context(self._open_source(segment))
                    value = connection.execute("SELECT kind,payload,digest FROM events WHERE id=?", (row["id"],)).fetchone()
                    if value is None or value[0] != row["kind"] or value[2] != row["digest"] or hashlib.sha256(value[1].encode()).hexdigest() != value[2]:
                        raise ValueError("corrupt or missing indexed archive record")
                    yield {"kind": row["kind"], "record": json.loads(value[1])}

    def replay(self, *, until=None, kind=None):
        return list(self.iter_replay(until=until, kind=kind))

    def status(self):
        with self._lock:
            now = self.clock()
            sample_due = not self._samples or (now - self._samples[-1][0]).total_seconds() >= 5
            self._usage_at = None
            usage = self._measure()
            if sample_due:
                self._samples.append((now, self._usage))
            elapsed = (self._samples[-1][0] - self._samples[0][0]).total_seconds() if self._samples else 0
            delta = self._samples[-1][1] - self._samples[0][1] if self._samples else 0
            rate = delta / elapsed if elapsed >= 10 and delta >= 0 else None
            free = shutil.disk_usage(self.directory).free
            remaining = max(0, self.budget_bytes - usage)
            error = self._last_error
            if usage >= self.budget_bytes:
                error = "archive_service_budget_exhausted"
            if free < self.min_free_bytes:
                error = "archive_global_free_floor_reached"
            rows = list(self.catalog.execute("SELECT * FROM segments"))
            active_bytes = sum(p.stat().st_size for p in self.segment_dir.glob((self.active_name or "NOACTIVE") + "*") if p.is_file())
            sealed = [r for r in rows if r["status"] == "sealed"]
            missing = [r["name"] for r in sealed if not self._source(r["name"]).exists()]
            cache = self.directory / "events-cold-cache"
            cache_bytes = sum(p.stat().st_size for p in cache.iterdir() if p.is_file()) if cache.exists() else 0
            warm_bytes = cold_bytes = segment_metadata_bytes = 0
            for p in self.segment_dir.iterdir():
                if p.is_file() and not p.name.startswith(self.active_name or "NOACTIVE"):
                    size = p.stat().st_size
                    if NAME.fullmatch(p.name):
                        warm_bytes += size
                    elif p.name.endswith(".sqlite.gz"):
                        cold_bytes += size
                    else:
                        segment_metadata_bytes += size
            protected_bytes = self.path.stat().st_size if self.path.exists() else 0
            allocations = {"active": active_bytes, "warm": warm_bytes, "cold": cold_bytes,
                           "protected": protected_bytes, "derived_cache": cache_bytes,
                           "segment_metadata": segment_metadata_bytes}
            allocations["catalog_state"] = max(0, usage - sum(allocations.values()))
            tiers = {"active_segments": sum(r["status"] == "active" for r in rows),
                     "sealed_originals_present": len(sealed) - len(missing),
                     "cold_only_segments": len(missing), "cold_only_verified_this_process": len(self._cold_verified),
                     "cold_proofs_present": sum(Path(str(self._source(r["name"])) + ".cold-proof.json").is_file() for r in sealed),
                     "derived_cache_bytes": cache_bytes, "derived_cache_budget_bytes": 64 * 1024**2,
                     "counts_scope": "current catalog and filesystem; proof presence is not integrity verification"}
            return {"managed": True, "usage_bytes": usage, "usage_is_conservative_estimate": bool(self._pending), "budget_bytes": self.budget_bytes,
                    "active_bytes": active_bytes, "segment_bytes": self.segment_bytes,
                    "segments": sum(r["status"] != "legacy" for r in rows),
                    "sealed_segments": sum(r["status"] == "sealed" for r in rows),
                    "compressed_segments": sum(r["gzip_sha"] is not None for r in rows),
                    "legacy_records": sum(r["records"] for r in rows if r["status"] == "legacy"),
                    "records": self.count(), "free_bytes": free, "growth_bytes_per_second": rate,
                    "remaining_bytes": remaining,
                    "seconds_to_exhaustion": min(remaining, max(0, free - self.min_free_bytes)) / rate if rate else None,
                    "global_floor_bytes": self.min_free_bytes, "retention_policy": "retain_all_originals_and_verified_copies",
                    "archive_tiers": tiers, "tier_usage_bytes": allocations,
                    "cold_verification": {"enabled": self.cold_verification_enabled,
                                          "minimum_scan_interval_seconds": 60,
                                          "last_scan_at": self._cold_scan_at.isoformat() if self._cold_scan_at else None,
                                          "last_success_at": self._cold_success_at.isoformat() if self._cold_success_at else None,
                                          "last_segment": self._cold_proof_name, "last_error": self._cold_error,
                                          "scope": "process-local progress; immutable proof presence is reported separately"},
                    "warnings": ["sealed_original_absent_verified_cold_recovery"] if missing else [],
                    "cold_only_names_sample": missing[:10],
                    "health": "blocked" if error else "ok", "last_error": error}

    def close(self):
        if self.active is not None:
            self.active.close()
            self.active = None
        if self.catalog is not None:
            self.catalog.close()
            self.catalog = None
        if self._owner is not None:
            fcntl.flock(self._owner.fileno(), fcntl.LOCK_UN)
            self._owner.close()
            self._owner = None
