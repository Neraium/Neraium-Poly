"""Controlled cold-only managed recovery; no production evidence is removed."""

import json
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from neraium_poly.contracts import Record
from neraium_poly.data.segmented import ManagedEventStore
from neraium_poly.data.store import EventStore


def create(tmp_path, *, legacy=False):
    path = tmp_path / "CONTROLLED-service" / "events.sqlite"
    now = datetime.now(UTC)
    if legacy:
        old = EventStore(path)
        old.append(Record(id="CONTROLLED-legacy", timestamp=now, available_at=now, source="fixture"))
        old.close()
    options = {"segment_bytes": 4096, "budget_bytes": 32 * 1024**2, "min_free_bytes": 0}
    store = ManagedEventStore(path, **options)
    records = [Record(id=f"CONTROLLED-{i}", timestamp=now + timedelta(seconds=i),
                      available_at=now + timedelta(seconds=i), source="CONTROLLED fixture") for i in range(4)]
    for record in records:
        store.append(record)
    store._seal_active()
    store.active_name = None  # Controlled checkpoint with no writable segment.
    for row in store.catalog.execute("SELECT * FROM segments WHERE status='sealed'").fetchall():
        store._compress(row)
    rows = [dict(row) for row in store.catalog.execute("SELECT * FROM segments WHERE status='sealed'")]
    baseline = store.replay()
    store.close()
    # Deliberately remove only controlled-fixture originals to simulate a future
    # separately authorized retention transition. No application deletion API exists.
    for row in rows:
        (path.parent / "events-segments" / row["name"]).unlink()
    return path, options, rows, records, baseline


def test_cold_only_restart_get_latest_replay_dedup_and_monotonic_segment_ids(tmp_path):
    path, options, rows, records, baseline = create(tmp_path)
    highest = max(int(r["name"][8:16]) for r in rows)
    store = ManagedEventStore(path, **options)
    try:
        assert int(store.active_name[8:16]) > highest
        assert store.replay() == baseline
        for record in records:
            assert json.loads(store.get(record.id)[1])["id"] == record.id
            assert store.append(record) is False
        assert store.latest("Record", limit=2) == [r["record"] for r in reversed(baseline[-2:])]
        assert store.replay(until=records[1].available_at) == baseline[:2]
        changed = records[0].model_copy(update={"source": "CONTROLLED identity collision"})
        with pytest.raises(ValueError, match="ID collision"):
            store.append(changed)
        assert store.count() == len(records)
        status = store.status()
        assert status["archive_tiers"]["cold_only_segments"] == len(rows)
        assert sum(status["tier_usage_bytes"].values()) == status["usage_bytes"]
        assert status["tier_usage_bytes"]["warm"] == 0
        assert status["tier_usage_bytes"]["cold"] > 0
        assert status["archive_tiers"]["cold_only_verified_this_process"] == len(rows)
        assert "sealed_original_absent_verified_cold_recovery" in status["warnings"]
        assert not any((path.parent / "events-segments" / row["name"]).exists() for row in rows)
    finally:
        store.close()
    again = ManagedEventStore(path, **options)
    try:
        assert again.replay() == baseline and again.count() == len(records)
    finally:
        again.close()


def test_managed_cold_recovery_rejects_catalog_corruption(tmp_path):
    path, options, rows, _records, _baseline = create(tmp_path)
    db = sqlite3.connect(path.parent / "events-archive.sqlite")
    db.execute("DROP TRIGGER records_no_update")
    db.execute("UPDATE records SET digest=? WHERE segment=?", ("a" * 64, rows[0]["name"]))
    db.commit()
    db.close()
    with pytest.raises(ValueError, match="differs from global catalog"):
        ManagedEventStore(path, **options)
    assert not (path.parent / "events-segments" / rows[0]["name"]).exists()


def test_managed_cold_recovery_rejects_gzip_corruption_without_recreating_raw(tmp_path):
    path, options, rows, _records, _baseline = create(tmp_path)
    raw = path.parent / "events-segments" / rows[0]["name"]
    with Path(str(raw) + ".gz").open("ab") as handle:
        handle.write(b"CONTROLLED corruption")
    with pytest.raises(ValueError, match="compressed copy hash/length"):
        ManagedEventStore(path, **options)
    assert not raw.exists()


def test_missing_legacy_or_active_archive_never_uses_cold_fallback(tmp_path):
    path, options, _rows, _records, _baseline = create(tmp_path, legacy=True)
    path.unlink()  # CONTROLLED legacy only.
    with pytest.raises(ValueError, match="missing archive source"):
        ManagedEventStore(path, **options)
    other = tmp_path / "active" / "events.sqlite"
    store = ManagedEventStore(other, **options)
    active = store._source(store.active_name)
    store.close()
    active.unlink()  # CONTROLLED active only.
    with pytest.raises(ValueError, match="missing archive source"):
        ManagedEventStore(other, **options)


def test_replay_generator_close_releases_cold_cache_pin(tmp_path, monkeypatch):
    path, options, _rows, _records, _baseline = create(tmp_path)
    store = ManagedEventStore(path, **options)
    reader = store._cold_reader()
    original, pins = reader.open, []

    @contextmanager
    def observed(*args, **kwargs):
        with original(*args, **kwargs) as source:
            pins.append(1)
            try:
                yield source
            finally:
                pins.pop()

    monkeypatch.setattr(reader, "open", observed)
    try:
        replay = store.iter_replay()
        next(replay)
        assert pins == [1]
        replay.close()
        assert pins == []
        assert store.get("CONTROLLED-0") is not None and pins == []
    finally:
        store.close()


def test_opt_in_maintenance_verifies_one_segment_per_minute_and_keeps_originals(tmp_path):
    path = tmp_path / "proof-service" / "events.sqlite"
    now = [datetime.now(UTC)]
    options = {"segment_bytes": 4096, "budget_bytes": 32 * 1024**2, "min_free_bytes": 0,
               "clock": lambda: now[0]}
    store = ManagedEventStore(path, cold_verification_enabled=True, **options)
    try:
        for i in range(4):
            store.append(Record(id=f"CONTROLLED-proof-{i}", timestamp=now[0], available_at=now[0], source="fixture"))
        for row in store.catalog.execute("SELECT * FROM segments WHERE status='sealed'").fetchall():
            store._compress(row)
        first = store.maintain()
        proofs = list(store.segment_dir.glob("*.cold-proof.json"))
        assert len(proofs) == 1 and first["cold_verification"]["last_success_at"] == now[0].isoformat()
        store.maintain()
        assert len(list(store.segment_dir.glob("*.cold-proof.json"))) == 1
        now[0] += timedelta(seconds=60)
        store.maintain()
        assert len(list(store.segment_dir.glob("*.cold-proof.json"))) == 2
        assert all(Path(str(proof).removesuffix(".cold-proof.json")).exists() for proof in proofs)
    finally:
        store.close()


def test_cold_proof_maintenance_defaults_disabled_and_failure_blocks_archive(tmp_path, monkeypatch):
    path = tmp_path / "proof-service" / "events.sqlite"
    options = {"segment_bytes": 4096, "budget_bytes": 32 * 1024**2, "min_free_bytes": 0}
    store = ManagedEventStore(path, **options)
    try:
        for i in range(2):
            now = datetime.now(UTC)
            store.append(Record(id=f"CONTROLLED-failed-proof-{i}", timestamp=now, available_at=now, source="fixture"))
        assert store.maintain()["cold_verification"]["enabled"] is False
        assert not list(store.segment_dir.glob("*.cold-proof.json"))
        store.cold_verification_enabled = True

        def failed(*_args, **_kwargs):
            raise ValueError("CONTROLLED independent integrity failure")

        monkeypatch.setattr("neraium_poly.data.cold.verify_cold_segment", failed)
        status = store.maintain()
        assert status["health"] == "blocked" and "CONTROLLED independent integrity failure" in status["last_error"]
        assert store.can_write() is False
        assert store.maintain()["health"] == "blocked"  # No bypass via 60-second throttle.
        assert store.can_write() is False
        assert all(store._source(row[0]).exists() for row in store.catalog.execute("SELECT name FROM segments"))
    finally:
        store.close()
