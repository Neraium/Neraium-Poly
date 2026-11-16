"""Controlled recovery/transport fixtures; never forecast or trading evidence."""
import asyncio
import json
from datetime import UTC, datetime
from threading import Event
from types import SimpleNamespace

import httpx
import pytest
from neraium_poly.contracts import Record
from neraium_poly.data.archive_audit import audit
from neraium_poly.data.connectivity import StreamGap
from neraium_poly.data.memory_reserve import AllocatorReserve
from neraium_poly.data.segmented import ManagedEventStore
from neraium_poly.experimental.feed import SharedFeedClient
from neraium_poly.experimental.research_worker import ResearchWorker
from neraium_poly.experimental.runtime import ExperimentalRuntime
from test_connectivity import Socket, full
from test_experimental_feed import frame

NOW = datetime(2026, 11, 16, tzinfo=UTC)
pytest_plugins = ['test_connectivity']


def store(path):
    return ManagedEventStore(path, segment_bytes=65536, budget_bytes=64 * 1024**2,
                             min_free_bytes=0, compress=True)


def test_recovery_merge_verifies_existing_rows_without_random_catalog_queries(tmp_path):
    s = store(tmp_path / 'events.sqlite')
    try:
        for i in range(32):
            s.append(Record(id=f'fixture-{i:04}', timestamp=NOW, available_at=NOW, source='CONTROLLED'))
        statements = []
        s.catalog.set_trace_callback(statements.append)
        assert s._index_segment(s._source(s.active_name), s.active_name) > 0
        assert not any('SELECT * FROM records WHERE id=' in sql for sql in statements)
        assert s.count() == 32
    finally:
        s.close()


def test_recovery_merge_replays_orphan_and_rejects_extra_catalog_row(tmp_path):
    s = store(tmp_path / 'events.sqlite')
    try:
        s.append(Record(id='fixture-a', timestamp=NOW, available_at=NOW, source='CONTROLLED'))
        orphan = Record(id='fixture-b', timestamp=NOW, available_at=NOW, source='CONTROLLED')
        s.active.append(orphan)  # Simulated process death before catalog commit.
        assert s._index_segment(s._source(s.active_name), s.active_name) == 2
        assert s.get(orphan.id) is not None
        s.catalog.execute('INSERT INTO records VALUES(?,?,?,?,?,?,?)',
                          ('fixture-z', 'Record', NOW.isoformat(), NOW.isoformat(), 'bad', s.active_name, -1))
        s.catalog.commit()
        with pytest.raises(ValueError, match='missing archive records'):
            s._index_segment(s._source(s.active_name), s.active_name)
    finally:
        s.close()


def test_readonly_audit_resumes_and_detects_corruption(tmp_path):
    s = store(tmp_path / 'events.sqlite')
    for i in range(25):
        s.append(Record(id=f'fixture-{i:04}', timestamp=NOW, available_at=NOW, source='CONTROLLED'))
    s.maintain()
    s.close()
    first = audit(tmp_path, max_segments=1)
    assert first['status'] == 'range_verified' and len(first['segments']) == 1
    assert first['segments'][0]['status'] == 'verified'
    second = audit(tmp_path, after=first['next_after'], max_segments=64)
    assert second['status'] == 'range_verified' and second['range_complete']
    assert first['records_verified'] + second['records_verified'] == 25
    assert not first['originals_modified'] and not first['admission_authority']
    raw = tmp_path / 'events-segments' / first['next_after']
    with raw.open('r+b') as f:
        f.seek(100)
        f.write(b'CONTROLLED-CORRUPTION')
    assert audit(tmp_path)['status'] == 'failed'


def test_allocator_reclaim_is_thresholded_throttled_and_never_collects_objects(monkeypatch):
    from neraium_poly.data import memory_reserve as m
    calls = []
    class Function:
        def __call__(self, pad):
            calls.append(pad)
            return 1
    class Lib:
        malloc_trim = Function()
    monkeypatch.setattr(m, 'allocator_snapshot', lambda: {'status': 'available', 'fordblks': 128 * 1024**2,
                                                        'uordblks': 1024**2})
    monkeypatch.setattr(m.ctypes, 'CDLL', lambda *_: Lib())
    clock = [0]
    r = AllocatorReserve(clock=lambda: clock[0])
    assert r.release()['pages_released']
    assert r.release()['attempts'] == 1 and calls == [0]
    clock[0] = 61
    assert r.release()['attempts'] == 2
    monkeypatch.setattr(m, 'allocator_snapshot', lambda: {'status': 'available', 'fordblks': 10, 'uordblks': 100})
    clock[0] = 122
    assert r.release()['status'] == 'not_required'
    assert calls == [0, 0]


@pytest.mark.parametrize('error,boundary', [(httpx.ConnectError, 'loopback_producer_unreachable'),
    (httpx.ReadTimeout, 'loopback_producer_timeout')])
async def test_feed_diagnostics_identify_dependency_without_cached_fallback(error, boundary):
    def failed(request):
        raise error('CONTROLLED', request=request)
    client = SharedFeedClient(client=httpx.AsyncClient(transport=httpx.MockTransport(failed)))
    try:
        with pytest.raises(error):
            await client.read()
        assert client.status()['failure_boundary'] == boundary
        assert client.status()['failures'] == 1
        assert not client.status()['trading_authority']
    finally:
        await client.close()


async def test_loopback_feed_never_uses_environment_proxy(now, monkeypatch):
    monkeypatch.setenv('HTTP_PROXY', 'http://127.0.0.1:1')
    monkeypatch.setenv('ALL_PROXY', 'http://127.0.0.1:1')
    monkeypatch.setenv('NO_PROXY', '')
    expected = frame(now)
    body = expected.model_dump_json().encode()
    async def serve(reader, writer):
        await reader.readuntil(b'\r\n\r\n')
        writer.write(b'HTTP/1.1 200 OK\r\nConnection: close\r\nContent-Length: '
                     + str(len(body)).encode() + b'\r\n\r\n' + body)
        await writer.drain()
        writer.close()
        await writer.wait_closed()
    server = await asyncio.start_server(serve, '127.0.0.1', 0)
    port = server.sockets[0].getsockname()[1]
    client = SharedFeedClient(f'http://127.0.0.1:{port}/api/market-frame')
    try:
        async with asyncio.timeout(5):
            result = await client.read(now)
        assert result == expected
        assert client.status()['status'] == 'ok'
    finally:
        await client.close()
        server.close()
        await server.wait_closed()


async def test_cancelled_full_queue_preserves_charge_and_shutdown_accounting(feed, now):
    feed._queue = asyncio.Queue(maxsize=1)
    task = asyncio.create_task(feed._receive(Socket([json.dumps([full(now)] * 3)])))
    for _ in range(100):
        if feed.metrics()['queue_backpressure_waits']:
            break
        await asyncio.sleep(.001)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    assert feed._queue.qsize() == 1
    assert feed._queued_bytes > 0
    feed._clear_queue()
    assert feed._queued_bytes == 0 and feed._queue.empty()


async def test_sustained_slow_consumer_burst_is_bounded_and_lossless(feed, now):
    feed._queue = asyncio.Queue(maxsize=4)
    received = []
    frames = [json.dumps([full(now)] * 20) for _ in range(4)]
    async def slow(book):
        await asyncio.sleep(.001)
        received.append(book.id)
    consumer = asyncio.create_task(feed._consume(slow))
    receiver = asyncio.create_task(feed._receive(Socket(frames)))
    try:
        async with asyncio.timeout(5):
            while len(received) < 80:
                await asyncio.sleep(.005)
        m = feed.metrics()
        assert len(received) == 80 and m['queue_peak_depth'] <= 4
        assert m['queue_retained_bytes'] == 0 and m['queue_peak_bytes'] <= feed.queue_bytes
        assert m['queue_backpressure_waits'] > 0 and m['queue_backpressure_seconds'] > 0
        assert m['queue_overflows'] == 0 and m['consumer_events'] == 80
    finally:
        receiver.cancel()
        consumer.cancel()
        await asyncio.gather(receiver, consumer, return_exceptions=True)


async def test_stalled_consumer_invalidates_cache_and_drains_all_tasks(feed, now, market):
    feed.queue_size = 1
    feed.queue_put_timeout = .03
    feed.max_reconnects = 0
    socket = Socket([json.dumps([full(now)] * 8)])
    feed.connector = lambda *a, **k: socket
    async def stalled(book):
        await asyncio.Event().wait()
    with pytest.raises(StreamGap, match='reconnect budget exhausted'):
        async with asyncio.timeout(2):
            await feed.run_stream([market], stalled)
    m = feed.metrics()
    assert m['last_reconnect_reason'] == 'market queue backpressure timeout'
    assert m['queue_overflows'] == m['queue_backpressure_timeouts'] == m['reconnects'] == 1
    assert not m['ws_connected'] and not feed.latest
    assert feed._queued_bytes == 0 and feed._queue.empty()


async def test_cancelled_native_publisher_drains_write_before_next_research_job():
    started, finish = Event(), Event()
    def native():
        started.set()
        assert finish.wait(5), 'controlled write deadline exceeded'
        return 'persisted'
    r = ExperimentalRuntime.__new__(ExperimentalRuntime)
    r.phase35_native = SimpleNamespace(step=native)
    worker = ResearchWorker()
    following = []
    async def next_job():
        following.append('next')
    first = asyncio.create_task(worker.run(r._publish_phase35_native))
    second = None
    try:
        async with asyncio.timeout(2):
            while not started.is_set():
                await asyncio.sleep(.001)
        first.cancel()
        second = asyncio.create_task(worker.run(next_job))
        await asyncio.sleep(.05)
        assert not first.done() and not following
    finally:
        finish.set()
        await asyncio.gather(first, *([second] if second else []), return_exceptions=True)
        await worker.close()
    assert first.cancelled() and following == ['next']
