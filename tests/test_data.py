import json
import sqlite3
from datetime import timedelta

import httpx
import pytest
from neraium_poly.data import (
    EventStore,
    LifecycleTracker,
    MarketStream,
    PolymarketAdapter,
    assess_book,
    normalize_book,
    normalize_market,
)


def raw_market():
    return {
        "id": "m1",
        "eventId": "e1",
        "question": "Question?",
        "clobTokenIds": '["t1","t2"]',
        "outcomes": '["Yes","No"]',
        "outcomePrices": '["0.4","0.6"]',
        "active": True,
        "closed": False,
        "description": "Rules",
        "resolutionSource": "Oracle",
    }


def test_normalize_legacy_and_v2(now):
    raw = raw_market()
    records = normalize_market(raw, now)
    assert len(records) == 2 and records[0].probability == 0.4
    assert records[0].status == "active"
    raw.update(version="v2", positionIds=["p1", "p2"])
    assert normalize_market(raw, now)[0].token_id == "p1"
    assert normalize_market(raw, now)[0].id == normalize_market(raw, now)[0].id


def test_missing_data_rejected(now):
    raw = raw_market()
    raw.pop("outcomePrices")
    with pytest.raises(ValueError):
        normalize_market(raw, now)
    with pytest.raises(ValueError):
        normalize_book({"bids": [], "asks": []}, "m1", "t1", now)


def test_book_normalization_and_identity(now):
    raw = {
        "asset_id": "t1",
        "timestamp": int(now.timestamp() * 1000),
        "bids": [{"price": ".2", "size": "5"}, {"price": ".3", "size": "6"}],
        "asks": [{"price": ".6", "size": "5"}, {"price": ".5", "size": "6"}],
    }
    book = normalize_book(raw, "m1", "t1", now)
    assert book.bids[0].price == 0.3 and book.asks[0].price == 0.5
    with pytest.raises(ValueError):
        normalize_book(raw, "m1", "wrong", now)
    raw["bids"].append(raw["bids"][0])
    with pytest.raises(ValueError):
        normalize_book(raw, "m1", "t1", now)


def test_stale_future_incomplete_missing_and_spread(book, now):
    assert assess_book(book, now).healthy
    assert assess_book(None, now).reasons == ("missing_book",)
    assert "stale_book" in assess_book(book, now + timedelta(seconds=16)).reasons
    assert "future_data" in assess_book(book, now - timedelta(seconds=1)).reasons
    assert "incomplete_book" in assess_book(book.model_copy(update={"complete": False}), now).reasons
    assert "large_spread" in assess_book(book, now, max_spread=0.001).reasons
    assert "missing_liquidity" in assess_book(book.model_copy(update={"asks": ()}), now).reasons
    assert "wrong_token" in assess_book(book, now, expected_token="x").reasons


def test_lifecycle_no_implicit_settlement(market, now):
    tracker = LifecycleTracker()
    tracker.observe(market)
    assert tracker.tradable("m1", "t1")
    closed = market.model_copy(update={"status": "closed"})
    tracker.observe(closed)
    assert not tracker.tradable("m1", "t1")
    resolved = market.model_copy(update={"status": "resolved"})
    tracker.observe(resolved)
    with pytest.raises(ValueError):
        tracker.observe(market)


def test_replay_append_only_idempotent_and_recovery(tmp_path, market, now):
    path = tmp_path / "events.sqlite"
    store = EventStore(path)
    late = market.model_copy(update={"id": "late", "available_at": now + timedelta(seconds=10)})
    assert store.append(late)
    assert store.append(market)
    assert not store.append(market)
    assert [x["record"]["id"] for x in store.replay()] == [market.id, "late"]
    assert len(store.replay(until=now)) == 1
    with pytest.raises(ValueError):
        store.append(market.model_copy(update={"question": "changed"}))
    with pytest.raises(sqlite3.IntegrityError):
        store.connection.execute("DELETE FROM events")
    store.close()
    reopened = EventStore(path)
    assert reopened.count() == 2
    assert len(reopened.replay(kind="MarketSnapshot")) == 2
    reopened.close()


def test_store_concurrency(tmp_path, market):
    from concurrent.futures import ThreadPoolExecutor

    store = EventStore(tmp_path / "concurrent.sqlite")
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(store.append, [market] * 20))
    assert sum(results) == 1 and store.count() == 1
    store.close()


async def no_sleep(_):
    return None


@pytest.mark.asyncio
async def test_retry_and_pagination(now):
    attempts = []
    delays = []

    async def sleep(delay):
        delays.append(delay)

    def handler(request):
        attempts.append(request)
        if len(attempts) == 1:
            return httpx.Response(429, headers={"Retry-After": "2"})
        if request.url.params["offset"] == "0":
            return httpx.Response(200, json=[raw_market()])
        return httpx.Response(200, json=[])

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = PolymarketAdapter(client, sleep=sleep, clock=lambda: now, min_interval=0)
        markets = await adapter.discover(page_size=1)
    assert len(markets) == 2 and len(attempts) == 3 and 2 in delays


@pytest.mark.asyncio
async def test_retry_budget_fails_closed(now):
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(503))) as client:
        adapter = PolymarketAdapter(client, sleep=no_sleep, retries=2)
        with pytest.raises(httpx.HTTPStatusError):
            await adapter.book("m1", "t1")


@pytest.mark.asyncio
async def test_discovery_records_incomplete_rows(now):
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=[{"id": "bad"}]))
    ) as client:
        adapter = PolymarketAdapter(client, sleep=no_sleep, clock=lambda: now)
        assert await adapter.discover() == []
        assert len(adapter.errors) == 1


@pytest.mark.asyncio
async def test_history_is_available_only_at_collection(now):
    old = now - timedelta(days=1)
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json={"history": [{"t": int(old.timestamp()), "p": 0.5}]})
        )
    ) as client:
        adapter = PolymarketAdapter(client, sleep=no_sleep, clock=lambda: now)
        rows = await adapter.history("m1", "t1", old - timedelta(seconds=1), now)
    assert rows[0].timestamp == old and rows[0].available_at == now


@pytest.mark.asyncio
async def test_v2_trades_use_condition_and_current_fields(now):
    def handler(request):
        assert request.url.params["condition"] == "0xcondition"
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "token_id": "t1",
                        "timestamp": int(now.timestamp()),
                        "side": "BUY",
                        "price": 0.4,
                        "size": 3,
                        "transaction_hash": "tx",
                    }
                ],
                "pagination": {"next_cursor": None},
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = PolymarketAdapter(client, sleep=no_sleep, clock=lambda: now)
        rows = await adapter.trades("0xcondition")
    assert rows[0].token_id == "t1" and rows[0].transaction_hash == "tx"


class FakeSocket:
    def __init__(self, messages):
        self.messages = iter(messages)
        self.sent = []

    async def send(self, message):
        self.sent.append(message)

    async def recv(self):
        try:
            value = next(self.messages)
        except StopIteration:
            raise ConnectionError("disconnected") from None
        if isinstance(value, Exception):
            raise value
        return value

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False


@pytest.mark.asyncio
async def test_disconnect_resnapshots_and_exhaustion(book):
    class Adapter:
        calls = 0

        async def book(self, market, token):
            self.calls += 1
            return book

    adapter = Adapter()
    stream = MarketStream(
        adapter, {"t1": "m1"}, connector=lambda *a, **k: FakeSocket([]), sleep=no_sleep, max_reconnects=1
    )
    received = []
    with pytest.raises(ConnectionError, match="budget"):
        async for snapshot in stream.snapshots():
            received.append(snapshot)
    assert len(received) == 2 and adapter.calls == 2
    assert not stream.connected and stream.latest == {}


@pytest.mark.asyncio
async def test_incremental_change_causes_full_refresh(book):
    class Adapter:
        calls = 0

        async def book(self, market, token):
            self.calls += 1
            return book

    adapter = Adapter()
    socket = FakeSocket([json.dumps({"event_type": "price_change", "price_changes": [{"asset_id": "t1"}]})])
    stream = MarketStream(
        adapter, {"t1": "m1"}, connector=lambda *a, **k: socket, sleep=no_sleep, max_reconnects=0
    )
    received = []
    with pytest.raises(ConnectionError):
        async for snapshot in stream.snapshots():
            received.append(snapshot)
    assert adapter.calls == 2 and len(received) == 2
    assert json.loads(socket.sent[0])["assets_ids"] == ["t1"]


@pytest.mark.asyncio
async def test_stream_cancel_clears_state(book):
    class Adapter:
        async def book(self, *_):
            return book

    stream = MarketStream(Adapter(), {"t1": "m1"}, connector=lambda *a, **k: FakeSocket([]))
    generator = stream.snapshots()
    assert await anext(generator) == book
    assert stream.connected
    await generator.aclose()
    assert not stream.connected and stream.latest == {}


@pytest.mark.asyncio
async def test_stream_full_book_frame(book, now):
    class Adapter:
        clock = staticmethod(lambda: now)

        async def book(self, *_):
            return book

    raw = {
        "event_type": "book",
        "asset_id": "t1",
        "timestamp": int(now.timestamp() * 1000),
        "bids": [{"price": ".35", "size": "7"}],
        "asks": [{"price": ".41", "size": "9"}],
    }
    stream = MarketStream(
        Adapter(),
        {"t1": "m1"},
        connector=lambda *a, **k: FakeSocket([json.dumps(raw)]),
        sleep=no_sleep,
        max_reconnects=0,
    )
    records = []
    with pytest.raises(ConnectionError):
        async for record in stream.snapshots():
            records.append(record)
    assert len(records) == 2 and records[-1].asks[0].price == 0.41


def test_store_separate_connections_idempotent(tmp_path, market):
    from concurrent.futures import ThreadPoolExecutor

    path = tmp_path / "shared.sqlite"
    stores = [EventStore(path) for _ in range(4)]
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda store: store.append(market), stores))
    assert sum(results) == 1
    for store in stores:
        store.close()
