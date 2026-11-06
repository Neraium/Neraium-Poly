"""Durable service state, bounded alerts and exclusive process ownership."""

import fcntl
import hashlib
import json
import sqlite3
from pathlib import Path
from threading import RLock


class LiveLedger:
    def __init__(self, directory: Path):
        directory.mkdir(parents=True, exist_ok=True)
        self.lock_file = (directory / "owner.lock").open("a+")
        try:
            fcntl.flock(self.lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.lock_file.close()
            raise ValueError("another paper coordinator owns this data directory") from None
        self.db = sqlite3.connect(directory / "service.sqlite", check_same_thread=False, isolation_level=None)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS state(key TEXT PRIMARY KEY,payload TEXT NOT NULL,digest TEXT NOT NULL)"
        )
        self._lock = RLock()

    def get(self, key, default=None):
        with self._lock:
            row = self.db.execute("SELECT payload,digest FROM state WHERE key=?", (key,)).fetchone()
            if row is None:
                return default
            if hashlib.sha256(row[0].encode()).hexdigest() != row[1]:
                raise ValueError("corrupt durable coordinator state")
            return json.loads(row[0])

    def put(self, key, value):
        payload = json.dumps(value, sort_keys=True, allow_nan=False)
        with self._lock:
            self.db.execute(
                "INSERT OR REPLACE INTO state VALUES(?,?,?)",
                (key, payload, hashlib.sha256(payload.encode()).hexdigest()),
            )

    def close(self):
        self.db.close()
        fcntl.flock(self.lock_file, fcntl.LOCK_UN)
        self.lock_file.close()
