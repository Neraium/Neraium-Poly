"""Controlled ingestion-memory fixtures; never authentic prices or performance."""
import asyncio
import json

import httpx
import pytest
from neraium_poly.data.connectivity import CoverageFeed, StreamGap, _payload_bytes
from neraium_poly.data.operational import OperationalPolymarketAdapter
from neraium_poly.data.polymarket import normalize_book
from test_connectivity import Socket, delta, full


def adapter(now):
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=full(now))))
    return OperationalPolymarketAdapter(client=client, clock=lambda: now, min_interval=0)


def deep_book(now, count=5, token='t1'):
    return full(now, token=token, bids=[{'price': str(.1 + i*.01), 'size': '1'} for i in range(count)], asks=[])


async def test_decoded_python_budget_rejects_small_wire_payload_before_admission(now, market):
    f = CoverageFeed(adapter(now), queue_bytes=4096)
    f.set_markets([market])
    try:
        await f.handle(full(now))
        payload = deep_book(now, 40)
        wire = json.dumps(payload)
        assert len(wire.encode()) < 4096 < _payload_bytes(json.loads(wire), 65536)
        with pytest.raises(StreamGap, match='queue byte budget'):
            await f._receive(Socket([wire]))
        assert not f.latest and f.metrics()['queue_byte_overflows'] == 1
        assert f.metrics()['queue_retained_bytes'] == 0
    finally:
        await f.close()


async def test_aggregate_bytes_bound_queue_and_stop_releases_retained_events(now, market):
    f = CoverageFeed(adapter(now), queue_bytes=4096)
    f.set_markets([market])
    try:
        payload = full(now, note='x'*2000)
        charge = _payload_bytes(payload, 65536)
        assert charge < 4096 < 2*charge
        with pytest.raises(StreamGap, match='queue byte budget'):
            await f._receive(Socket([json.dumps([payload, payload])]))
        assert f._queue.qsize() == 1
        assert 0 < f.metrics()['queue_retained_bytes'] <= 4096
        await f.stop_stream()
        assert not f._queue.qsize() and not f.metrics()['queue_retained_bytes']
    finally:
        await f.close()


async def test_reconnect_exhaustion_drains_queue_and_bounds_native_socket_buffer(now, market):
    arguments = {}
    payload = full(now, note='x'*2000)
    socket = Socket([json.dumps([payload, payload])])
    def connector(*args, **kwargs):
        arguments.update(kwargs)
        return socket
    f = CoverageFeed(adapter(now), connector=connector, queue_bytes=4096, max_reconnects=0)
    try:
        with pytest.raises(StreamGap, match='reconnect budget'):
            await f.run_stream([market], lambda _: None)
        assert arguments['max_queue'] == 1 and arguments['max_size'] == 16*1024**2
        assert not f.latest and not f.connected
        assert not f._queue.qsize() and f.metrics()['queue_retained_bytes'] == 0
        assert f.metrics()['queue_peak_bytes'] <= 4096
    finally:
        await f.close()


async def test_inflight_consumer_remains_charged_until_callback_cancellation(now, market):
    entered = asyncio.Event()
    block = asyncio.Event()
    async def consume(_):
        entered.set()
        await block.wait()
    socket = Socket([json.dumps(full(now))])
    f = CoverageFeed(adapter(now), connector=lambda *a, **k: socket)
    try:
        f.start_stream([market], consume)
        await asyncio.wait_for(entered.wait(), timeout=1)
        assert f._queue.qsize() == 0 and f.metrics()['queue_retained_bytes'] > 0
        await f.stop_stream()
        assert f.metrics()['queue_retained_bytes'] == 0 and not f.latest
    finally:
        await f.close()


async def test_oversized_full_book_rejects_before_normalization_and_never_truncates(now, market, monkeypatch):
    from neraium_poly.data import connectivity
    f = CoverageFeed(adapter(now), max_book_levels=2)
    f.set_markets([market])
    try:
        assert await f.handle(full(now))
        monkeypatch.setattr(connectivity, 'normalize_book', lambda *a: pytest.fail('must not build oversized book'))
        assert await f.handle(deep_book(now, 3)) == []
        assert not f.latest and f.metrics()['book_level_budget_rejections'] == 1
    finally:
        await f.close()


async def test_global_levels_charge_replacements_not_duplicates_or_other_tokens(now, market):
    f = CoverageFeed(adapter(now), max_book_levels=4, max_cached_levels=4)
    other = market.model_copy(update={'token_id': 't2', 'market_id': 'm2'})
    f.set_markets([market, other])
    try:
        assert await f.handle(full(now))
        assert await f.handle(full(now, token='t2'))
        assert await f.handle(full(now))  # replacement remains two, not four, levels
        assert f.metrics()['cached_book_levels'] == 4
        assert await f.handle(deep_book(now, 3)) == []
        assert 't1' not in f.latest and 't2' in f.latest
        assert f.metrics()['cached_book_levels'] == 2
    finally:
        await f.close()


async def test_oversized_delta_and_rest_cannot_restore_stale_executable_fallback(now, market):
    f = CoverageFeed(adapter(now), max_book_levels=2)
    f.set_markets([market])
    oversized = normalize_book(deep_book(now, 3), market.market_id, market.token_id, now)
    bounded = normalize_book(full(now), market.market_id, market.token_id, now)
    state = [oversized]
    async def rest(*_):return state[0]
    f.adapter.book = rest
    try:
        assert await f.handle(full(now))
        change = delta(now, [{'asset_id':'t1', 'side':'BUY', 'price':'.38', 'size':'1'}])
        assert await f.handle(change) == []
        assert 't1' not in f.latest
        assert await f.execution_book('t1') is None
        assert await f.books([market]) == []
        assert 't1' not in f.latest
        state[0] = bounded
        recovered = await f.execution_book('t1')
        assert recovered == bounded and recovered.timestamp == now
        assert f.metrics()['cached_book_levels'] == 2
    finally:
        await f.close()


@pytest.mark.parametrize('changes', [
    {'queue_bytes':True}, {'queue_bytes':4095}, {'queue_bytes':65*1024**2},
    {'max_book_levels':True}, {'max_book_levels':4, 'max_cached_levels':3},
])
def test_memory_configuration_is_explicit_and_bounded(now, changes):
    # Configuration rejects before creating/owning transport clients.
    with pytest.raises(ValueError, match='bounded coverage'):
        CoverageFeed(**changes)


def test_payload_charge_is_iterative_and_conservative_for_shared_leaves():
    value = 'same'
    for _ in range(1000):value = [value]
    assert _payload_bytes(value, 100_000) > 50_000
    shared = {'a':'x'*1000}
    assert _payload_bytes([shared, shared], 100_000) > 2*_payload_bytes(shared, 100_000)


async def test_idle_receiver_and_consumer_release_previous_decoded_frame(now, market, monkeypatch):
    import weakref

    from neraium_poly.data import connectivity

    class Tracked(dict):
        pass

    references = []
    def decode(_):
        event = Tracked(full(now))
        references.append(weakref.ref(event))
        return [event]

    waiting = asyncio.Event()
    block = asyncio.Event()
    delivered = asyncio.Event()
    class WaitingSocket:
        calls = 0
        async def recv(self):
            self.calls += 1
            if self.calls == 1:return 'CONTROLLED_FRAME'
            waiting.set()
            await block.wait()
        async def send(self, _):pass

    monkeypatch.setattr(connectivity.json, 'loads', decode)
    f = CoverageFeed(adapter(now))
    f.set_markets([market])
    receiver = asyncio.create_task(f._receive(WaitingSocket()))
    consumer = asyncio.create_task(f._consume(lambda _: delivered.set()))
    try:
        await asyncio.wait_for(waiting.wait(), 1)
        await asyncio.wait_for(delivered.wait(), 1)
        await asyncio.sleep(0)
        assert f.metrics()['queue_retained_bytes'] == 0
        assert references[0]() is None
    finally:
        receiver.cancel();consumer.cancel()
        await asyncio.gather(receiver, consumer, return_exceptions=True)
        await f.close()
