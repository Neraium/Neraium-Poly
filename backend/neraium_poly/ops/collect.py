"""Bounded public collection. No strategy or execution is invoked."""

import json
from pathlib import Path

import httpx

from neraium_poly.data import EventStore, PolymarketAdapter


async def collect(path: Path):
    store = EventStore(path)
    adapter = PolymarketAdapter()
    counts = {"markets": 0, "books": 0, "errors": []}
    try:
        markets = await adapter.discover(max_pages=1, page_size=10)
        for market in markets:
            store.append(market)
            counts["markets"] += 1
            if market.status != "active":
                continue
            try:
                book = await adapter.book(market.market_id, market.token_id)
                store.append(book)
                counts["books"] += 1
            except (httpx.HTTPError, ValueError, TypeError, KeyError) as error:
                counts["errors"].append({"token": market.token_id, "error": type(error).__name__})
    finally:
        await adapter.close()
        store.close()
    print(json.dumps(counts))
