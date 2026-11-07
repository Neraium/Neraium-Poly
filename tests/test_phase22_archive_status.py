"""Controlled archive-view concurrency; no fixture is live market evidence."""
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from threading import Event, Thread
from types import SimpleNamespace

from neraium_poly.contracts import Record
from neraium_poly.data.segmented import ManagedEventStore


class Clock:
    def __init__(self): self.now = datetime(2026, 11, 7, 12, tzinfo=UTC)
    def __call__(self): return self.now


def archive(tmp_path, clock):
    return ManagedEventStore(tmp_path/'events.sqlite', segment_bytes=65536,
                             budget_bytes=64*1024**2, min_free_bytes=1024**2, clock=clock)


def test_status_view_does_not_wait_for_verification_lock_or_run_queries(tmp_path, monkeypatch):
    clock = Clock(); store = archive(tmp_path, clock)
    store.status()
    started, release = Event(), Event()
    def maintenance():
        with store._lock:
            started.set()
            assert release.wait(3)
    worker = Thread(target=maintenance); worker.start()
    try:
        assert started.wait(1)
        monkeypatch.setattr(store, 'status', lambda: (_ for _ in ()).throw(AssertionError('No strict view request')))
        value = store.operations_status()
        assert not release.is_set() and value['health'] == 'ok'
        assert value['snapshot_only'] and value['usage_is_historical']
        assert value['measurement_status'] == 'cached' and not value['admission_authority']
        # Mutable HTTP output cannot alter the next measurement or core checks.
        value['cold_verification']['enabled'] = 'CONTROLLED tamper'
        assert store.operations_status()['cold_verification']['enabled'] is False
    finally:
        release.set(); worker.join(); store.close()


def test_missing_stale_future_and_fresh_measurements_are_explicit(tmp_path):
    clock = Clock(); store = archive(tmp_path, clock)
    try:
        with store._snapshot_lock:
            store._status_snapshot = None  # CONTROLLED missing sampler publication
        empty = store.operations_status()
        assert empty['measurement_status'] == 'unavailable' and empty['usage_bytes'] is None
        assert empty['health'] == 'unknown' and not empty['admission_authority']
        strict = store.status(); saved = deepcopy(strict)
        clock.now += timedelta(seconds=61)
        stale = store.operations_status()
        assert stale['measurement_status'] == stale['health'] == 'stale'
        assert stale['measurement_at'] == saved['measurement_at'] and stale['seconds_to_exhaustion'] is None
        clock.now -= timedelta(seconds=62)
        assert store.operations_status()['measurement_status'] == 'stale'
        clock.now += timedelta(seconds=1)
        assert store.operations_status()['measurement_status'] == 'cached'
    finally:
        store.close()


def test_fresh_floor_failure_overrides_cached_ok_without_approving_writes(tmp_path, monkeypatch):
    import neraium_poly.data.segmented as module
    clock = Clock(); store = archive(tmp_path, clock); store.status()
    try:
        monkeypatch.setattr(module.shutil, 'disk_usage', lambda _p: SimpleNamespace(free=0))
        observed = store.operations_status()
        assert observed['free_bytes'] == 0 and observed['health'] == 'blocked'
        assert observed['last_error'] == 'archive_global_free_floor_reached'
        assert not store.can_write()
    finally:
        store.close()


def test_fault_and_closed_store_never_show_cached_ok(tmp_path):
    clock = Clock(); store = archive(tmp_path, clock); store.status()
    store._last_error = 'CONTROLLED corrupt archive'
    assert store.operations_status()['health'] == 'blocked'
    store.close()
    assert store.operations_status()['health'] == 'blocked'


def test_restart_revalidates_records_and_does_not_reuse_process_cache(tmp_path):
    clock = Clock(); store = archive(tmp_path, clock)
    try:
        store.append(Record(id='CONTROLLED-record', timestamp=clock(), available_at=clock(), source='controlled'))
        original = store.get('CONTROLLED-record'); store.status()
        assert store.operations_status()['health'] == 'ok'
    finally:
        store.close()
    store = archive(tmp_path, clock)
    try:
        assert store.get('CONTROLLED-record') == original
        # Startup reconstructs and publishes a new strict measurement; no cache is persisted.
        assert store.operations_status()['measurement_status'] == 'cached'
        assert store.operations_status()['health'] == 'ok'
    finally:
        store.close()


async def test_runtime_operations_endpoint_is_nonblocking_and_cannot_latch_fault(tmp_path, monkeypatch):
    import asyncio
    from concurrent.futures import ThreadPoolExecutor

    from fastapi.testclient import TestClient
    from neraium_poly.ops.api import create_app
    from neraium_poly.ops.live import LivePaperRuntime
    from neraium_poly.ops.live_config import LivePaperConfig
    from test_live_operation import FakeAdapter
    clock = Clock()
    config = LivePaperConfig(data_dir=tmp_path/'collector', coverage_enabled=False,
        archive_management_enabled=True, archive_reserve_disk_mb=8192, archive_budget_mb=64)
    runtime = LivePaperRuntime(config, adapter=FakeAdapter(clock), clock=clock)
    started, release = Event(), Event()
    def verification():
        with runtime.events._lock:
            started.set()
            assert release.wait(3)
    worker = Thread(target=verification); worker.start()
    try:
        assert started.wait(1)
        with ThreadPoolExecutor(max_workers=1) as pool:
            request = pool.submit(lambda: TestClient(create_app(runtime=runtime)).get('/api/archive-state'))
            response = request.result(timeout=1)
        assert response.status_code == 200
        assert response.json()['archive']['snapshot_only'] and response.json()['cash'] == 500
    finally:
        release.set(); worker.join()
    try:
        def failed_view(): raise RuntimeError('CONTROLLED view unavailable')
        monkeypatch.setattr(runtime.events, 'operations_status', failed_view)
        unknown = runtime.archive_state()['archive']
        assert unknown['health'] == 'unknown' and not unknown['admission_authority']
        assert runtime.archive_fault is None and runtime._budget_ok()
        runtime.archive_fault = 'CONTROLLED genuine strict storage failure'
        assert runtime.archive_state()['archive']['health'] == 'blocked'
    finally:
        await asyncio.wait_for(runtime.close(), 3)


def test_experimental_display_counters_are_unknown_while_archive_busy():
    from threading import RLock

    from neraium_poly.experimental.runtime import ExperimentalRuntime
    lock, started, release = RLock(), Event(), Event()
    def verification():
        with lock:
            started.set(); assert release.wait(3)
    def forbidden_count(**_kwargs): raise AssertionError('Busy counter must not query archive')
    runtime = SimpleNamespace(events=SimpleNamespace(_lock=lock, count=forbidden_count),
        config=SimpleNamespace(phase16_execution_veto_enabled=True), last_phase16_checks=[])
    worker = Thread(target=verification); worker.start()
    try:
        assert started.wait(1)
        view = ExperimentalRuntime.phase16_execution_status(runtime, for_operations=True)
        assert view['committed_vetoes'] is view['committed_check_passes'] is None
        assert view['counter_error'] == 'archive_counter_measurement_busy'
        assert view['enabled'] is True
    finally:
        release.set(); worker.join()
