"""Deterministic synthetic transport fixtures, never real profitability evidence."""

import asyncio
import json
from datetime import timedelta

import httpx
import pytest
from neraium_poly.contracts import OrderBookSnapshot
from neraium_poly.data.connectivity import ConcurrentPublicAdapter, CoverageFeed, StreamGap
from neraium_poly.data.operational import OperationalPolymarketAdapter
from neraium_poly.data.polymarket import GAMMA
from neraium_poly.data.stream import MARKET_WS


def raw_market(i):
    return {
        "id": str(i),
        "events": [{"id": str(i // 2)}],
        "question": f"Market{i}?",
        "clobTokenIds": [f"t{i}", f"n{i}"],
        "outcomes": ["Yes", "No"],
        "outcomePrices": [0.4, 0.6],
        "active": True,
        "closed": False,
        "enableOrderBook": True,
        "acceptingOrders": True,
        "description": "Test rules",
        "resolutionSource": "https://test.example/oracle",
    }


def full(now, token="t1", **extra):
    return {
        "event_type": "book",
        "asset_id": token,
        "timestamp": str(int(now.timestamp() * 1000)),
        "bids": [{"price": ".39", "size": "100"}],
        "asks": [{"price": ".4", "size": "100"}],
        **extra,
    }


def delta(now, changes):
    return {
        "event_type": "price_change",
        "timestamp": str(int(now.timestamp() * 1000)),
        "price_changes": changes,
    }


@pytest.fixture
async def feed(now, market):
    async def handler(request):
        return httpx.Response(200, json={k: v for k, v in full(now).items() if k != "event_type"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = OperationalPolymarketAdapter(client=client, clock=lambda: now, min_interval=0)
    value = CoverageFeed(adapter, rate=20)
    value.set_markets([market])
    yield value
    await value.close()
    await client.aclose()


async def test_ranked_bounded_discovery_hundreds_and_rotation(now):
    queries = []

    async def handler(request):
        queries.append(dict(request.url.params))
        offset = int(request.url.params["offset"])
        limit = int(request.url.params["limit"])
        return httpx.Response(200, json=[raw_market(i) for i in range(offset, offset + limit)])

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = OperationalPolymarketAdapter(client=client, clock=lambda: now)
    f = CoverageFeed(adapter, rate=20)
    try:
        result = await f.discover(max_markets=200, page_size=100, max_pages=2)
        assert len(result.markets) == 400 and result.scanned_count == 200
        assert all(q["order"] == "volume24hr" and q["ascending"] == "false" for q in queries)
        assert result.next_offset == 200
        next_batch = await f.discover(max_markets=10, page_size=10, max_pages=1)
        assert next_batch.markets[0].market_id == "200"
    finally:
        await f.close()
        await client.aclose()


async def test_concurrent_requests_release_limiter_while_network_waits():
    inflight = 0
    peak = 0

    async def handler(request):
        nonlocal inflight, peak
        inflight += 1
        peak = max(peak, inflight)
        await asyncio.sleep(0.12)
        inflight -= 1
        return httpx.Response(200, json=[])

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = ConcurrentPublicAdapter(client=client, concurrency=3, rate=20)
    try:
        await asyncio.gather(*(adapter._get(GAMMA, "/markets") for _ in range(5)))
        assert 1 < peak <= 3 and adapter.peak_inflight == peak
    finally:
        await client.aclose()


async def test_rate_limit_backoff_and_bounded_retry():
    responses = iter([429, 503, 200])
    sleeps = []

    async def sleep(seconds):
        sleeps.append(seconds)

    async def handler(request):
        return httpx.Response(next(responses), json=[], headers={"Retry-After": "2"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    a = ConcurrentPublicAdapter(client=client, sleep=sleep, rate=20)
    try:
        assert await a._get(GAMMA, "/markets") == []
        assert a.rate_limits == 1 and max(sleeps) >= 2
    finally:
        await client.aclose()


async def test_unapproved_origin_rejects():
    a = ConcurrentPublicAdapter()
    try:
        with pytest.raises(ValueError):
            await a._get("https://foreign.example", "/markets")
    finally:
        await a.close()


async def test_native_full_book_has_websocket_provenance(feed, now):
    result = await feed.handle(full(now))
    assert len(result) == 1 and result[0].source == MARKET_WS
    assert feed.metrics()["native_book_frames"] == 1 and feed.metrics()["rest_books"] == 0


async def test_level_replacement_zero_removal_and_multi_level_atomicity(feed, now):
    await feed.handle(full(now))
    result = await feed.handle(
        delta(
            now,
            [
                {"asset_id": "t1", "side": "BUY", "price": ".39", "size": "0"},
                {"asset_id": "t1", "side": "BUY", "price": ".38", "size": "12"},
                {"asset_id": "t1", "side": "SELL", "price": ".4", "size": "7"},
            ],
        )
    )
    assert result[0].bids[0].price == 0.38 and result[0].asks[0].size == 7
    assert result[0].bids[0].size == 12


async def test_camelcase_envelope(feed, now):
    event = {"topic": "market", "type": "book", "payload": {**full(now), "assetId": "t1"}}
    assert await feed.handle(event)
    result = await feed.handle(
        {
            "topic": "market",
            "type": "price_change",
            "payload": {
                "timestamp": str(int(now.timestamp() * 1000)),
                "priceChanges": [
                    {
                        "assetId": "t1",
                        "side": "BUY",
                        "price": ".39",
                        "size": "3",
                        "bestBid": ".39",
                        "bestAsk": ".4",
                    }
                ],
            },
        }
    )
    assert result[0].bids[0].size == 3


async def test_out_of_order_never_regresses_known_state(feed, now):
    await feed.handle(full(now))
    assert await feed.handle(full(now - timedelta(seconds=1))) == []
    assert (
        await feed.handle(
            delta(
                now - timedelta(seconds=1), [{"asset_id": "t1", "side": "BUY", "price": ".39", "size": "1"}]
            )
        )
        == []
    )
    assert feed.latest["t1"].bids[0].size == 100
    assert feed.metrics()["out_of_order"] == 2


@pytest.mark.parametrize(
    "update",
    [
        {"side": "INVALID", "price": ".39", "size": "4"},
        {"side": "BUY", "price": "nan", "size": "4"},
        {"side": "BUY", "price": ".39", "size": "-1"},
        {"side": "BUY", "price": ".41", "size": "1"},
    ],
)
async def test_bad_delta_invalidates_and_refreshes_only_target(feed, now, update):
    await feed.handle(full(now))
    received = await feed.handle(delta(now, [{"asset_id": "t1", **update}]))
    assert received and received[0].source == "https://clob.polymarket.com"
    assert feed.metrics()["gaps"] == 1 and feed.metrics()["rest_books"] == 1


async def test_missing_baseline_and_top_disagreement_resnapshot_target(feed, now):
    result = await feed.handle(delta(now, [{"asset_id": "t1", "side": "BUY", "price": ".39", "size": "4"}]))
    assert result and feed.metrics()["rest_books"] == 1
    result = await feed.handle(
        delta(now, [{"asset_id": "t1", "side": "BUY", "price": ".39", "size": "4", "best_bid": ".35"}])
    )
    assert result and feed.metrics()["rest_books"] == 2


async def test_detected_timestamp_gap_requires_resnapshot(feed, now):
    old = now - timedelta(seconds=40)
    await feed.handle(full(old))
    await feed.handle(delta(now, [{"asset_id": "t1", "side": "BUY", "price": ".39", "size": "4"}]))
    assert feed.metrics()["gaps"] == 1 and feed.metrics()["rest_books"] == 1


async def test_unknown_asset_ignored_and_cap_rejected(feed, now, market):
    assert not await feed.handle(full(now, token="foreign"))
    feed.max_tokens = 1
    with pytest.raises(ValueError):
        feed.set_markets([market, market.model_copy(update={"token_id": "t2", "market_id": "m2"})])


async def test_full_invalid_future_book_withheld(feed, now):
    assert not await feed.handle(full(now + timedelta(seconds=1)))
    assert "t1" not in feed.latest and feed.metrics()["invalid_frames"] == 1


async def test_bounded_rest_selection_and_identity(feed, market):
    result = await feed.books([market], limit=1)
    assert len(result) == 1 and isinstance(result[0], OrderBookSnapshot)
    assert feed.metrics()["rest_books"] == 1


class Socket:
    def __init__(self, messages):
        self.messages = iter(messages)
        self.sent = []

    async def send(self, message):
        self.sent.append(message)

    async def recv(self):
        await asyncio.sleep(0)
        value = next(self.messages, None)
        if value is None:
            await asyncio.sleep(60)
        return value

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


async def test_native_stream_delivery_and_cancel_clears_cache(now, market):
    socket = Socket([json.dumps(full(now))])
    f = CoverageFeed(OperationalPolymarketAdapter(clock=lambda: now), connector=lambda *a, **k: socket)
    received = []
    try:
        task = f.start_stream([market], received.append)
        for _ in range(30):
            if received:
                break
            await asyncio.sleep(0.01)
        assert received and f.connected and f.metrics()["native_book_frames"] == 1
        assert json.loads(socket.sent[0])["assets_ids"] == ["t1"]
        await f.stop_stream()
        assert not f.connected and not f.latest and task.done()
    finally:
        await f.close()


async def test_queue_overflow_invalidates_state(feed, now):
    await feed.handle(full(now))
    feed._queue = asyncio.Queue(maxsize=1)
    socket = Socket([json.dumps([full(now), full(now)])])
    with pytest.raises(StreamGap):
        await feed._receive(socket)
    assert not feed.latest and feed.metrics()["queue_overflows"] == 1


async def test_malformed_frame_reconnect_budget_withholds_cache(now, market):
    socket = Socket(["not-json"])
    f = CoverageFeed(
        OperationalPolymarketAdapter(clock=lambda: now), connector=lambda *a, **k: socket, max_reconnects=0
    )
    try:
        with pytest.raises(StreamGap, match="reconnect budget"):
            await f.run_stream([market], lambda b: None)
        assert not f.connected and not f.latest and f.metrics()["reconnects"] == 1
    finally:
        await f.close()


async def test_failed_consumer_is_a_detected_gap(now, market):
    socket = Socket([json.dumps(full(now))])
    f = CoverageFeed(
        OperationalPolymarketAdapter(clock=lambda: now), connector=lambda *a, **k: socket, max_reconnects=0
    )

    def broken(book):
        raise RuntimeError("controlled callback failure")

    try:
        with pytest.raises(StreamGap):
            await f.run_stream([market], broken)
        assert not f.latest and f.metrics()["callbacks_failed"] == 1
    finally:
        await f.close()


async def test_tick_change_cannot_keep_old_executable_state(feed, now):
    await feed.handle(full(now))
    await feed.handle({"event_type": "tick_size_change", "asset_id": "t1"})
    assert "t1" not in feed.latest


async def test_unavailable_rest_does_not_manufacture_liquidity(now, market):
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(404, json={})))
    f = CoverageFeed(OperationalPolymarketAdapter(client=client, clock=lambda: now))
    try:
        assert await f.books([market]) == []
        assert not f.latest
    finally:
        await f.close()
        await client.aclose()


async def test_429_retry_after_applies_to_all_following_requests(monkeypatch):
    import neraium_poly.data.connectivity as module

    clock = [100.0]
    starts = []

    async def sleep(delay):
        clock[0] += delay

    monkeypatch.setattr(module, "monotonic", lambda: clock[0])
    responses = iter([429, 200])

    async def handler(request):
        starts.append(clock[0])
        return httpx.Response(next(responses), json=[], headers={"Retry-After": "5"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = ConcurrentPublicAdapter(client=client, sleep=sleep, retries=1, rate=20)
    try:
        with pytest.raises(httpx.HTTPStatusError):
            await adapter._get(GAMMA, "/markets")
        assert adapter._next_start >= 105
        assert await adapter._get(GAMMA, "/markets") == []
        assert starts[1] - starts[0] >= 5
    finally:
        await client.aclose()


async def test_global_cooldown_extension_while_another_request_waits(monkeypatch):
    import neraium_poly.data.connectivity as module

    clock = [100.0]
    calls = 0
    monkeypatch.setattr(module, "monotonic", lambda: clock[0])
    adapter = None

    async def sleep(delay):
        nonlocal calls
        calls += 1
        clock[0] += delay
        if calls == 1:
            adapter._next_start = clock[0] + 5

    starts = []

    async def handler(request):
        starts.append(clock[0])
        return httpx.Response(200, json=[])

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = ConcurrentPublicAdapter(client=client, sleep=sleep, rate=20)
    adapter._next_start = 101
    try:
        await adapter._get(GAMMA, "/markets")
        assert starts == [106] and calls == 2
    finally:
        await client.aclose()


@pytest.mark.parametrize("payload", [{"assets_ids": ["t1"]}, {"conditionId": "unknown-condition"}])
async def test_resolution_scope_invalidates_and_withholds_closed_tokens(feed, now, market, payload):
    await feed.handle(full(now))
    await feed.handle({"event_type": "market_resolved", **payload})
    assert not feed.latest
    assert not await feed.handle(full(now))
    assert not await feed.books([market])
    assert feed.metrics()["resolved_tokens_withheld"] == 1


async def test_tick_change_without_asset_identifier_invalidates_all(feed, now):
    await feed.handle(full(now))
    await feed.handle({"event_type": "tick_size_change", "conditionId": "unknown-condition"})
    assert not feed.latest


async def test_rest_resnapshot_cannot_regress_newer_native_state(feed, now):
    later = now + timedelta(seconds=1)

    async def stale_response(market_id, token_id):
        # A newer native frame arrives while REST was awaiting network IO.
        feed.latest[token_id] = OrderBookSnapshot.model_validate(
            {**(await feed.handle(full(now)))[0].model_dump(), "timestamp": later, "available_at": later}
        )
        return OrderBookSnapshot.model_validate(
            {**feed.latest[token_id].model_dump(), "timestamp": now, "available_at": now}
        )

    feed.adapter.book = stale_response
    result = await feed._resnapshot("t1")
    assert result.timestamp == later and feed.latest["t1"].timestamp == later
    assert feed.metrics()["out_of_order"] == 1
