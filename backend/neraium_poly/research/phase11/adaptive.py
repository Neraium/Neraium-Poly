"""Append-only exploratory model versions and drift; never trading authority."""

import hashlib
import json
import math
import sqlite3
from datetime import UTC, datetime
from pathlib import Path


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


class ResearchRegistry:
    def __init__(self, path, *, max_versions=32):
        if not 1 <= max_versions <= 100:
            raise ValueError("bounded version count required")
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.max_versions = max_versions
        self.db.executescript("""
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS versions(
          id TEXT PRIMARY KEY, dataset TEXT NOT NULL, available_at TEXT NOT NULL,
          payload TEXT NOT NULL, digest TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS audit(
          seq INTEGER PRIMARY KEY, payload TEXT NOT NULL, digest TEXT NOT NULL);
        CREATE TRIGGER IF NOT EXISTS versions_no_update BEFORE UPDATE ON versions
          BEGIN SELECT RAISE(ABORT,'research versions append only'); END;
        CREATE TRIGGER IF NOT EXISTS versions_no_delete BEFORE DELETE ON versions
          BEGIN SELECT RAISE(ABORT,'research versions append only'); END;
        """)

    def _audit(self, event):
        prior = self.db.execute("SELECT digest FROM audit ORDER BY seq DESC LIMIT 1").fetchone()
        event = {**event, "previous_digest": prior[0] if prior else None}
        payload = canonical(event)
        self.db.execute(
            "INSERT INTO audit(payload,digest) VALUES(?,?)",
            (payload, hashlib.sha256(payload.encode()).hexdigest()),
        )

    def register(self, *, version_id, dataset_sha256, available_at, metrics, provenance):
        if len(dataset_sha256) != 64 or any(c not in "0123456789abcdef" for c in dataset_sha256):
            raise ValueError("dataset identity required")
        if available_at.tzinfo is None:
            raise ValueError("aware dataset availability required")
        rows = []
        for m in metrics:
            row = dict(m)
            for key in ("value", "baseline_value"):
                val = row.get(key)
                if val is not None and (isinstance(val, bool) or not math.isfinite(val) or val < 0):
                    raise ValueError("finite nonnegative error metrics required")
            value, baseline = row.get("value"), row.get("baseline_value")
            row["disposition"] = "insufficient_evidence"
            if value is not None and baseline is not None:
                row["disposition"] = (
                    "suspended_worse_than_baseline" if value > baseline else "exploratory_only"
                )
            row["promotion_eligible"] = False
            rows.append(row)
        payload = canonical(
            {
                "version_id": version_id,
                "dataset_sha256": dataset_sha256,
                "available_at": available_at.astimezone(UTC).isoformat(),
                "metrics": rows,
                "provenance": provenance,
                "certification_authority": False,
                "automatic_promotion": False,
            }
        )
        old = self.db.execute("SELECT payload FROM versions WHERE id=?", (version_id,)).fetchone()
        if old:
            if old[0] != payload:
                raise ValueError("research version identity reused")
            return json.loads(old[0])
        if self.db.execute("SELECT COUNT(*) FROM versions").fetchone()[0] >= self.max_versions:
            raise ValueError("research version storage budget exhausted")
        previous = self.db.execute("SELECT available_at FROM versions ORDER BY rowid DESC LIMIT 1").fetchone()
        if previous and available_at < datetime.fromisoformat(previous[0]):
            raise ValueError("research datasets must advance in availability order")
        self.db.execute("BEGIN IMMEDIATE")
        try:
            self.db.execute(
                "INSERT INTO versions VALUES(?,?,?,?,?)",
                (
                    version_id,
                    dataset_sha256,
                    available_at.astimezone(UTC).isoformat(),
                    payload,
                    hashlib.sha256(payload.encode()).hexdigest(),
                ),
            )
            self._audit(
                {"action": "register", "version_id": version_id, "timestamp": datetime.now(UTC).isoformat()}
            )
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise
        return json.loads(payload)

    def rollback(self, version_id, *, reason):
        if len(reason.strip()) < 12:
            raise ValueError("rollback reason required")
        if not self.db.execute("SELECT 1 FROM versions WHERE id=?", (version_id,)).fetchone():
            raise ValueError("unknown research version")
        self._audit(
            {
                "action": "rollback_research_selection",
                "version_id": version_id,
                "reason": reason,
                "timestamp": datetime.now(UTC).isoformat(),
                "operational_effect": False,
            }
        )

    def status(self):
        history = []
        for row in self.db.execute("SELECT * FROM versions ORDER BY rowid"):
            if hashlib.sha256(row["payload"].encode()).hexdigest() != row["digest"]:
                raise ValueError("corrupt research version")
            history.append(json.loads(row["payload"]))
        last_digest = None
        selected = history[-1]["version_id"] if history else None
        for row in self.db.execute("SELECT * FROM audit ORDER BY seq"):
            if hashlib.sha256(row["payload"].encode()).hexdigest() != row["digest"]:
                raise ValueError("corrupt research audit")
            event = json.loads(row["payload"])
            if event["previous_digest"] != last_digest:
                raise ValueError("broken research audit chain")
            last_digest = row["digest"]
            if event["action"] in {"register", "rollback_research_selection"}:
                selected = event["version_id"]
        drift = []
        if len(history) >= 2:
            previous = {m["model"]: m for m in history[-2]["metrics"]}
            for m in history[-1]["metrics"]:
                prior = previous.get(m["model"], {})
                if m.get("value") is not None and prior.get("value") is not None:
                    drift.append(
                        {
                            "model": m["model"],
                            "error_change": m["value"] - prior["value"],
                            "overlapping_datasets": True,
                            "independent_evidence": False,
                        }
                    )
        return {
            "versions": len(history),
            "selected_research_version": selected,
            "history": history,
            "drift": drift,
            "certification_authority": False,
            "automatic_promotion": False,
            "operational_effect": False,
        }

    def close(self):
        self.db.close()
