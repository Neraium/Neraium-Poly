"""Bounded timing for the existing loopback market-frame request path."""

import json
import logging
import re
from contextvars import ContextVar
from datetime import UTC, datetime
from time import monotonic
from uuid import uuid4

TRACE_HEADER = b"x-neraium-frame-request"
_REQUEST_ID = re.compile(rb"[a-f0-9]{32}")
_producer = ContextVar("market_frame_producer_trace", default=None)
_log = logging.getLogger(__name__)
_HTTP_EVENTS = {
    ("connection", "connect_tcp"),
    ("http11", "send_request_headers"),
    ("http11", "receive_response_headers"),
    ("http11", "receive_response_body"),
}
_HTTP_STATES = {"started", "complete", "failed"}


class FrameRequestTiming:
    """Client-side stages, including failed reads with no response/frame."""

    def __init__(self):
        self.request_id = uuid4().hex
        self.started = monotonic()
        self.marks = {}
        self.failure_stage = None

    def mark(self, name):
        self.marks.setdefault(name, round(monotonic() - self.started, 6))

    def http_event(self, name, _info):
        parts = name.split(".")
        if len(parts) != 3 or tuple(parts[:2]) not in _HTTP_EVENTS or parts[2] not in _HTTP_STATES:
            return
        self.mark(name)
        if parts[2] == "failed":
            self.failure_stage = parts[1]

    def receipt(self):
        return {
            "request_id": self.request_id,
            "http_stage_seconds": dict(self.marks),
            "http_failure_stage": self.failure_stage,
        }


def producer_mark(name):
    trace = _producer.get()
    if trace is not None:
        trace["stage_seconds"].setdefault(name, round(monotonic() - trace["started"], 6))


def producer_frame(frame, *, ingestion_age_seconds, has_fresh_books):
    trace = _producer.get()
    if trace is not None:
        producer_mark("frame_built")
        trace.update(
            frame_id=frame.id,
            source_available_at=frame.available_at.isoformat(),
            producer_status=frame.producer_health["status"],
            ingestion_age_seconds=ingestion_age_seconds,
            has_fresh_books=has_fresh_books,
        )


class MarketFrameTimingMiddleware:
    """Correlate tagged requests through ASGI send; leave the response unchanged."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if (
            scope["type"] != "http"
            or scope.get("method") != "GET"
            or scope.get("path") != "/api/market-frame"
        ):
            return await self.app(scope, receive, send)
        request_id = next((v for k, v in scope["headers"] if k == TRACE_HEADER), b"")
        if not _REQUEST_ID.fullmatch(request_id):
            return await self.app(scope, receive, send)
        trace = {
            "request_id": request_id.decode("ascii"),
            "asgi_arrived_at": datetime.now(UTC).isoformat(),
            "started": monotonic(),
            "stage_seconds": {},
        }
        token = _producer.set(trace)

        async def traced_send(message):
            kind = message["type"]
            if kind == "http.response.start":
                trace["http_status"] = message["status"]
                producer_mark("response_start")
            elif kind == "http.response.body":
                producer_mark("first_body")
                if not message.get("more_body"):
                    producer_mark("final_body")
            await send(message)
            if kind == "http.response.body" and not message.get("more_body"):
                producer_mark("final_body_sent")

        try:
            await self.app(scope, receive, traced_send)
        finally:
            producer_mark("asgi_exit")
            _producer.reset(token)
            record = {key: value for key, value in trace.items() if key != "started"}
            record["stage_seconds"] = dict(trace["stage_seconds"])
            _log.info("market_frame_timing %s", json.dumps(record, separators=(",", ":")))
