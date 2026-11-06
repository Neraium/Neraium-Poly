"""Actual child-process crash with controlled fixtures, never operational archives."""

import json
import subprocess
import sys

from neraium_poly.contracts import Record
from neraium_poly.data.segmented import ManagedEventStore


def test_process_death_after_segment_commit_recovers_wal_and_global_identity(tmp_path):
    path = tmp_path / "events.sqlite"
    value = {"id": "CONTROLLED-hard-crash", "source": "CONTROLLED fixture",
             "timestamp": "2026-11-06T12:00:00Z", "available_at": "2026-11-06T12:00:00Z"}
    program = """
import json,os,sys
from neraium_poly.contracts import Record
from neraium_poly.data.segmented import ManagedEventStore
store=ManagedEventStore(sys.argv[1],segment_bytes=65536,budget_bytes=64*1024**2,min_free_bytes=0,compress=False)
def crash_after_segment_before_catalog(*args):
    os._exit(19)
store._catalog_record=crash_after_segment_before_catalog
store.append(Record.model_validate(json.loads(sys.argv[2])))
raise AssertionError('controlled crash did not happen')
"""
    child = subprocess.run([sys.executable, "-c", program, str(path), json.dumps(value)],
                           capture_output=True, text=True, timeout=20, check=False)
    assert child.returncode == 19, child.stderr
    store = ManagedEventStore(path, segment_bytes=65536, budget_bytes=64 * 1024**2,
                              min_free_bytes=0, compress=False)
    try:
        assert store.count() == 1
        assert store.get(value["id"])[0] == "Record"
        assert not store.append(Record.model_validate(value))
        assert store.count() == 1
        assert store.status()["health"] == "ok"
    finally:
        store.close()
