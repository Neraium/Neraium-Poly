"""Bounded read-only sharing of actual immutable public order-book observations."""

import hashlib
from datetime import UTC, datetime
from urllib.parse import urlparse

import httpx

from neraium_poly.data import assess_book
from neraium_poly.experimental.contracts import SharedMarketFrame

BOOK_SOURCES = {
    "https://clob.polymarket.com",
    "wss://ws-subscriptions-clob.polymarket.com/ws/market",
}


def market_frame(runtime) -> SharedMarketFrame:
    # Never call risk.snapshot/state here: sharing observations cannot expire or
    # otherwise mutate the certified account's reservations or capital.
    with runtime._lock:
        raw_books = tuple(runtime._current_books().values())
        markets = tuple(runtime.markets.values())
        last_success = runtime.last_success
        now = runtime.clock()
        age = (now - last_success).total_seconds() if last_success else None
        by_token = {m.token_id: m for m in markets}
        books = tuple(
            b
            for b in raw_books
            if b.token_id in by_token
            and b.market_id == by_token[b.token_id].market_id
            and b.exchange == by_token[b.token_id].exchange == "polymarket"
            and b.source in BOOK_SOURCES
            and b.available_at <= now
        )
        has_fresh_books = any(assess_book(b, now).healthy for b in books)
        health = {
            "status": "ok"
            if age is not None and 0 <= age < 60 and runtime.last_error is None and has_fresh_books
            else "degraded",
            "last_error": runtime.last_error,
            "books_withheld_at_export": len(raw_books) - len(books),
            "last_ingestion_at": last_success.isoformat() if last_success else None,
            "paper_trading": True,
            "live_trading_enabled": False,
        }
        fees = {
            token: {
                "fee_rate": model.effective_notional_bound(),
                "observed_at": at.isoformat(),
                "source": "https://clob.polymarket.com",
                "reference": f"/markets-by-token/{token}",
            }
            for token, (at, model) in runtime.fees.items()
        }
        return SharedMarketFrame(
            id=hashlib.sha256((now.isoformat() + repr(tuple(b.id for b in books))).encode()).hexdigest(),
            timestamp=now,
            available_at=now,
            source="neraium-poly/public-market-frame/v1",
            producer_health=health,
            markets=markets,
            books=books,
            fees=fees,
            relationships=tuple(r.model_dump(mode="json") for r in runtime.relationships.values()),
            connectivity=runtime.coverage.metrics() if runtime.coverage else {},
        )


def loopback_url(value: str) -> str:
    url = urlparse(value)
    if (
        url.scheme != "http"
        or url.hostname != "127.0.0.1"
        or url.username
        or url.password
        or url.query
        or url.fragment
        or not url.port
    ):
        raise ValueError("explicit loopback public-data URL required")
    return value


class SharedFeedClient:
    def __init__(
        self, url="http://127.0.0.1:18742/api/market-frame", *, client=None, max_bytes=8 * 1024 * 1024
    ):
        self.url = loopback_url(url)
        if not 1024 <= max_bytes <= 32 * 1024 * 1024:
            raise ValueError("bounded frame budget required")
        self.max_bytes = max_bytes
        self.client = client or httpx.AsyncClient(timeout=10, follow_redirects=False)

    async def read(self, now=None) -> SharedMarketFrame:
        return await self._read(now)

    async def read_research(self, now=None) -> SharedMarketFrame:
        """Diagnostics may classify cached metadata; degraded books are always stripped."""
        return await self._read(now, diagnostics=True)

    async def _read(self, now=None, *, diagnostics=False) -> SharedMarketFrame:
        data = bytearray()
        async with self.client.stream("GET", self.url) as response:
            response.raise_for_status()
            async for chunk in response.aiter_bytes():
                if len(data) + len(chunk) > self.max_bytes:
                    raise ValueError("shared frame exceeds byte budget")
                data.extend(chunk)
        frame = SharedMarketFrame.model_validate_json(data)
        now = now or datetime.now(UTC)
        if not 0 <= (now - frame.available_at).total_seconds() <= 15:
            raise ValueError("stale or future shared frame")
        if frame.source != "neraium-poly/public-market-frame/v1":
            raise ValueError("unexpected public-data producer")
        if frame.producer_health.get("status") != "ok" and not diagnostics:
            raise ValueError("public-data producer is degraded")
        if frame.producer_health.get("live_trading_enabled") is not False:
            raise ValueError("public-data producer mode mismatch")
        by_token = {m.token_id: m for m in frame.markets}
        if len(by_token) != len(frame.markets) or len(by_token) > 1000:
            raise ValueError("ambiguous or over-budget market universe")
        seen = set()
        for book in frame.books:
            market = by_token.get(book.token_id)
            if (
                book.source not in BOOK_SOURCES
                or book.exchange != "polymarket"
                or market is None
                or market.exchange != book.exchange
                or market.market_id != book.market_id
                or book.token_id in seen
                or book.available_at > frame.available_at
            ):
                raise ValueError("untrusted or mismatched actual book")
            seen.add(book.token_id)
        if frame.producer_health.get("status") != "ok":
            return frame.model_copy(update={"books": (), "fees": {}, "evidence": (), "relationships": ()})
        return frame

    async def close(self):
        await self.client.aclose()
