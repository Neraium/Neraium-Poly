# Public market data and replay

`PolymarketAdapter` implements a read-only `PublicExchangeAdapter` protocol. Its async methods are `discover(max_pages=10, page_size=100)`, `book(market_id, token_id)`, `history(market_id, token_id, start, end)`, `trades(condition_id, limit=100)` and `close()`. The argument named `market_id` to `trades` must be Polymarket's on-chain condition ID, as the current V2 feed filters by `condition`; it is not Gamma's numeric market ID. Discovery produces one immutable `MarketSnapshot` per outcome and supports legacy `clobTokenIds` and Protocol V2 `positionIds`. Missing identifiers or prices are rejected and recorded in `adapter.errors`. `adapter.discovery_complete` is true only when pagination exhausts below the configured cap and all rows normalize.

Order books are sorted best-first, checked for crossed or duplicate levels, associated with the requested token, and rejected without source timestamps or both depth arrays. `assess_book(book, now)` reports missing, stale, future, incomplete, wrong-token, missing-liquidity and wide-spread conditions. Collection time is never substituted for a missing order-book source timestamp. `LifecycleTracker.observe` tracks active, closed and resolved states without treating closed as settled; `tradable` requires explicit rules and resolution source.

`MarketStream(adapter, {token_id: market_id}).snapshots()` opens only the public market WebSocket, sends the documented subscription and text heartbeat, and resnapshots via REST after every reconnect. Incremental changes trigger complete REST refreshes rather than unsafe application of unsequenced deltas. Disconnects clear cached books. Retry count, delays, maximum message size, and HTTP timeouts are bounded. HTTP transport/429/5xx errors retry with capped exponential backoff and numeric Retry-After support. No credential or wallet interfaces exist.

`EventStore(path).append(record)` transactionally appends any shared contract Record subclass. Equal IDs and payloads are idempotent across threads and connections; ID collisions with changed payloads fail. SQL triggers prohibit ordinary updates/deletes. SHA256 payload digests detect replay corruption. `replay(until=..., kind=...)` returns `{kind, record}` dictionaries ordered by availability time, then source timestamp and stable ID; late arrivals remain unavailable in an earlier replay. SQLite uses WAL and full synchronous writes. Reopening the same path recovers the ledger. This is a research event store, not cryptographically tamper-proof storage against an owner of the database file.

History retrieved today retains today's availability time, even when source observations are old. This prevents accidental use of a later download as point-in-time data. Research that can prove contemporaneous availability may construct a separate provenance-backed dataset. We do not assume historical order-book depth is available. Archive complete books prospectively. Recent trade retrieval is bounded to one page and is explicitly not an exhaustive historical trade collector. `MarketStream` refresh-all behavior favors correctness over throughput; broader subscriptions need batching/coalescing before high-volume ingestion. No continuous worker is started automatically.

## Verification

On 2026-11-05, `PYTHONPATH=backend /home/ubuntu/Neraium-Poly/.venv/bin/pytest -q tests/test_data.py tests/test_contracts.py` passed 20 tests (17 data tests and three shared-contract tests). Ruff checks passed for the data module and its test file. A bounded unauthenticated probe fetched three Gamma markets (six outcomes), then one CLOB book with 17 bid and 141 ask levels; freshness checks passed at collection. This proves current REST connectivity from this host, not long-running WebSocket reliability or historical completeness. WebSocket recovery is tested with deterministic injected disconnects and full-book frames, not a sustained live feed.

Official documentation inspected on 2026-11-05:

- [Market discovery](https://docs.polymarket.com/market-data/discover-markets.md)
- [Prices and order books](https://docs.polymarket.com/market-data/prices-order-books.md)
- [Public market stream, subscription, heartbeat and event formats](https://docs.polymarket.com/market-data/realtime-data.md)
- [CLOB OpenAPI specification](https://docs.polymarket.com/api-spec/clob-openapi.yaml)
- [Data API V2 specification](https://data-api.polymarket.com/v2/openapi.json)
