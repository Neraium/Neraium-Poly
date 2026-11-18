"""Isolated loopback tests for timing without changing market/evidence semantics."""

import asyncio
import json
import logging
import socket
import time
from datetime import timedelta
from threading import Event, RLock, Thread
from types import SimpleNamespace

import pytest
import uvicorn
from neraium_poly.experimental.feed import market_frame
from neraium_poly.ops.api import create_app
from neraium_poly.research.phase42.dashboard import snapshot
from neraium_poly.research.phase44.reference import ReferenceSampler
from test_experimental_feed import frame


@pytest.mark.parametrize(
    ("message_type", "failed_stage"),
    [
        ("http.response.start", "receive_response_headers"),
        ("http.response.body", "receive_response_body"),
    ],
)
def test_delayed_transport_is_correlated_without_refreshing_original_frame(
    now, caplog, message_type, failed_stage
):
    clock = [now]
    input_frame = frame(now)
    runtime = SimpleNamespace(
        _lock=RLock(),
        _current_books=lambda: {book.token_id: book for book in input_frame.books},
        markets={market.token_id: market for market in input_frame.markets},
        clock=lambda: now,
        last_success=now,
        last_error=None,
        fees={},
        relationships={},
        coverage=None,
    )
    runtime.market_frame = lambda: market_frame(runtime).model_dump(mode="json")
    app = create_app(runtime=runtime)
    release = Event()
    delay_entered = Event()

    async def delayed_app(scope, receive, send):
        async def delayed_send(message):
            if message["type"] == message_type and not delay_entered.is_set():
                delay_entered.set()
                await asyncio.to_thread(release.wait, 8)
            await send(message)

        await app(scope, receive, delayed_send)

    caplog.set_level(logging.INFO, logger="neraium_poly.experimental.feed_trace")
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(delayed_app, lifespan="off", log_config=None))
        thread = Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        thread.start()
        try:
            deadline = time.monotonic() + 5
            while not server.started and time.monotonic() < deadline:
                time.sleep(0.02)
            assert server.started
            sampler = ReferenceSampler(f"http://127.0.0.1:{port}/api/market-frame", clock=lambda: clock[0])
            sampler.observe()
            assert delay_entered.is_set()
            failed = sampler.status()["recent_reads"][-1]
            assert failed["error"].startswith("ReadTimeout:")
            assert failed["http_failure_stage"] == failed_stage
            assert "frame_id" not in failed
            with pytest.raises(ValueError, match="unavailable"):
                sampler.latest()
            release.set()

            sampler.observe()
            accepted, receipt = sampler.latest_with_receipt()
            assert receipt["http_failure_stage"] is None
            assert accepted.available_at == now
            assert accepted.books == input_frame.books
            assert receipt["http_stage_seconds"]["decoded"] >= receipt["http_stage_seconds"]["body_complete"]

            sampler.observe()
            repeated, second = sampler.latest_with_receipt()
            assert repeated.id == accepted.id and repeated.available_at == now
            assert receipt["request_id"] != second["request_id"] != failed["request_id"]
            runtime.research_reference = sampler
            runtime.shadow_research_snapshot = {
                "as_of": now.isoformat(),
                "freshness_trace": {"decision_reads": [receipt], "published_at": now.isoformat()},
            }
            assert snapshot(runtime, now)["status"] == "fresh"
            assert snapshot(runtime, now)["status"] == "fresh"
            assert sampler.attempts == 3

            clock[0] += timedelta(seconds=21)
            assert snapshot(runtime, clock[0])["status"] == "stale"
            sampler.observe()
            assert sampler.status()["status"] == "withheld"
            assert "stale or future" in sampler.status()["last_error"]
            assert sampler.status()["recent_reads"][-1]["source_available_at"] == now.isoformat()
        finally:
            release.set()
            server.should_exit = True
            thread.join(5)

    assert not thread.is_alive()
    producer = {}
    for record in caplog.records:
        if record.name == "neraium_poly.experimental.feed_trace":
            payload = json.loads(record.getMessage().removeprefix("market_frame_timing "))
            producer[payload["request_id"]] = payload
    for request in (failed, receipt):
        span = producer[request["request_id"]]
        assert span["frame_id"] == accepted.id
        assert span["source_available_at"] == now.isoformat()
        stages = span["stage_seconds"]
        assert stages["handler_started"] <= stages["lock_wait_started"] <= stages["lock_acquired"]
        assert stages["lock_acquired"] <= stages["frame_built"] <= stages["handler_returned"]
        assert stages["handler_returned"] <= stages["response_start"] <= stages["first_body"]
