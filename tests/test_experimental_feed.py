"""Controlled transport tests; not evidence of actual market operation."""

import hashlib
from datetime import timedelta
from threading import RLock
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient
from neraium_poly.contracts import MarketSnapshot, OrderBookSnapshot, PriceLevel
from neraium_poly.experimental.contracts import SharedMarketFrame
from neraium_poly.experimental.feed import SharedFeedClient, market_frame
from neraium_poly.ops.api import create_app


def frame(now):
    market = MarketSnapshot(
        timestamp=now,
        available_at=now,
        source="https://gamma-api.polymarket.com",
        market_id="controlled",
        event_id="test",
        token_id="controlled-token",
        question="Controlled fixture",
        probability=0.4,
    )
    book = OrderBookSnapshot(
        timestamp=now,
        available_at=now,
        source="https://clob.polymarket.com",
        market_id=market.market_id,
        token_id=market.token_id,
        bids=(PriceLevel(price=0.39, size=100),),
        asks=(PriceLevel(price=0.4, size=100),),
    )
    return SharedMarketFrame(
        timestamp=now,
        available_at=now,
        source="neraium-poly/public-market-frame/v1",
        producer_health={"status": "ok", "live_trading_enabled": False},
        markets=(market,),
        books=(book,),
    )


async def test_full_levels_and_source_times_survive_readonly_transport(now):
    f = frame(now)
    client = SharedFeedClient(
        client=httpx.AsyncClient(
            transport=httpx.MockTransport(lambda r: httpx.Response(200, json=f.model_dump(mode="json")))
        )
    )
    try:
        assert await client.read(now) == f
    finally:
        await client.close()


@pytest.mark.parametrize("change", ["old", "future", "synthetic", "degraded", "identity", "duplicate"])
async def test_invalid_shared_observations_fail_closed(now, change):
    f = frame(now)
    data = f.model_dump(mode="json")
    if change == "old":
        data["timestamp"] = data["available_at"] = (now - timedelta(seconds=16)).isoformat()
    if change == "future":
        data["timestamp"] = data["available_at"] = (now + timedelta(seconds=1)).isoformat()
    if change == "synthetic":
        data["books"][0]["source"] = "synthetic-test"
    if change == "degraded":
        data["producer_health"]["status"] = "degraded"
    if change == "identity":
        data["books"][0]["market_id"] = "other"
    if change == "duplicate":
        data["books"] *= 2
    client = SharedFeedClient(
        client=httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=data)))
    )
    try:
        with pytest.raises(ValueError):
            await client.read(now)
    finally:
        await client.close()


async def test_response_budget_and_remote_urls_reject(now):
    with pytest.raises(ValueError):
        SharedFeedClient("https://external.example/api/market-frame")
    client = SharedFeedClient(
        max_bytes=1024,
        client=httpx.AsyncClient(
            transport=httpx.MockTransport(lambda r: httpx.Response(200, content=b"x" * 2048))
        ),
    )
    try:
        with pytest.raises(ValueError, match="budget"):
            await client.read(now)
    finally:
        await client.close()


def test_export_never_reads_or_mutates_certified_account(now):
    f = frame(now)

    class NoAccount:
        def __getattribute__(self, name):
            raise AssertionError("certified account accessed")

    runtime = SimpleNamespace(
        _lock=RLock(),
        _current_books=lambda: {b.token_id: b for b in f.books},
        markets={m.token_id: m for m in f.markets},
        clock=lambda: now,
        last_success=now,
        last_error=None,
        fees={},
        relationships={},
        coverage=None,
        risk=NoAccount(),
    )
    before = hashlib.sha256(f.model_dump_json().encode()).hexdigest()
    result = market_frame(runtime)
    assert result.books == f.books and result.markets == f.markets
    assert hashlib.sha256(f.model_dump_json().encode()).hexdigest() == before


def test_synthetic_runtime_cannot_export_live_frame():
    assert TestClient(create_app()).get("/api/market-frame").status_code == 404
