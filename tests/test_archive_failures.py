"""Independent controlled archive fault tests; never actual trading evidence."""

import errno
import hashlib
import sqlite3
from datetime import UTC, datetime, timedelta

import pytest
from neraium_poly.contracts import MarketSnapshot
from neraium_poly.data import EventStore, segmented
from neraium_poly.data.segmented import ManagedEventStore

NOW = datetime(2026, 11, 6, 12, tzinfo=UTC)


def sample(index, *, seconds=None):
    at = NOW + timedelta(seconds=index if seconds is None else seconds)
    return MarketSnapshot(
        id=f"CONTROLLED-archive-{index}",
        timestamp=at,
        available_at=at,
        source="CONTROLLED fixture; not real market evidence",
        market_id="controlled",
        token_id="controlled-token",
        event_id="controlled-event",
        question="Controlled archive fixture. " * 1024,
        probability=0.4,
        resolution_rules="Controlled test only",
        resolution_source="fixture.invalid",
    )


def managed(path, **changes):
    return ManagedEventStore(
        path,
        **{
            "segment_bytes": 64 * 1024,
            "budget_bytes": 16 * 1024**2,
            "min_free_bytes": 0,
            **changes,
        },
    )


def make_legacy(path, records):
    store = EventStore(path)
    try:
        for record in records:
            store.append(record)
    finally:
        store.close()
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_committed_segment_orphan_recovers_after_catalog_interruption(tmp_path, monkeypatch):
    path = tmp_path / "events.sqlite"
    make_legacy(path, [])
    record = sample(1)
    store = managed(path)

    def interrupted_catalog(*_args, **_kwargs):
        raise OSError(errno.EIO, "CONTROLLED interruption after durable segment commit")

    monkeypatch.setattr(store, "_catalog_record", interrupted_catalog)
    try:
        with pytest.raises(OSError, match="CONTROLLED interruption"):
            store.append(record)
    finally:
        store.close()
    recovered = managed(path)
    try:
        assert recovered.count() == 1
        assert recovered.get(record.id)[2] == hashlib.sha256(record.model_dump_json().encode()).hexdigest()
        assert not recovered.append(record)
        assert len(recovered.replay()) == 1
    finally:
        recovered.close()


def test_legacy_and_sealed_history_keep_global_identity_and_order(tmp_path):
    path = tmp_path / "events.sqlite"
    legacy = sample(0, seconds=20)
    original_hash = make_legacy(path, [legacy])
    store = managed(path)
    try:
        for index in range(1, 7):
            store.append(sample(index))
            store.maintain()
        assert store.status()["sealed_segments"] >= 1
        assert not store.append(legacy)
        with pytest.raises(ValueError):
            store.append(legacy.model_copy(update={"question": "Conflicting controlled ID"}))
        ordered = [r["record"]["id"] for r in store.replay()]
        assert ordered == [f"CONTROLLED-archive-{i}" for i in range(1, 7)] + [legacy.id]
        assert [r["id"] for r in store.latest("MarketSnapshot", limit=2)] == [legacy.id, sample(6).id]
        assert store.count(kind="MarketSnapshot") == 7
    finally:
        store.close()
    assert hashlib.sha256(path.read_bytes()).hexdigest() == original_hash
    recovered = managed(path)
    try:
        assert recovered.count() == 7
        assert [r["record"]["id"] for r in recovered.replay()] == ordered
        assert recovered.get(legacy.id)[0] == "MarketSnapshot"
    finally:
        recovered.close()
    assert hashlib.sha256(path.read_bytes()).hexdigest() == original_hash


def test_low_filesystem_space_rejects_new_evidence_without_losing_history(tmp_path, monkeypatch):
    path = tmp_path / "events.sqlite"
    legacy = sample(0)
    make_legacy(path, [legacy])
    store = managed(path, min_free_bytes=4096)
    real_usage = segmented.shutil.disk_usage
    usage = real_usage(tmp_path)
    try:
        with monkeypatch.context() as patch:
            patch.setattr(segmented.shutil, "disk_usage", lambda _: usage._replace(free=1))
            with pytest.raises((ValueError, OSError)):
                store.append(sample(1))
        assert store.count() == 1
        assert store.get(legacy.id) is not None
        assert store.get(sample(1).id) is None
        assert store.append(sample(1))
    finally:
        store.close()


def test_total_budget_rejects_more_data_and_preserves_accepted_records(tmp_path):
    path = tmp_path / "events.sqlite"
    make_legacy(path, [])
    accepted = []
    store = managed(path, budget_bytes=1024**2, compress=False)
    try:
        for index in range(128):
            try:
                store.append(sample(index))
            except (ValueError, OSError):
                break
            accepted.append(sample(index))
        else:
            pytest.fail("controlled archive ignored its configured finite budget")
        assert accepted
        assert store.count() >= len(accepted)
        for record in accepted:
            assert store.get(record.id) is not None
    finally:
        store.close()


def test_enospc_during_compression_publication_retains_originals(tmp_path, monkeypatch):
    path = tmp_path / "events.sqlite"
    original_hash = make_legacy(path, [sample(0)])
    store = managed(path)
    original_publish = store._publish_compression
    publications = []

    def disk_full(*_args, **_kwargs):
        publications.append(True)
        raise OSError(errno.ENOSPC, "CONTROLLED compression publication disk full")

    monkeypatch.setattr(store, "_publish_compression", disk_full)
    try:
        for index in range(1, 5):
            try:
                store.append(sample(index))
                store.maintain()
            except (OSError, ValueError) as error:
                assert (
                    isinstance(error, OSError) and error.errno == errno.ENOSPC
                ) or "compression publication disk full" in str(error)
                break
        assert store.status()["sealed_segments"] >= 1
        assert publications
        originals = [
            store.segment_dir / row[0]
            for row in store.catalog.execute(
                "SELECT name FROM segments WHERE status='sealed' AND name!='legacy'"
            )
        ]
        assert originals
        hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in originals}
        monkeypatch.setattr(store, "_publish_compression", original_publish)
    finally:
        store.close()
    assert hashlib.sha256(path.read_bytes()).hexdigest() == original_hash
    recovered = managed(path)
    try:
        recovered.maintain()
        for name, digest in hashes.items():
            assert hashlib.sha256((recovered.segment_dir / name).read_bytes()).hexdigest() == digest
        assert recovered.get(sample(0).id) is not None
        assert recovered.count() >= 2  # One legacy record plus an accepted segment row.
    finally:
        recovered.close()


def test_catalog_pointer_without_source_payload_fails_closed(tmp_path):
    path = tmp_path / "events.sqlite"
    make_legacy(path, [sample(0)])
    store = managed(path)
    catalog_path = store.catalog.execute("PRAGMA database_list").fetchone()[2]
    try:
        store.append(sample(1))
    finally:
        store.close()
    # Controlled on-disk corruption: never run against an operational database.
    db = sqlite3.connect(catalog_path)
    try:
        db.execute("UPDATE records SET segment='segment-99999999.sqlite' WHERE id=?", (sample(1).id,))
        db.commit()
    finally:
        db.close()
    with pytest.raises((ValueError, OSError, sqlite3.DatabaseError)):
        managed(path)


def test_corrupted_compressed_copy_is_detected_without_original_deletion(tmp_path):
    path = tmp_path / "events.sqlite"
    make_legacy(path, [])
    store = managed(path)
    try:
        for index in range(5):
            store.append(sample(index))
            store.maintain()
        copies = list(store.segment_dir.glob("*.sqlite.gz"))
        assert copies
    finally:
        store.close()
    copy = copies[0]
    original = copy.with_suffix("")
    digest = hashlib.sha256(original.read_bytes()).hexdigest()
    copy.write_bytes(b"CONTROLLED deliberately corrupt gzip")
    with pytest.raises((ValueError, OSError)):
        managed(path)
    assert original.exists()
    assert hashlib.sha256(original.read_bytes()).hexdigest() == digest


def test_published_compression_without_catalog_commit_is_adopted_not_replaced(tmp_path, monkeypatch):
    path = tmp_path / "events.sqlite"
    make_legacy(path, [])
    store = managed(path)
    original_verify = store._verify_compressed
    interrupted = []

    def after_publication(row):
        if not interrupted:
            interrupted.append(True)
            raise OSError(errno.EIO, "CONTROLLED interruption after gzip publication")
        return original_verify(row)

    monkeypatch.setattr(store, "_verify_compressed", after_publication)
    try:
        for index in range(5):
            try:
                store.append(sample(index))
                store.maintain()
            except (ValueError, OSError):
                break
        assert interrupted
        copies = list(store.segment_dir.glob("*.sqlite.gz"))
        assert copies
        published = copies[0]
        identity = (published.stat().st_ino, hashlib.sha256(published.read_bytes()).hexdigest())
    finally:
        store.close()
    recovered = managed(path)
    try:
        recovered.maintain()
        assert recovered.status()["compressed_segments"] >= 1
        assert (published.stat().st_ino, hashlib.sha256(published.read_bytes()).hexdigest()) == identity
        assert published.with_suffix("").is_file()
        assert recovered.count() >= 1
    finally:
        recovered.close()


def test_failed_seal_catalog_commit_does_not_create_two_active_segments(tmp_path):
    path = tmp_path / "events.sqlite"
    make_legacy(path, [])
    store = managed(path, compress=False)
    connection = store.catalog

    class FailSealOnce:
        failed = False

        def __getattr__(self, name):
            return getattr(connection, name)

        def __enter__(self):
            connection.__enter__()
            return self

        def __exit__(self, *args):
            return connection.__exit__(*args)

        def execute(self, sql, *args):
            if "UPDATE segments SET status='sealed'" in sql and not self.failed:
                self.failed = True
                raise OSError(errno.EIO, "CONTROLLED seal catalog interruption")
            return connection.execute(sql, *args)

    try:
        store.append(sample(1))
        store.catalog = FailSealOnce()
        with pytest.raises(OSError, match="seal catalog interruption"):
            store._seal_active()
        store.catalog = connection
        state = store.maintain()
        assert state["health"] == "ok"
        assert connection.execute("SELECT count(*) FROM segments WHERE status='active'").fetchone()[0] == 1
        assert store.append(sample(2))
    finally:
        store.catalog = connection
        store.close()
    recovered = managed(path, compress=False)
    try:
        assert recovered.count() == 2
        assert not recovered.append(sample(1))
        assert not recovered.append(sample(2))
    finally:
        recovered.close()
