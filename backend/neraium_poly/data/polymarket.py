"""Unauthenticated read-only Polymarket adapter. No order endpoint exists here."""

import asyncio
import hashlib
import json
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any, Protocol

import httpx
from pydantic import Field, field_validator

from neraium_poly.contracts import MarketSnapshot, OrderBookSnapshot, PriceLevel, Record

GAMMA = "https://gamma-api.polymarket.com"
CLOB = "https://clob.polymarket.com"
DATA = "https://data-api.polymarket.com"


def utc_now() -> datetime:
    return datetime.now(UTC)


def stable_id(kind: str, payload: dict) -> str:
    return hashlib.sha256((kind + json.dumps(payload, sort_keys=True, default=str)).encode()).hexdigest()


def timestamp(value: Any) -> datetime:
    if isinstance(value, datetime):
        result = value
    elif isinstance(value, (int, float)) or (isinstance(value, str) and value.replace(".", "", 1).isdigit()):
        numeric = float(value)
        result = datetime.fromtimestamp(numeric / 1000 if numeric > 10_000_000_000 else numeric, UTC)
    else:
        result = datetime.fromisoformat(str(value))
    if result.tzinfo is None:
        raise ValueError("source timestamp lacks timezone")
    return result.astimezone(UTC)


def _array(value: Any) -> list:
    result = json.loads(value) if isinstance(value, str) else value
    if not isinstance(result, list):
        raise TypeError("expected array")
    return result


def normalize_market(raw: dict, received_at: datetime) -> tuple[MarketSnapshot, ...]:
    """One record per outcome token; absent prices/IDs are rejected, never guessed."""
    tokens = _array(raw.get("positionIds") if raw.get("version") == "v2" else raw.get("clobTokenIds", []))
    outcomes = _array(raw.get("outcomes", []))
    prices = _array(raw.get("outcomePrices", []))
    if not tokens or len(tokens) != len(outcomes) or len(prices) != len(tokens):
        raise ValueError("incomplete outcome identifiers/prices")
    event_id = raw.get("eventId") or next((e.get("id") for e in raw.get("events", []) if e.get("id")), None)
    if not event_id or not raw.get("id") or not raw.get("question"):
        raise ValueError("missing market/event identity")
    status = "unknown"
    if raw.get("umaResolutionStatus") == "resolved" or raw.get("resolved") is True:
        status = "resolved"
    elif raw.get("closed") is True:
        status = "closed"
    elif raw.get("active") is True and raw.get("closed") is False:
        status = "active"
    records = []
    for token, outcome, price in zip(tokens, outcomes, prices, strict=True):
        if not str(token):
            raise ValueError("empty outcome identifier")
        values = {
            "timestamp": received_at,
            "available_at": received_at,
            "source": GAMMA,
            "market_id": str(raw["id"]),
            "event_id": str(event_id),
            "question": raw["question"],
            "token_id": str(token),
            "outcome": str(outcome),
            "probability": float(price),
            "status": status,
            "resolution_rules": raw.get("description") or "",
            "resolution_source": raw.get("resolutionSource") or "",
            "end_time": timestamp(raw["endDate"]) if raw.get("endDate") else None,
            "tick_size": float(raw.get("orderPriceMinTickSize") or 0.01),
            "min_order_size": float(raw.get("orderMinSize") or 1),
        }
        records.append(MarketSnapshot(id=stable_id("market", values), **values))
    return tuple(records)


def normalize_book(
    raw: dict, market_id: str, token_id: str, received_at: datetime, sequence: int = 0
) -> OrderBookSnapshot:
    supplied_id = raw.get("asset_id") or raw.get("assetId")
    if supplied_id is not None and str(supplied_id) != token_id:
        raise ValueError("book token mismatch")
    if "bids" not in raw or "asks" not in raw or "timestamp" not in raw:
        raise ValueError("incomplete book")
    bids = tuple(sorted((PriceLevel.model_validate(x) for x in raw["bids"]), key=lambda x: -x.price))
    asks = tuple(sorted((PriceLevel.model_validate(x) for x in raw["asks"]), key=lambda x: x.price))
    if len({x.price for x in bids}) != len(bids) or len({x.price for x in asks}) != len(asks):
        raise ValueError("duplicate price levels")
    values = {
        "timestamp": timestamp(raw["timestamp"]),
        "available_at": received_at,
        "source": CLOB,
        "market_id": market_id,
        "token_id": token_id,
        "bids": bids,
        "asks": asks,
        "sequence": sequence,
        "complete": True,
    }
    return OrderBookSnapshot(id=stable_id("book", values), **values)


class PriceObservation(Record):
    market_id: str
    token_id: str
    probability: float = Field(ge=0, le=1)


class TradeObservation(Record):
    market_id: str
    token_id: str
    side: str
    price: float = Field(gt=0, le=1)
    size: float = Field(gt=0)
    transaction_hash: str = ""

    @field_validator("side")
    @classmethod
    def valid_side(cls, value):
        if value not in {"BUY", "SELL"}:
            raise ValueError("unknown trade side")
        return value


class PublicExchangeAdapter(Protocol):
    async def discover(self, *, max_pages: int = 10, page_size: int = 100) -> list[MarketSnapshot]: ...
    async def book(self, market_id: str, token_id: str) -> OrderBookSnapshot: ...
    async def history(
        self, market_id: str, token_id: str, start: datetime, end: datetime
    ) -> list[PriceObservation]: ...


class PolymarketAdapter:
    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        *,
        retries: int = 4,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        clock: Callable[[], datetime] = utc_now,
        min_interval: float = 0.1,
    ):
        if retries < 1 or min_interval < 0:
            raise ValueError("invalid retry/rate configuration")
        self.client = client or httpx.AsyncClient(timeout=15, follow_redirects=False)
        self._owns_client = client is None
        self.retries, self.sleep, self.clock, self.min_interval = retries, sleep, clock, min_interval
        self._request_lock = asyncio.Lock()
        self.errors: list[str] = []
        self.discovery_complete = False

    async def close(self):
        if self._owns_client:
            await self.client.aclose()

    async def _get(self, base: str, path: str, params: dict | None = None):
        async with self._request_lock:
            for attempt in range(self.retries):
                await self.sleep(self.min_interval)
                try:
                    response = await self.client.get(base + path, params=params)
                except httpx.TransportError:
                    if attempt == self.retries - 1:
                        raise
                    await self.sleep(min(30, 2**attempt))
                    continue
                if response.status_code not in {429, 500, 502, 503, 504}:
                    response.raise_for_status()
                    return response.json()
                if attempt == self.retries - 1:
                    response.raise_for_status()
                delay = min(60, 2**attempt)
                try:
                    delay = max(delay, min(60, float(response.headers.get("Retry-After", "0"))))
                except ValueError:
                    pass
                await self.sleep(delay)
        raise RuntimeError("retry loop exhausted")

    async def discover(self, *, max_pages: int = 10, page_size: int = 100) -> list[MarketSnapshot]:
        if not 1 <= page_size <= 500 or not 1 <= max_pages <= 1000:
            raise ValueError("bounded pagination required")
        result = []
        self.errors.clear()
        self.discovery_complete = False
        for page in range(max_pages):
            rows = await self._get(
                GAMMA,
                "/markets",
                {"active": "true", "closed": "false", "limit": page_size, "offset": page * page_size},
            )
            if not isinstance(rows, list):
                raise TypeError("invalid Gamma page")
            for raw in rows:
                try:
                    result.extend(normalize_market(raw, self.clock()))
                except (ValueError, TypeError, KeyError) as exc:
                    self.errors.append(f"market {raw.get('id', '?')}: {exc}")
            if len(rows) < page_size:
                self.discovery_complete = not self.errors
                break
        return result

    async def book(self, market_id: str, token_id: str) -> OrderBookSnapshot:
        raw = await self._get(CLOB, "/book", {"token_id": token_id})
        return normalize_book(raw, market_id, token_id, self.clock())

    async def history(
        self, market_id: str, token_id: str, start: datetime, end: datetime
    ) -> list[PriceObservation]:
        if start.tzinfo is None or end.tzinfo is None or start >= end:
            raise ValueError("invalid history interval")
        raw = await self._get(
            CLOB,
            "/prices-history",
            {
                "market": token_id,
                "startTs": int(start.timestamp()),
                "endTs": int(end.timestamp()),
                "fidelity": 1,
            },
        )
        received = self.clock()
        records = []
        for row in raw["history"]:
            observed = timestamp(row["t"])
            if not start <= observed <= end:
                raise ValueError("history point outside requested interval")
            values = {
                "timestamp": observed,
                "available_at": received,
                "source": CLOB,
                "market_id": market_id,
                "token_id": token_id,
                "probability": float(row["p"]),
            }
            records.append(PriceObservation(id=stable_id("price", values), **values))
        return sorted(records, key=lambda x: (x.timestamp, x.id))

    async def trades(self, market_id: str, *, limit: int = 100) -> list[TradeObservation]:
        """Public V2 recent trades. Bounded retrieval; not an exhaustive archival feed."""
        if not 1 <= limit <= 500:
            raise ValueError("limit must be 1..500")
        raw = await self._get(DATA, "/v2/trades", {"condition": market_id, "limit": limit})
        rows = raw if isinstance(raw, list) else raw.get("data", raw.get("trades", []))
        received = self.clock()
        records = []
        for row in rows:
            token = row.get("token_id") or row.get("asset") or row.get("assetId") or row.get("asset_id")
            if token is None:
                raise ValueError("trade missing asset identifier")
            values = {
                "timestamp": timestamp(row["timestamp"]),
                "available_at": received,
                "source": DATA,
                "market_id": market_id,
                "token_id": str(token),
                "side": row["side"],
                "price": float(row["price"]),
                "size": float(row["size"]),
                "transaction_hash": row.get("transaction_hash", row.get("transactionHash", "")),
            }
            records.append(TradeObservation(id=stable_id("trade", values), **values))
        return records
