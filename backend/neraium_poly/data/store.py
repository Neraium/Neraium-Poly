"""SQLite append-only operational event ledger with deterministic replay."""

import hashlib
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from threading import RLock

from neraium_poly.contracts import Record


class EventStore:
    def __init__(self, path: str | Path = ":memory:"):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(str(path), check_same_thread=False, timeout=10)
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA synchronous=FULL")
        self.connection.execute(
            "CREATE TABLE IF NOT EXISTS events (id TEXT PRIMARY KEY, kind TEXT NOT NULL, available_at TEXT NOT NULL, event_time TEXT NOT NULL, payload TEXT NOT NULL, digest TEXT NOT NULL)"
        )
        self.connection.execute(
            "CREATE TRIGGER IF NOT EXISTS events_no_update BEFORE UPDATE ON events BEGIN SELECT RAISE(ABORT, 'append only'); END"
        )
        self.connection.execute(
            "CREATE TRIGGER IF NOT EXISTS events_no_delete BEFORE DELETE ON events BEGIN SELECT RAISE(ABORT, 'append only'); END"
        )
        self.connection.commit()
        self._lock = RLock()

    def close(self):
        self.connection.close()

    def append(self, record: Record) -> bool:
        payload = record.model_dump_json()
        digest = hashlib.sha256(payload.encode()).hexdigest()
        with self._lock, self.connection:
            inserted = self.connection.execute(
                "INSERT OR IGNORE INTO events VALUES (?,?,?,?,?,?)",
                (
                    record.id,
                    type(record).__name__,
                    record.available_at.isoformat(),
                    record.timestamp.isoformat(),
                    payload,
                    digest,
                ),
            ).rowcount
            previous = self.connection.execute(
                "SELECT digest FROM events WHERE id=?", (record.id,)
            ).fetchone()
            if previous[0] != digest:
                raise ValueError("event ID collision with different payload")
        return bool(inserted)

    def replay(self, *, until: datetime | None = None, kind: str | None = None) -> list[dict]:
        """Availability first, event timestamp then stable ID; never insertion order."""
        if until is not None and until.tzinfo is None:
            raise ValueError("timezone required")
        clauses, params = [], []
        if until is not None:
            from datetime import UTC

            clauses.append("available_at <= ?")
            params.append(until.astimezone(UTC).isoformat())
        if kind is not None:
            clauses.append("kind = ?")
            params.append(kind)
        query = "SELECT kind,payload,digest FROM events"
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY available_at,event_time,id"
        with self._lock:
            rows = self.connection.execute(query, params).fetchall()
        result = []
        for event_kind, payload, digest in rows:
            if hashlib.sha256(payload.encode()).hexdigest() != digest:
                raise ValueError("corrupt replay event")
            result.append({"kind": event_kind, "record": json.loads(payload)})
        return result

    def get(self, record_id: str):
        with self._lock:
            row = self.connection.execute(
                "SELECT kind,payload,digest FROM events WHERE id=?", (record_id,)
            ).fetchone()
        if row and hashlib.sha256(row[1].encode()).hexdigest() != row[2]:
            raise ValueError("corrupt archived record")
        return row

    def latest(self, kind: str, limit: int = 100) -> list[dict]:
        if not 1 <= limit <= 1000:
            raise ValueError("bounded latest archive query required")
        with self._lock:
            rows = self.connection.execute(
                "SELECT payload,digest FROM events WHERE kind=? ORDER BY available_at DESC,id DESC LIMIT ?",
                (kind, limit),
            ).fetchall()
        result = []
        for payload, digest in rows:
            if hashlib.sha256(payload.encode()).hexdigest() != digest:
                raise ValueError("corrupt archived record")
            result.append(json.loads(payload))
        return result

    def count(self, *, kind: str | None = None, qualified: bool | None = None) -> int:
        clauses, params = [], []
        if kind is not None:
            clauses.append("kind=?")
            params.append(kind)
        if qualified is not None:
            clauses.append("json_extract(payload,'$.qualified')=?")
            params.append(int(qualified))
        query = "SELECT count(*) FROM events" + (" WHERE " + " AND ".join(clauses) if clauses else "")
        with self._lock:
            return self.connection.execute(query, params).fetchone()[0]
