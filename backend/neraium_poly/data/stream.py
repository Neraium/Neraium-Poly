"""Recoverable public market stream. REST resnapshot prevents unknown delta gaps."""

import asyncio
import json
from collections.abc import Awaitable, Callable
from contextlib import suppress

import httpx
from websockets.asyncio.client import connect
from websockets.exceptions import WebSocketException

from .polymarket import PolymarketAdapter, normalize_book, utc_now

MARKET_WS = "wss://ws-subscriptions-clob.polymarket.com/ws/market"


class MarketStream:
    def __init__(
        self,
        adapter: PolymarketAdapter,
        markets: dict[str, str],
        *,
        connector=connect,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        max_reconnects: int = 8,
    ):
        if not markets or max_reconnects < 0:
            raise ValueError("markets and bounded reconnect count required")
        self.adapter, self.markets, self.connector = adapter, dict(markets), connector
        self.sleep, self.max_reconnects = sleep, max_reconnects
        self.connected = False
        self.generation = 0
        self.errors: list[str] = []
        self.latest = {}

    async def _heartbeat(self, socket):
        while True:
            await self.sleep(10)
            await socket.send("PING")

    async def snapshots(self):
        """Yield only complete books, clear state on disconnect; caller checks age."""
        reconnects = 0
        while True:
            heartbeat = None
            try:
                async with self.connector(
                    MARKET_WS, open_timeout=15, close_timeout=5, ping_interval=None, max_size=4 * 1024 * 1024
                ) as socket:
                    await socket.send(json.dumps({"assets_ids": list(self.markets), "type": "market"}))
                    self.connected = True
                    self.generation += 1
                    self.latest.clear()
                    heartbeat = asyncio.create_task(self._heartbeat(socket))
                    for token, market in self.markets.items():
                        book = await self.adapter.book(market, token)
                        self.latest[token] = book
                        yield book
                    while True:
                        message = await asyncio.wait_for(socket.recv(), timeout=25)
                        if message in {"PONG", "PING"}:
                            if message == "PING":
                                await socket.send("PONG")
                            continue
                        events = json.loads(message)
                        if not isinstance(events, list):
                            events = [events]
                        for event in events:
                            event_type = event.get("event_type") or event.get("type")
                            payload = event.get("payload", event)
                            token = str(payload.get("asset_id") or payload.get("assetId") or "")
                            if event_type == "book" and token in self.markets:
                                book = normalize_book(
                                    payload,
                                    self.markets[token],
                                    token,
                                    getattr(self.adapter, "clock", utc_now)(),
                                )
                                old = self.latest.get(token)
                                if old and book.timestamp < old.timestamp:
                                    continue
                                self.latest[token] = book
                                yield book
                            elif event_type in {"price_change", "tick_size_change", "market_resolved"}:
                                # No global exchange sequence is promised. Refresh every subscribed
                                # token rather than applying possibly missed/out-of-order deltas.
                                for token, market in self.markets.items():
                                    book = await self.adapter.book(market, token)
                                    self.latest[token] = book
                                    yield book
                raise ConnectionError("market stream closed")
            except (
                OSError,
                ValueError,
                TimeoutError,
                ConnectionError,
                WebSocketException,
                httpx.HTTPError,
            ) as exc:
                self.errors.append(type(exc).__name__)
                if len(self.errors) > 100:
                    del self.errors[:-100]
                reconnects += 1
                if reconnects > self.max_reconnects:
                    raise ConnectionError("market reconnect budget exhausted") from exc
            finally:
                self.connected = False
                self.latest.clear()
                if heartbeat is not None:
                    heartbeat.cancel()
                    with suppress(asyncio.CancelledError, OSError, WebSocketException):
                        await heartbeat
            await self.sleep(min(30, 2 ** (reconnects - 1)))
