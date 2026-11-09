"""Bounded, public-only liquid-market coverage and causally maintained books.

WebSocket deltas are venue level replacements, not trades. No global exchange
sequence is invented. Disconnects and detectable integrity gaps invalidate state.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import math
import sys
from collections import defaultdict
from collections.abc import Awaitable, Callable, Sequence
from contextlib import suppress
from datetime import datetime
from decimal import Decimal, InvalidOperation
from time import monotonic

import httpx
from websockets.asyncio.client import connect
from websockets.exceptions import WebSocketException

from neraium_poly.contracts import MarketSnapshot, OrderBookSnapshot, PriceLevel

from .operational import DiscoveryBatch, OperationalPolymarketAdapter
from .polymarket import CLOB, GAMMA, normalize_book, normalize_market, stable_id, timestamp
from .quality import assess_book
from .stream import MARKET_WS


class StreamGap(ConnectionError):
    """Unknown continuity is never silently converted to executable liquidity."""


def _payload_bytes(value, limit):
    """Conservative retained Python size; shared JSON leaves may be overcharged.

    Stop once the budget fails rather than constructing another serialization or
    recursively walking an arbitrarily deep JSON document. This is a queue
    admission charge, not an estimate of total process RSS or decoder peak.
    """
    pending, total = [value], 0
    while pending:
        item = pending.pop()
        total += sys.getsizeof(item)
        if total > limit:
            return total
        if isinstance(item, dict):
            for key, child in item.items():
                pending.extend((key, child))
        elif isinstance(item, (list, tuple)):
            pending.extend(item)
    return total


class ConcurrentPublicAdapter(OperationalPolymarketAdapter):
    """Throttle request starts globally; never hold the limiter during network IO."""

    def __init__(self, *args, concurrency: int = 4, rate: float = 8, **kwargs):
        if not 1 <= concurrency <= 16 or not math.isfinite(rate) or not 0 < rate <= 20:
            raise ValueError("bounded public concurrency/rate required")
        kwargs["min_interval"] = 0
        super().__init__(*args, **kwargs)
        self._semaphore = asyncio.Semaphore(concurrency)
        self._rate_lock = asyncio.Lock()
        self._next_start = 0.0
        self.rate = rate
        self.requests = 0
        self.rate_limits = 0
        self.transport_errors = 0
        self.peak_inflight = 0
        self._inflight = 0

    async def _get(self, base: str, path: str, params: dict | None = None):
        # Only the existing public origins and GET requests are exposed.
        if base not in {GAMMA, CLOB, "https://data-api.polymarket.com"} or not path.startswith("/"):
            raise ValueError("unapproved public data origin")
        for attempt in range(self.retries):
            async with self._semaphore:
                async with self._rate_lock:
                    # A 429 response may extend the global start time while a
                    # different request is sleeping here. Recheck before IO.
                    while True:
                        target = self._next_start
                        delay = max(0, target - monotonic())
                        if delay:
                            await self.sleep(delay)
                        if self._next_start > target:
                            continue
                        self._next_start = max(monotonic(), target) + 1 / self.rate
                        break
                self.requests += 1
                self._inflight += 1
                self.peak_inflight = max(self.peak_inflight, self._inflight)
                try:
                    response = await self.client.get(base + path, params=params)
                except httpx.TransportError:
                    self.transport_errors += 1
                    if attempt == self.retries - 1:
                        raise
                    response = None
                finally:
                    self._inflight -= 1
            if response is not None and response.status_code not in {429, 500, 502, 503, 504}:
                response.raise_for_status()
                return response.json()
            delay = min(30, 2**attempt)
            if response is not None:
                with suppress(ValueError):
                    retry_after = float(response.headers.get("Retry-After", "0"))
                    if math.isfinite(retry_after):
                        delay = max(delay, min(60, retry_after))
                if response.status_code == 429:
                    self.rate_limits += 1
                    # Single-loop atomic update is intentional: no await or
                    # limiter lock can let another sleeping waiter miss it.
                    self._next_start = max(self._next_start, monotonic() + delay)
                if attempt == self.retries - 1:
                    response.raise_for_status()
            await self.sleep(delay)
        raise RuntimeError("public request retry budget exhausted")


class CoverageFeed:
    def __init__(
        self,
        adapter: OperationalPolymarketAdapter | None = None,
        *,
        max_tokens: int = 800,
        concurrency: int = 4,
        rate: float = 8,
        queue_size: int = 512,
        queue_bytes: int = 8 * 1024**2,
        max_book_levels: int = 4096,
        max_cached_levels: int = 100_000,
        connector=connect,
        max_reconnects: int = 8,
        max_gap_seconds: float = 30,
    ):
        if (
            not 1 <= max_tokens <= 2000
            or not 1 <= queue_size <= 10000
            or max_reconnects < 0
            or max_gap_seconds <= 0
            or type(queue_bytes) is not int or not 4096 <= queue_bytes <= 64 * 1024**2
            or type(max_book_levels) is not int or not 2 <= max_book_levels <= 20_000
            or type(max_cached_levels) is not int or not max_book_levels <= max_cached_levels <= 1_000_000
        ):
            raise ValueError("bounded coverage and recovery configuration required")
        self._original = adapter or OperationalPolymarketAdapter()
        self.adapter = ConcurrentPublicAdapter(
            client=self._original.client,
            clock=self._original.clock,
            retries=self._original.retries,
            sleep=self._original.sleep,
            concurrency=concurrency,
            rate=rate,
        )
        self.adapter.discovery_offset = getattr(self._original, "discovery_offset", 0)
        self.max_tokens, self.queue_size = max_tokens, queue_size
        self.queue_bytes = queue_bytes
        self.queue_put_timeout = 1.0
        self.max_book_levels, self.max_cached_levels = max_book_levels, max_cached_levels
        self._queued_bytes = 0
        self.connector, self.max_reconnects, self.max_gap_seconds = connector, max_reconnects, max_gap_seconds
        self.latest: dict[str, OrderBookSnapshot] = {}
        self._markets: dict[str, MarketSnapshot] = {}
        self._resolved_tokens: set[str] = set()
        self._gap_watermarks: dict[str, datetime] = {}
        self._queue = asyncio.Queue(maxsize=queue_size)
        self._task = None
        self._refresh_tasks = {}
        self._generation = 0
        self._on_book = None
        self.connected = False
        self._closed = False
        self._metrics = {
            k: 0
            for k in (
                "messages",
                "native_book_frames",
                "native_delta_frames",
                "native_books_delivered",
                "rest_books",
                "reconnects",
                "gaps",
                "out_of_order",
                "queue_overflows",
                "queue_backpressure_waits",
                "queue_backpressure_timeouts",
                "queue_byte_overflows",
                "queue_peak_bytes",
                "largest_frame_bytes",
                "oversized_frames",
                "book_level_budget_rejections",
                "invalid_frames",
                "callbacks_failed",
                "invalidations",
                "resnapshot_failures",
                "gap_missing_baseline",
                "gap_source_time",
                "gap_top_integrity",
                "gap_invalid_delta",
                "stale_recovery_baselines",
            )
        }
        self.last_message_at = None
        self.last_gap_at = None
        self.last_reconnect_reason = None
        self._cursor = 0

    def metrics(self) -> dict:
        now = self.adapter.clock()
        return {
            **self._metrics,
            "ws_connected": self.connected,
            "subscribed_tokens": len(self._markets),
            "cached_books": len(self.latest),
            "resolved_tokens_withheld": len(self._resolved_tokens),
            "gap_tokens_withheld": sum(token not in self.latest for token in self._gap_watermarks),
            "fresh_books": sum(assess_book(b, now).healthy for b in self.latest.values()),
            "queue_depth": self._queue.qsize(),
            "queue_retained_bytes": self._queued_bytes,
            "queue_budget_bytes": self.queue_bytes,
            "queue_byte_scope": "conservative Python payload charge including in-flight consumer; decoder/socket buffers separate",
            "last_reconnect_reason": self.last_reconnect_reason,
            "websocket_max_queue": 1,
            "websocket_max_frame_bytes": 16 * 1024**2,
            "cached_book_levels": sum(len(b.bids) + len(b.asks) for b in self.latest.values()),
            "max_cached_book_levels": self.max_cached_levels,
            "max_levels_per_book": self.max_book_levels,
            "resnapshot_pending": len(self._refresh_tasks),
            "connection_generation": self._generation,
            "last_message_at": self.last_message_at.isoformat() if self.last_message_at else None,
            "last_gap_at": self.last_gap_at.isoformat() if self.last_gap_at else None,
            "http_requests": self.adapter.requests,
            "http_rate_limits": self.adapter.rate_limits,
            "http_peak_inflight": self.adapter.peak_inflight,
            "rate_requests_per_second": self.adapter.rate,
        }

    async def discover(
        self, *, max_markets: int = 200, page_size: int = 100, max_pages: int = 4
    ) -> DiscoveryBatch:
        if not 1 <= max_markets <= 1000 or not 1 <= page_size <= 200 or not 1 <= max_pages <= 20:
            raise ValueError("bounded liquid discovery required")
        selected, scanned, errors = {}, set(), []
        offset = self.adapter.discovery_offset
        complete = False
        for _ in range(max_pages):
            limit = min(page_size, max_markets - len(selected))
            rows = await self.adapter._get(
                GAMMA,
                "/markets",
                {
                    "active": "true",
                    "closed": "false",
                    "limit": limit,
                    "offset": offset,
                    "order": "volume24hr",
                    "ascending": "false",
                },
            )
            if not isinstance(rows, list):
                raise TypeError("invalid public market page")
            offset += len(rows)
            for raw in rows:
                if not isinstance(raw, dict):
                    errors.append("malformed_market")
                    continue
                scanned.add(str(raw.get("id", "")))
                try:
                    records = normalize_market(raw, self.adapter.clock())
                    if any(m.status != "active" for m in records):
                        raise ValueError("inactive market")
                    if raw.get("enableOrderBook") is False or raw.get("acceptingOrders") is False:
                        continue
                    selected.setdefault(records[0].market_id, records)
                except (TypeError, ValueError, KeyError):
                    errors.append("invalid_market:" + str(raw.get("id", "?")))
            if len(rows) < limit:
                offset = 0
                complete = True
                break
            if len(selected) >= max_markets:
                break
        self.adapter.discovery_offset = offset
        self._original.discovery_offset = offset
        markets = tuple(m for records in selected.values() for m in records)
        return DiscoveryBatch(markets, len(scanned), not complete, tuple(errors), offset)

    def set_markets(self, markets: Sequence[MarketSnapshot]) -> None:
        unique = {m.token_id: m for m in markets}
        if len(unique) > self.max_tokens:
            raise ValueError("subscription token budget exceeded")
        for m in markets:
            if unique[m.token_id].market_id != m.market_id:
                raise ValueError("ambiguous token identity")
        self._markets = unique
        self._resolved_tokens.intersection_update(unique)
        self._gap_watermarks = {key: value for key, value in self._gap_watermarks.items() if key in unique}
        self.latest = {k: v for k, v in self.latest.items() if k in unique}

    async def books(
        self, markets: Sequence[MarketSnapshot], limit: int | None = None
    ) -> list[OrderBookSnapshot]:
        self.set_markets(markets)
        values = list(self._markets.values())
        count = min(len(values), limit if limit is not None else self.max_tokens)
        if count < 0:
            raise ValueError("invalid REST book count")
        if not values:
            return []
        chosen = [values[(self._cursor + i) % len(values)] for i in range(count)]
        self._cursor = (self._cursor + count) % len(values)

        async def one(m):
            if m.token_id in self._resolved_tokens:
                return None
            try:
                b = await self.adapter.book(m.market_id, m.token_id)
                self._metrics["rest_books"] += 1
                if m.token_id in self._resolved_tokens:
                    return None
                if not self._accept_baseline(b):
                    return None
                old = self.latest.get(m.token_id)
                if old is not None and b.timestamp < old.timestamp:
                    self._metrics["out_of_order"] += 1
                    return old
                self.latest[m.token_id] = b
                return b
            except (httpx.HTTPError, ValueError, TypeError, KeyError):
                self.latest.pop(m.token_id, None)
                return None

        result = await asyncio.gather(*(one(m) for m in chosen))
        return [b for b in result if b is not None]

    def _invalidate(self, tokens: Sequence[str] | None = None, *, gap: bool = True, watermark=None):
        affected = list(tokens) if tokens is not None else list(self._markets)
        for token in affected:
            self.latest.pop(token, None)
        self._metrics["invalidations"] += 1
        if gap:
            self._metrics["gaps"] += 1
            self.last_gap_at = self.adapter.clock()
            boundary = watermark or self.last_gap_at
            for token in affected:
                prior = self._gap_watermarks.get(token)
                if prior is None or boundary > prior:
                    self._gap_watermarks[token] = boundary

    def _accept_baseline(self, book):
        if not self._admit_levels(book.token_id, len(book.bids) + len(book.asks)):
            return False
        boundary = self._gap_watermarks.get(book.token_id)
        if boundary is not None and book.timestamp < boundary:
            self._metrics["stale_recovery_baselines"] += 1
            return False
        self._gap_watermarks.pop(book.token_id, None)
        return True

    def _admit_levels(self, token, levels, *, watermark=None):
        other = sum(len(b.bids) + len(b.asks) for key, b in self.latest.items() if key != token)
        if levels > self.max_book_levels or other + levels > self.max_cached_levels:
            self._metrics["book_level_budget_rejections"] += 1
            self._invalidate([token], watermark=watermark)
            return False
        return True

    async def execution_book(self, token: str):
        """A pending order cannot bypass resolution/gap guards via raw REST."""
        return await self._resnapshot(token)

    async def _resnapshot(self, token: str, *, generation=None, invalidate=True):
        if invalidate:
            self.latest.pop(token, None)
        market = self._markets.get(token)
        if market is None or token in self._resolved_tokens:
            return None
        try:
            book = await self.adapter.book(market.market_id, token)
            self._metrics["rest_books"] += 1
            if token in self._resolved_tokens or (generation is not None and generation != self._generation):
                return None
            if not self._accept_baseline(book):
                return None
            current = self.latest.get(token)
            if current is not None and current.timestamp > book.timestamp:
                self._metrics["out_of_order"] += 1
                return current
            self.latest[token] = book
            return book
        except (httpx.HTTPError, ValueError, TypeError, KeyError):
            return None

    def _schedule_resnapshot(self, token):
        if token in self._refresh_tasks or token in self._resolved_tokens or token not in self._markets:
            return
        generation = self._generation

        async def recover():
            try:
                book = await self._resnapshot(token, generation=generation, invalidate=False)
                if book is not None and generation == self._generation and self._on_book is not None:
                    value = self._on_book(book)
                    if inspect.isawaitable(value):
                        await value
            except Exception:  # noqa: BLE001 - background failure leaves a token withheld
                self._metrics["resnapshot_failures"] += 1
            finally:
                if self._refresh_tasks.get(token) is asyncio.current_task():
                    self._refresh_tasks.pop(token, None)

        self._refresh_tasks[token] = asyncio.create_task(recover())

    async def _cancel_refreshes(self):
        tasks = list(self._refresh_tasks.values())
        self._refresh_tasks.clear()
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def handle(self, event: dict, *, background_recovery=False) -> list[OrderBookSnapshot]:
        """Return verified full states; no callback is authorized by mere receipt."""
        if not isinstance(event, dict):
            raise StreamGap("invalid market frame")
        kind = event.get("event_type") or event.get("type")
        payload = event.get("payload", event)
        if not isinstance(payload, dict):
            raise StreamGap("invalid payload")
        received = self.adapter.clock()
        if kind == "book":
            self._metrics["native_book_frames"] += 1
            token = str(payload.get("asset_id") or payload.get("assetId") or "")
            if token not in self._markets or token in self._resolved_tokens:
                return []
            try:
                sides = (payload.get("bids"), payload.get("asks"))
                if all(isinstance(side, list) for side in sides) and not self._admit_levels(token, sum(map(len, sides))):
                    return []
                book = normalize_book(payload, self._markets[token].market_id, token, received)
                if not self._accept_baseline(book):
                    return []
                old = self.latest.get(token)
                if old and book.timestamp < old.timestamp:
                    self._metrics["out_of_order"] += 1
                    return []
                values = book.model_dump()
                values["source"] = MARKET_WS
                values["id"] = stable_id("ws-full", {k: v for k, v in values.items() if k != "id"})
                book = OrderBookSnapshot.model_validate(values)
                self.latest[token] = book
                self._metrics["native_books_delivered"] += 1
                return [book]
            except (ValueError, KeyError, TypeError):
                self._metrics["invalid_frames"] += 1
                self._invalidate([token])
                return []
        if kind == "price_change":
            self._metrics["native_delta_frames"] += 1
            changes = payload.get("price_changes", payload.get("priceChanges", []))
            if not isinstance(changes, list) or not changes:
                raise StreamGap("empty price changes")
            grouped = defaultdict(list)
            for change in changes:
                if not isinstance(change, dict):
                    raise StreamGap("invalid price change")
                token = str(change.get("asset_id") or change.get("assetId") or "")
                if token in self._markets and token not in self._resolved_tokens:
                    grouped[token].append(change)
            result = []
            for token, updates in grouped.items():
                old = self.latest.get(token)
                at = received
                try:
                    at = timestamp(payload["timestamp"])
                    if at > received:
                        raise ValueError("future delta")
                    if old and at < old.timestamp:
                        self._metrics["out_of_order"] += 1
                        continue
                    if old is None:
                        raise ValueError("missing baseline")
                    if (at - old.timestamp).total_seconds() > self.max_gap_seconds:
                        raise ValueError("detected source time gap")
                    # Levels are frozen public records. Reuse unchanged instances
                    # instead of rebuilding the whole book for each single-level
                    # venue replacement; older snapshots remain immutable.
                    bids = {Decimal(str(v.price)): v for v in old.bids}
                    asks = {Decimal(str(v.price)): v for v in old.asks}
                    for update in updates:
                        price, size = Decimal(str(update["price"])), Decimal(str(update["size"]))
                        if not price.is_finite() or not size.is_finite() or not 0 < price < 1 or size < 0:
                            raise ValueError("invalid delta level")
                        side = update["side"]
                        if side not in {"BUY", "SELL"}:
                            raise ValueError("invalid delta side")
                        levels = bids if side == "BUY" else asks
                        if size == 0:
                            levels.pop(price, None)
                        else:
                            previous = levels.get(price)
                            if previous is None or Decimal(str(previous.size)) != size:
                                levels[price] = PriceLevel(price=float(price), size=float(size))

                    def levels(values, reverse=False):
                        return tuple(v for _, v in sorted(values.items(), reverse=reverse))

                    if not self._admit_levels(token, len(bids) + len(asks), watermark=min(at, received)):
                        if background_recovery:
                            self._schedule_resnapshot(token)
                        else:
                            refreshed = await self._resnapshot(token)
                            if refreshed is not None:
                                result.append(refreshed)
                        continue
                    values = {
                        "timestamp": at,
                        "available_at": received,
                        "source": MARKET_WS,
                        "market_id": old.market_id,
                        "token_id": token,
                        "bids": levels(bids, True),
                        "asks": levels(asks),
                        "sequence": 0,
                        "complete": True,
                    }
                    book = OrderBookSnapshot(id=stable_id("ws-book", values), **values)
                    # Best quotes describe the resulting token update. Earlier
                    # updates in this same atomic batch may have intermediate tops.
                    for update in updates[-1:]:
                        for camel, snake, actual in [
                            ("bestBid", "best_bid", book.bids[0].price if book.bids else 0),
                            ("bestAsk", "best_ask", book.asks[0].price if book.asks else 1),
                        ]:
                            declared = update.get(camel, update.get(snake))
                            if declared is not None and abs(float(declared) - actual) > 1e-9:
                                raise ValueError("top-of-book integrity gap")
                    self.latest[token] = book
                    self._metrics["native_books_delivered"] += 1
                    result.append(book)
                except (ValueError, KeyError, TypeError, InvalidOperation) as error:
                    reason = str(error)
                    category = (
                        "gap_missing_baseline"
                        if reason == "missing baseline"
                        else "gap_source_time"
                        if reason == "detected source time gap"
                        else "gap_top_integrity"
                        if reason == "top-of-book integrity gap"
                        else "gap_invalid_delta"
                    )
                    self._metrics[category] += 1
                    self._invalidate([token], watermark=min(at, received))
                    if background_recovery:
                        self._schedule_resnapshot(token)
                    else:
                        refreshed = await self._resnapshot(token)
                        if refreshed is not None:
                            result.append(refreshed)
            return result
        if kind in {"tick_size_change", "market_resolved"}:
            token = str(payload.get("asset_id") or payload.get("assetId") or "")
            supplied = payload.get("assets_ids", payload.get("asset_ids", payload.get("assetIds", [])))
            candidates = {str(value) for value in supplied} if isinstance(supplied, list) else set()
            if token:
                candidates.add(token)
            tokens = sorted(candidates.intersection(self._markets))
            # Condition IDs aren't Gamma market IDs. If the venue's event does
            # not identify subscribed assets, do not guess an unaffected scope.
            if not tokens:
                tokens = list(self._markets)
            if kind == "market_resolved":
                self._resolved_tokens.update(tokens)
            self._invalidate(tokens)
        return []

    async def _heartbeat(self, socket):
        while True:
            await asyncio.sleep(10)
            await socket.send("PING")

    async def _receive(self, socket):
        while True:
            message = await asyncio.wait_for(socket.recv(), timeout=25)
            self._metrics["messages"] += 1
            self.last_message_at = self.adapter.clock()
            if message in {"PONG", "PING"}:
                if message == "PING":
                    await socket.send("PONG")
                continue
            try:
                frame_bytes = len(message.encode("utf-8")) if isinstance(message, str) else len(message)
                self._metrics["largest_frame_bytes"] = max(self._metrics["largest_frame_bytes"], frame_bytes)
                if frame_bytes > 16 * 1024**2:
                    self._metrics["oversized_frames"] += 1
                    self._invalidate()
                    raise StreamGap("market frame byte budget exceeded")
                events = json.loads(message)
                for index, event in enumerate(events if isinstance(events, list) else [events]):
                    # A native initial full-book list can contain the whole universe.
                    # Yield to consumers before a second burst fills the bounded queue.
                    if index and index % 16 == 0:
                        await asyncio.sleep(0)
                    charge = _payload_bytes(event, self.queue_bytes - self._queued_bytes)
                    if self._queued_bytes + charge > self.queue_bytes:
                        self._metrics["queue_byte_overflows"] += 1
                        self._invalidate()
                        raise StreamGap("market queue byte budget exceeded")
                    self._queued_bytes += charge
                    self._metrics["queue_peak_bytes"] = max(self._metrics["queue_peak_bytes"], self._queued_bytes)
                    try:
                        self._queue.put_nowait((event, charge))
                    except asyncio.QueueFull:
                        # Backpressure the socket reader briefly instead of
                        # discarding a valid burst. The queue and byte budget
                        # remain bounded; a stalled consumer still fails closed.
                        self._metrics["queue_backpressure_waits"] += 1
                        try:
                            await asyncio.wait_for(
                                self._queue.put((event, charge)), timeout=self.queue_put_timeout
                            )
                        except TimeoutError:
                            self._queued_bytes -= charge
                            self._metrics["queue_backpressure_timeouts"] += 1
                            self._metrics["queue_overflows"] += 1
                            self._invalidate()
                            raise StreamGap("market queue backpressure timeout") from None
                        except asyncio.CancelledError:
                            self._queued_bytes -= charge
                            raise
            finally:
                # Neither an empty queue nor a completed callback should retain
                # the whole previous decoded universe while waiting for IO.
                message = events = event = None
            await asyncio.sleep(0)

    async def _consume(self, on_book):
        while True:
            queued = await self._queue.get()
            charge = 0
            try:
                if isinstance(queued, tuple):
                    event, charge = queued
                else:
                    # Preserve deterministic/local raw-event injection. Native
                    # transport always enters through charged _receive admission.
                    event = queued
                    candidate = _payload_bytes(event, self.queue_bytes - self._queued_bytes)
                    if self._queued_bytes + candidate > self.queue_bytes:
                        self._metrics["queue_byte_overflows"] += 1
                        self._invalidate()
                        raise StreamGap("market consumer byte budget exceeded")
                    charge = candidate
                    self._queued_bytes += charge
                for book in await self.handle(event, background_recovery=True):
                    try:
                        value = on_book(book)
                        if inspect.isawaitable(value):
                            await value
                    except Exception as error:
                        self._metrics["callbacks_failed"] += 1
                        raise StreamGap("market consumer failed") from error
            finally:
                self._queued_bytes -= charge
                self._queue.task_done()
                queued = event = book = value = None

    def _clear_queue(self):
        while not self._queue.empty():
            self._queue.get_nowait()
            self._queue.task_done()
        self._queued_bytes = 0

    async def run_stream(
        self,
        markets: Sequence[MarketSnapshot],
        on_book: Callable[[OrderBookSnapshot], Awaitable[None] | None],
    ):
        self.set_markets(markets)
        self._on_book = on_book
        if not self._markets:
            return
        attempt = 0
        while not self._closed:
            tasks = []
            try:
                self._generation += 1
                self._invalidate(gap=False)
                self._clear_queue()
                self._queue = asyncio.Queue(maxsize=self.queue_size)
                async with self.connector(
                    MARKET_WS, open_timeout=15, close_timeout=5, ping_interval=None,
                    max_size=16 * 1024 * 1024, max_queue=1,
                ) as socket:
                    await socket.send(json.dumps({"assets_ids": list(self._markets), "type": "market"}))
                    self.connected = True
                    tasks = [
                        asyncio.create_task(self._heartbeat(socket)),
                        asyncio.create_task(self._receive(socket)),
                        asyncio.create_task(self._consume(on_book)),
                    ]
                    done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_EXCEPTION)
                    for task in done:
                        task.result()
                    raise StreamGap("market stream closed")
            except (OSError, ValueError, TypeError, TimeoutError, WebSocketException, StreamGap) as error:
                self.last_reconnect_reason = (
                    str(error)[:96] if isinstance(error, StreamGap) else type(error).__name__
                )
                attempt += 1
                self._metrics["reconnects"] += 1
                if attempt > self.max_reconnects:
                    raise StreamGap("reconnect budget exhausted") from None
            finally:
                self.connected = False
                self._generation += 1
                await self._cancel_refreshes()
                self._invalidate(gap=not self._closed)
                for task in tasks:
                    task.cancel()
                for task in tasks:
                    with suppress(asyncio.CancelledError, Exception):
                        await task
                self._clear_queue()
            await asyncio.sleep(min(30, 2 ** (attempt - 1)))

    def start_stream(self, markets, on_book):
        if self._task and not self._task.done():
            raise ValueError("stream already running; stop before changing universe")
        self._closed = False
        self._task = asyncio.create_task(self.run_stream(markets, on_book))
        return self._task

    async def stop_stream(self):
        self._closed = True
        if self._task:
            self._task.cancel()
            with suppress(asyncio.CancelledError, StreamGap):
                await self._task
            self._task = None
        await self._cancel_refreshes()
        self._clear_queue()
        self.connected = False
        self._invalidate(gap=False)

    async def close(self):
        await self.stop_stream()
        await self.adapter.close()
        await self._original.close()
