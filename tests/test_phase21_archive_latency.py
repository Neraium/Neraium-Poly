"""Controlled performance regressions preserve full integrity and floor checks."""
import hashlib
from datetime import UTC, datetime

import pytest
from neraium_poly.contracts import Record
from neraium_poly.data import EventStore, segmented
from neraium_poly.data.segmented import ManagedEventStore, _tree_size

NOW = datetime(2026, 11, 7, tzinfo=UTC)


def managed(path):
    return ManagedEventStore(path, segment_bytes=16*1024**2, budget_bytes=64*1024**2,
                             min_free_bytes=0, compress=False, clock=lambda: NOW)


def populated(path):
    legacy = EventStore(path)
    try:
        for n in range(2501):
            legacy.append(Record(id=f'CONTROLLED-{n}', source='controlled archive test',
                                 timestamp=NOW, available_at=NOW))
    finally:
        legacy.close()
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_readonly_reverification_reuses_bounded_accounting_and_verifies_every_row(tmp_path, monkeypatch):
    path = tmp_path/'events.sqlite'
    original = populated(path)
    store = managed(path)
    try:
        seen, walks, floors = [], [], []
        catalog = store._catalog_record
        tree_size = segmented._tree_size
        disk_usage = segmented.shutil.disk_usage
        monkeypatch.setattr(store, '_catalog_record', lambda row, name: (seen.append(row[0]), catalog(row, name))[1])
        monkeypatch.setattr(segmented, '_tree_size', lambda p: (walks.append(p), tree_size(p))[1])
        monkeypatch.setattr(segmented.shutil, 'disk_usage', lambda p: (floors.append(p), disk_usage(p))[1])
        store._usage_at = None
        assert store._index_segment(path, 'legacy') == 2501
        assert len(seen) == len(set(seen)) == 2501
        assert len(walks) == 1 and len(floors) == 3
        assert hashlib.sha256(path.read_bytes()).hexdigest() == original
    finally:
        store.close()


def test_cached_service_measurement_still_checks_current_filesystem_floor(tmp_path, monkeypatch):
    path = tmp_path/'events.sqlite'
    populated(path)
    store = managed(path)
    current = segmented.shutil.disk_usage(tmp_path)
    calls = []
    def disk_usage(_path):
        calls.append(1)
        return current if len(calls) == 1 else current._replace(free=0)
    monkeypatch.setattr(segmented.shutil, 'disk_usage', disk_usage)
    try:
        with pytest.raises(ValueError, match='global_free_floor'):
            store._index_segment(path, 'legacy')
        assert len(calls) == 2
        assert store.count() == 2501
    finally:
        store.close()


def test_orphan_catalogue_insert_invalidates_usage_before_next_write(tmp_path):
    store = managed(tmp_path/'events.sqlite')
    try:
        row = Record(id='CONTROLLED-orphan', source='controlled missing catalog', timestamp=NOW, available_at=NOW)
        store.active.append(row)  # Simulate committed source preceding interrupted index commit.
        store._usage_at = NOW
        assert store._index_segment(store._source(store.active_name)) == 1
        assert store._usage_at is None
        assert store.get(row.id)[2] == hashlib.sha256(row.model_dump_json().encode()).hexdigest()
    finally:
        store.close()


def test_fast_tree_walk_counts_nested_files_and_rejects_file_and_directory_aliases(tmp_path):
    (tmp_path/'one').write_bytes(b'1234')
    (tmp_path/'nested').mkdir()
    (tmp_path/'nested'/'two').write_bytes(b'567')
    assert _tree_size(tmp_path) == 7
    (tmp_path/'alias').symlink_to(tmp_path/'one')
    with pytest.raises(ValueError, match='symlink'):
        _tree_size(tmp_path)
    (tmp_path/'alias').unlink()  # Disposable test fixture only.
    (tmp_path/'alias').symlink_to(tmp_path/'nested', target_is_directory=True)
    with pytest.raises(ValueError, match='symlink'):
        _tree_size(tmp_path)
