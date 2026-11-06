"""Controlled cold-tier fixtures; none are authentic market observations."""

import errno
import hashlib
import json
import os
import shutil
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from neraium_poly.contracts import Record
from neraium_poly.data import cold
from neraium_poly.data.segmented import ManagedEventStore


class ControlledRecord(Record):
    text: str


def fixture_archive(tmp_path):
    directory = tmp_path / "service"
    store = ManagedEventStore(directory / "events.sqlite", segment_bytes=4096,
                              budget_bytes=32 * 1024**2, min_free_bytes=0)
    now = datetime.now(UTC)
    for i in range(3):
        store.append(ControlledRecord(id=f"CONTROLLED-cold-{i}", timestamp=now,
                                      available_at=now, source="CONTROLLED fixture", text="x" * 4000))
    for _ in range(5):
        store.maintain()
    rows = [dict(r) for r in store.catalog.execute("SELECT * FROM segments WHERE status='sealed' ORDER BY name")]
    store.close()
    assert len(rows) >= 2 and all(r["gzip_sha"] for r in rows)
    return directory, rows, now + timedelta(days=2)


def verify(directory, row, *, cache=None):
    return cold.verify_cold_segment(directory / "events-segments" / row["name"], catalog_row=row,
                                    cache_directory=cache or directory / "cold-cache",
                                    min_free_bytes=0, max_cache_bytes=65536)


def test_cold_copy_independently_restores_all_records_without_source_change(tmp_path):
    directory, rows, _now = fixture_archive(tmp_path)
    row = rows[0]
    raw = directory / "events-segments" / row["name"]
    original = raw.read_bytes()
    proof = verify(directory, row)
    assert proof["recovery_tested"] is True and proof["sqlite_quick_check"] == "ok"
    assert proof["records"] == proof["catalog_match_count"] == row["records"]
    assert len(proof["catalog_records_sha256"]) == 64
    assert proof["approval_required"] is True and proof["removal_authorized"] is False
    assert raw.read_bytes() == original
    assert verify(directory, row) == proof
    reader = cold.ColdSegmentReader(directory / "cold-cache", min_free_bytes=0, max_cache_bytes=65536)
    with reader.open(raw, catalog_row=row) as db:
        assert db.execute("SELECT count(*) FROM events").fetchone()[0] == row["records"]
        with pytest.raises(sqlite3.OperationalError):
            db.execute("DELETE FROM events")


def test_controlled_gzip_only_fixture_recovers_without_recreating_original(tmp_path):
    directory, rows, _now = fixture_archive(tmp_path)
    raw = directory / "events-segments" / rows[0]["name"]
    proof = verify(directory, rows[0])
    proof_path = Path(str(raw) + ".cold-proof.json")
    original_proof = proof_path.read_bytes()
    raw.unlink()  # CONTROLLED fixture only; production has no original-removal API.
    reader = cold.ColdSegmentReader(directory / "cold-cache", min_free_bytes=0, max_cache_bytes=65536)
    restored = reader.verify_metadata(raw, catalog_row=rows[0])
    assert restored["raw_present"] is False
    assert restored["raw_sha256"] == proof["raw_sha256"]
    assert not raw.exists() and proof_path.read_bytes() == original_proof


def test_pinned_readers_prevent_cache_eviction_and_sources_always_survive(tmp_path):
    directory, rows, _now = fixture_archive(tmp_path)
    reader = cold.ColdSegmentReader(directory / "cold-cache", min_free_bytes=0, max_cache_bytes=65536)
    first, second = [directory / "events-segments" / r["name"] for r in rows[:2]]
    with (reader.open(first, catalog_row=rows[0]), pytest.raises(ValueError, match="readers pinned"),
          reader.open(second, catalog_row=rows[1])):
        pass
    with reader.open(second, catalog_row=rows[1]) as db:
        assert db.execute("SELECT count(*) FROM events").fetchone()[0] == rows[1]["records"]
    assert first.exists() and second.exists()
    assert Path(str(first) + ".gz").exists() and Path(str(second) + ".gz").exists()
    assert sum(p.stat().st_size for p in reader.directory.iterdir()) <= 65536


def test_corrupt_gzip_or_cache_is_detected_without_original_deletion(tmp_path):
    directory, rows, _now = fixture_archive(tmp_path)
    row = rows[0]
    raw = directory / "events-segments" / row["name"]
    verify(directory, row)
    cached = directory / "cold-cache" / (row["raw_sha"] + ".sqlite")
    with cached.open("r+b") as f:
        f.seek(100)
        f.write(b"CORRUPT")
    with pytest.raises(ValueError, match="corrupt derived"):
        verify(directory, row)
    assert hashlib.sha256(raw.read_bytes()).hexdigest() == row["raw_sha"]
    gz = Path(str(raw) + ".gz")
    with gz.open("ab") as f:
        f.write(b"CORRUPT")
    with pytest.raises(ValueError, match="compressed copy"):
        verify(directory, row)


def test_interrupted_cache_publication_is_recoverable_without_overwriting_source(tmp_path, monkeypatch):
    directory, rows, _now = fixture_archive(tmp_path)
    raw = directory / "events-segments" / rows[0]["name"]
    cache = directory / "cold-cache"
    link = cold.os.link
    failed = [False]

    def interrupt(source, target):
        if str(target).endswith(".sqlite") and not failed[0]:
            failed[0] = True
            raise OSError(errno.ENOSPC, "CONTROLLED publication failure")
        return link(source, target)

    monkeypatch.setattr(cold.os, "link", interrupt)
    with pytest.raises(OSError, match="CONTROLLED"):
        verify(directory, rows[0], cache=cache)
    assert list(cache.glob("*.pending"))
    monkeypatch.setattr(cold.os, "link", link)
    assert verify(directory, rows[0], cache=cache)["recovery_tested"] is True
    assert not list(cache.glob("*.pending"))
    assert raw.exists() and Path(str(raw) + ".gz").exists()


def test_hardlinked_completed_cache_pending_file_is_cleaned_after_restart(tmp_path):
    directory, rows, _now = fixture_archive(tmp_path)
    verify(directory, rows[0])
    cached = directory / "cold-cache" / (rows[0]["raw_sha"] + ".sqlite")
    pending = Path(str(cached) + ".pending")
    os.link(cached, pending)  # Controlled interruption after link before pending unlink.
    assert verify(directory, rows[0])["recovery_tested"] is True
    assert not pending.exists() and cached.exists()


def test_disk_floor_prevents_recovery_writes_without_losing_copy(tmp_path, monkeypatch):
    directory, rows, _now = fixture_archive(tmp_path)
    usage = shutil._ntuple_diskusage(1024, 1023, 1)
    monkeypatch.setattr(cold.shutil, "disk_usage", lambda _: usage)
    with pytest.raises(ValueError, match="filesystem safety floor"):
        verify(directory, rows[0])
    raw = directory / "events-segments" / rows[0]["name"]
    assert raw.exists() and Path(str(raw) + ".gz").exists()


def test_retention_proposal_is_exact_and_never_confers_deletion_authority(tmp_path, monkeypatch):
    directory, rows, now = fixture_archive(tmp_path)
    before = cold.inventory(directory, now=now, warm_seconds=86400)
    assert any(r["tier"] == "ACTIVE" for r in before["segments"])
    assert any(r["tier"] == "COLD_PENDING_VERIFICATION" for r in before["segments"])
    verify(directory, rows[0])
    monkeypatch.setattr(cold, "process_references", lambda _: {"scope": "CONTROLLED complete fixture", "complete": True, "references": []})
    proposal = cold.retention_proposal(directory, now=now, warm_seconds=86400,
                                       retention_class="proposed_raw_after_verified_cold")
    assert len(proposal["candidates"]) == 1
    candidate = proposal["candidates"][0]
    assert candidate["raw_sha256"] == rows[0]["raw_sha"]
    assert candidate["raw_inode"] > 0 and candidate["raw_device"] > 0
    assert candidate["review_prerequisites_met"] is True
    assert proposal["removal_authorized"] is candidate["removal_authorized"] is False
    assert proposal["approval_required"] is True
    assert len(proposal["proposal_sha256"]) == 64
    assert proposal == cold.retention_proposal(directory, now=now, warm_seconds=86400,
                                               retention_class="proposed_raw_after_verified_cold")
    retained = cold.retention_proposal(directory, now=now, warm_seconds=86400, retention_class="retain_original")
    assert "retention_class_prohibits_original_removal" in retained["candidates"][0]["rejection_reasons"]
    assert Path(candidate["raw_path"]).exists()


def test_unknown_or_active_process_references_block_retention_prerequisites(tmp_path, monkeypatch):
    directory, rows, now = fixture_archive(tmp_path)
    verify(directory, rows[0])
    path = str(directory / "events-segments" / rows[0]["name"])
    monkeypatch.setattr(cold, "process_references", lambda _: {"scope": "CONTROLLED partial audit", "complete": False,
                                                              "references": [{"pid": 1, "kind": "fd", "path": path}]})
    p = cold.retention_proposal(directory, now=now, warm_seconds=86400, retention_class="proposed_raw_after_verified_cold")
    assert not p["candidates"][0]["review_prerequisites_met"]
    assert set(p["candidates"][0]["rejection_reasons"]) == {"complete_privileged_process_reference_audit_required", "original_referenced_by_active_process"}


def test_catalog_change_after_cold_proof_is_not_approved_by_stale_proof(tmp_path, monkeypatch):
    directory, rows, now = fixture_archive(tmp_path)
    verify(directory, rows[0])
    db = sqlite3.connect(directory / "events-archive.sqlite")
    db.execute("DROP TRIGGER records_no_update")  # Explicit CONTROLLED corruption only.
    db.execute("UPDATE records SET digest=? WHERE segment=?", ("f" * 64, rows[0]["name"]))
    db.commit()
    db.close()
    monkeypatch.setattr(cold, "process_references", lambda _: {"complete": True, "references": []})
    with pytest.raises(ValueError, match="catalog changed"):
        cold.retention_proposal(directory, now=now, warm_seconds=86400, retention_class="proposed_raw_after_verified_cold")


def test_proof_or_manifest_corruption_fails_closed(tmp_path):
    directory, rows, now = fixture_archive(tmp_path)
    verify(directory, rows[0])
    raw = directory / "events-segments" / rows[0]["name"]
    proof = Path(str(raw) + ".cold-proof.json")
    value = json.loads(proof.read_text())
    value["catalog_match_count"] = 0
    proof.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="invalid cold verification proof"):
        cold.inventory(directory, now=now, warm_seconds=86400)
    manifest = Path(str(raw) + ".manifest.json")
    value = json.loads(manifest.read_text())
    value["records"] += 1
    manifest.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="manifest does not match"):
        verify(directory, rows[0])


def test_process_reference_audit_reports_a_known_open_fixture(tmp_path):
    path = tmp_path / "CONTROLLED-file"
    path.write_text("fixture")
    with path.open("rb"):
        report = cold.process_references([path])
    assert any(r["pid"] == os.getpid() and r["path"] == str(path) for r in report["references"])


def test_open_sqlite_writer_and_symlinked_cache_are_rejected(tmp_path):
    from neraium_poly.data import EventStore

    directory, rows, _now = fixture_archive(tmp_path)
    raw = directory / "events-segments" / rows[0]["name"]
    writer = EventStore(raw)  # Explicit unsafe CONTROLLED fixture, never production.
    try:
        now = datetime.now(UTC)
        writer.append(Record(id="CONTROLLED-new-writer", timestamp=now, available_at=now, source="fixture"))
        with pytest.raises(ValueError, match="active SQLite"):
            verify(directory, rows[0])
    finally:
        writer.close()
    target = tmp_path / "cache-target"
    target.mkdir()
    alias = tmp_path / "cache-alias"
    alias.symlink_to(target, target_is_directory=True)
    with pytest.raises(ValueError, match="symlinked"):
        cold.ColdSegmentReader(alias, min_free_bytes=0)
