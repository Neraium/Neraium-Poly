"""Controlled derived-catalog migration; original records are never rewritten."""
import sqlite3
from datetime import UTC, datetime

from neraium_poly.contracts import Record
from neraium_poly.data.segmented import ManagedEventStore


def test_existing_catalog_adds_covering_segment_index_without_changing_records(tmp_path):
    path = tmp_path/'events.sqlite'
    def open_store():
        return ManagedEventStore(path, segment_bytes=8*1024**2, budget_bytes=1024**3,
                                 min_free_bytes=8*1024**3, compress=False)
    store = open_store()
    try:
        now = datetime.now(UTC)
        for i in range(4):
            store.append(Record(id=f'CONTROLLED-{i}', source='controlled-test', timestamp=now, available_at=now))
        original = [store.get(f'CONTROLLED-{i}') for i in range(4)]
    finally:
        store.close()
    # Reproduce the pre-fix schema in this disposable fixture only.
    with sqlite3.connect(tmp_path/'events-archive.sqlite') as db:
        db.execute('DROP INDEX records_segment')
        digests = db.execute('SELECT id,digest,segment FROM records ORDER BY id').fetchall()
    store = open_store()
    try:
        assert [store.get(f'CONTROLLED-{i}') for i in range(4)] == original
        assert [tuple(r) for r in store.catalog.execute('SELECT id,digest,segment FROM records ORDER BY id')] == digests
        plan = ' '.join(str(tuple(r)) for r in store.catalog.execute(
            'EXPLAIN QUERY PLAN SELECT count(*) FROM records WHERE segment=?', (store.active_name,)))
        assert 'records_segment' in plan and 'SCAN records' not in plan
        assert store.count() == 4
    finally:
        store.close()
