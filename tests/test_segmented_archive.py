"""Controlled archive fixtures; never authentic market or performance evidence."""

import hashlib
from datetime import UTC, datetime, timedelta

import pytest
from neraium_poly.contracts import Record
from neraium_poly.data.segmented import ManagedEventStore
from neraium_poly.data.store import EventStore

NOW = datetime(2026, 11, 6, tzinfo=UTC)


def record(i):
    return Record(id=f"controlled-{i}", timestamp=NOW + timedelta(seconds=i),
                  available_at=NOW + timedelta(seconds=i), source="CONTROLLED_fixture")


def managed(path, **changes):
    return ManagedEventStore(path, **{"segment_bytes": 65536, "budget_bytes": 16 * 1024**2,
                                     "min_free_bytes": 0, **changes})


def test_legacy_is_preserved_and_all_history_queries_survive_rotation(tmp_path):
    path = tmp_path / "events.sqlite"
    old = EventStore(path)
    old.append(record(0))
    old.close()
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    store = managed(path)
    try:
        assert not store.append(record(0))
        for i in range(1, 25):
            assert store.append(record(i))
        state = store.maintain()
        assert state["health"] == "ok"
        assert state["legacy_records"] == 1
        assert state["sealed_segments"] >= 2
        assert state["compressed_segments"] == 1
        assert store.count() == store.count(kind="Record") == 25
        assert store.count(qualified=True) == 0
        assert store.latest("Record", 2)[0]["id"] == "controlled-24"
        assert [x["record"]["id"] for x in store.iter_replay(until=NOW + timedelta(seconds=2))] == [
            "controlled-0", "controlled-1", "controlled-2"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == digest
        assert not path.with_suffix(".sqlite.gz").exists()
    finally:
        store.close()
    recovered = managed(path)
    try:
        assert recovered.count() == 25
        assert not recovered.append(record(24))
        assert len(recovered.replay()) == 25
        assert recovered.status()["legacy_records"] == 1
    finally:
        recovered.close()


def test_owner_duplicate_collision_and_actual_rate(tmp_path):
    now = [NOW]
    path = tmp_path / "events.sqlite"
    store = managed(path, clock=lambda: now[0])
    try:
        with pytest.raises(ValueError, match="another archive owner"):
            managed(path)
        assert store.status()["growth_bytes_per_second"] is None
        store.append(record(0))
        with pytest.raises(ValueError, match="collision"):
            store.append(record(0).model_copy(update={"source": "different"}))
        now[0] += timedelta(seconds=10)
        assert store.status()["growth_bytes_per_second"] > 0
        assert store.status()["seconds_to_exhaustion"] > 0
        with pytest.raises(ValueError, match="timezone"):
            store.replay(until=datetime(2026, 1, 1))
    finally:
        store.close()


def test_source_corruption_rejected_on_recovery(tmp_path):
    path = tmp_path / "events.sqlite"
    store = managed(path)
    for i in range(15):
        store.append(record(i))
    store.maintain()
    source = store.segment_dir / store.catalog.execute(
        "SELECT name FROM segments WHERE status='sealed' ORDER BY name LIMIT 1"
    ).fetchone()[0]
    store.close()
    with source.open("r+b") as handle:
        handle.seek(100)
        handle.write(b"CORRUPTED")
    with pytest.raises(ValueError, match="immutable archive source changed"):
        managed(path)


def test_frequent_status_calls_do_not_create_fake_growth_window(tmp_path):
    now = [NOW]
    store = managed(tmp_path / "events.sqlite", clock=lambda: now[0])
    try:
        store.append(record(0))
        for i in range(100):
            now[0] = NOW + timedelta(milliseconds=i)
            assert store.status()["growth_bytes_per_second"] is None
        assert len(store._samples) == 1
        now[0] = NOW + timedelta(seconds=10)
        assert store.status()["growth_bytes_per_second"] > 0
        assert len(store._samples) == 2
        measured_rate = store.status()["growth_bytes_per_second"]
        store.append(record(1))
        now[0] += timedelta(milliseconds=1)
        assert store.status()["growth_bytes_per_second"] == measured_rate
    finally:
        store.close()


def test_published_manifest_recovers_interrupted_catalogue_seal(tmp_path):
    path = tmp_path / "events.sqlite"
    store = managed(path)
    store.append(record(0))
    source = store._source(store.active_name)
    name = store.active_name
    store.active.connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    store.active.close()
    store.active = None
    store._write_manifest(name, hashlib.sha256(source.read_bytes()).hexdigest(), source.stat().st_size, 1)
    store.close()
    recovered = managed(path)
    try:
        assert recovered.active_name != name
        assert recovered.count() == 1
        assert recovered.catalog.execute("SELECT status FROM segments WHERE name=?", (name,)).fetchone()[0] == "sealed"
        assert recovered.maintain()["compressed_segments"] == 1
    finally:
        recovered.close()


def test_adopted_legacy_rejects_a_new_uncheckpointed_writer(tmp_path):
    path = tmp_path / "events.sqlite"
    original = EventStore(path)
    original.append(record(0))
    original.close()
    manager = managed(path)
    manager.close()
    unsafe_writer = EventStore(path)
    try:
        unsafe_writer.append(record(1))
        with pytest.raises(ValueError, match="uncheckpointed writer"):
            managed(path)
    finally:
        unsafe_writer.close()
