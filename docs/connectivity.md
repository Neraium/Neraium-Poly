# Bounded liquid-market connectivity

`CoverageFeed` is a public-only Polymarket transport coordinator. It contains no wallet, signer or order submission. It does not approve models or turn observed prices into independently estimated probabilities.

```python
feed = CoverageFeed(existing_adapter, max_tokens=800, concurrency=4, rate=8, queue_size=512)
batch = await feed.discover(max_markets=200, page_size=100, max_pages=4)
rest_books = await feed.books(batch.markets, limit=100)
stream_task = feed.start_stream(batch.markets, on_book)
# ... application lifecycle ...
await feed.stop_stream()
await feed.close()
```

`feed.adapter` is a `ConcurrentPublicAdapter` sharing the supplied adapter's HTTP client and clock. The application should consistently use it for public metadata, fee and resolution requests; that gives all such calls the same request-start limiter and bounded in-flight semaphore. `close()` cancels its managed stream and closes the original adapter. A separately created `run_stream(...)` task must be cancelled and awaited by its owner before changing the subscription universe. Do not mutate a running stream's universe without resubscribing.

## Discovery and REST fallback

Discovery uses official Gamma `GET /markets` with active/closed flags, bounded pagination, `order=volume24hr` and descending order. Explicitly disabled order books or order acceptance are excluded. Normalization failures remain counted as errors; they are not converted to usable contracts. Source metadata can be cached and volume is a ranking feature, not proof of current executable liquidity. `DiscoveryBatch` preserves raw scanned count, normalized outcomes, errors and the next offset for caller persistence.

The default limit is 200 distinct markets, commonly 400 outcome tokens. Subscription state has a separate hard token cap. `books(markets, limit)` rotates a bounded selection of tokens and performs concurrent public GETs. The limiter controls request starts; it never holds a global mutex while waiting for the network. Retries for transport errors, 429 and supported 5xx responses are bounded and respect numeric Retry-After values. Request concurrency and rate have hard bounds. Unknown origins and non-public request surfaces are rejected.

REST returns actual source timestamps and receipt times. The existing strict 15-second book-quality check is unchanged. A complete HTTP response may still contain a stale or one-sided venue book; no timestamp is replaced with the fetch time to make it appear fresh.

## WebSocket continuity

The stream uses the public market endpoint `wss://ws-subscriptions-clob.polymarket.com/ws/market` and native full-book/price-change frames, with PING/PONG liveness checks. Both documented legacy snake-case and current camel-case envelopes are handled. Native books have the WebSocket URL in `Record.source`; REST resnapshots retain the CLOB HTTP source. Counters distinguish native full frames, delta frames, native states delivered, and REST requests/books. Native traffic is not claimed merely because a REST bootstrap succeeded.

Price changes replace the exact side/price size, with size zero removing a level. Multiple level changes for a token are applied atomically before crossing and best-bid/ask integrity checks. Instrument IDs, finite prices/sizes, source time, and a complete baseline are required. Older frames cannot regress known state. Missing baselines, detected source-time gaps, declared top-of-book disagreement and invalid deltas invalidate the affected token and resnapshot only that token. Tick changes and resolution notifications invalidate affected known tokens. No all-universe HTTP refresh occurs on every price change.

There is no invented global exchange sequence number. The transport cannot prove an undocumented upstream loss of a deeper-level delta from timestamps alone; periodic public REST verification remains appropriate. It detects explicit disconnects, timeout, queue overflow, malformed payloads, obsolete frames, missing baselines and available top-of-book integrity discrepancies.

A bounded queue separates receiving from consumers. Overflow invalidates cached executable states and forces reconnection; it does not silently drop changes while retaining a supposedly complete book. Disconnect/reconnect clears cached books until a new native full book or affected-token REST snapshot reestablishes state. `feed.latest` is the authoritative cache: consumers must not keep trading from a copied pre-gap cache. Callback failure is also a stream gap, not an acknowledged delivery. Source freshness must still be checked at every order decision.

`metrics()` reports connection/subscription status, fresh and cached book counts, queue depth, messages, native frame/state counts, REST activity, reconnects, gaps, invalidations, out-of-order frames, overflows, invalid frames, callback failures and receipt times. Invalidations include intentional startup/shutdown cache clearing; detected gaps are separately counted. These are operational diagnostics, not proof that every exchange event was observed.

## Evidence and resource bounds

The final bounded public probe and verification results are saved under the isolated worktree's `.planning/evidence/`. The probe reads real public data and submits no order. It is not a sustained-load test or trading certification. Unit tests use explicit synthetic transport fixtures and test integrity/recovery behavior only.

Active streams can produce hundreds of deep-level book updates per second even for a small subset. Applications must bound their archival writes and queues as well as REST polling. Archive only according to an explicit completeness policy, preserve source/receipt references for heartbeats, expose any persistence pause as a data gap, and never allow a background callback to bypass the application's disk budget. This module owns no unbounded history list or disk archive.

Primary documentation inspected 2026-11-06:

- [Gamma list markets](https://docs.polymarket.com/api-reference/markets/list-markets)
- [Gamma OpenAPI specification](https://docs.polymarket.com/api-spec/gamma-openapi.yaml)
- [Public market real-time frames](https://docs.polymarket.com/market-data/realtime-data)
- [Public market AsyncAPI specification](https://docs.polymarket.com/asyncapi.json)

Final observed smoke at2026-11-06T00:48:05Z:201raw markets scanned,200normalized markets/400outcomes,one malformed market excluded. A20-token native subscription over12seconds received74messages containing22native full-book frames and69delta frames, delivered160full book states, with zero reconnects/detected gaps/overflows. At the measurement instant8/20cached books passed the existing strict freshness/two-sided quality check. There were20separately counted RESTbootstrap books. This demonstrates actual native ingestion, not uniformly executable200market coverage. Detailed source/receipt timestamps and public market IDs are in connectivity-smoke-final.json. An earlier20-second40-token probe is retained separately; its callback examples were capped and its RESTfreshness count was measured atprobeend, not atinitialfetch.

Follow-up integrity hardening: a429 Retry-After response extends the global request-start cooldown, including requests already waiting for a start slot; even a final failed attempt leaves that cooldown in force. Concurrent REST responses and affected-token resnapshots cannot overwrite a newer native source timestamp. Resolution/tick notifications support asset arrays; unknown condition-only scope conservatively invalidates all subscribed states. Resolution notifications also withhold identified tokens from subsequent REST/native updates for the current subscribed universe, preventing a full stale closed-market book from silently restoring executable status. Unknown closure scope can therefore temporarily withhold the entire universe and must be treated as a data-quality suspension, never bypassed for coverage counts.

Throughput follow-up: recovery inside the native consumer previously awaited rate-limited REST, serializing all native processing behind a single affected token. Native delivery now schedules deduplicated per-token background recoveries, leaving invalidated tokens unavailable while other assets continue. Recovery tasks are bounded by subscription tokens and cancelled on generation changes; old-generation replies cannot restore executable liquidity. Multiple changes in an atomic token update check the final declared top, rather than falsely comparing intermediate tops against the final state. The receiver cooperatively yields during400-book native initial bursts. No delta coalescing or tick-history claim was introduced.

A20-second,200-market/400-token real smoke on2026-11-06T01:10:33Z received12,258messages and delivered23,603native states, with zero queue overflows or reconnects, queue depth1,381native cached books and286books passing the strict source freshness/quality check. It performed58affected-token REST recoveries. The1,083conservative invalidation detections include repeated observations of a token still awaiting its baseline; they are not1,083proven lost packets or independent disconnects. New reason counters separate missing baseline, source-time gap, declared-top disagreement and invalid delta. The bounded test is evidence of recovered throughput, not a sustained production guarantee.

Recovery watermark hardening: every detected token gap records the latest offending source time (unknown-scope disconnect/overflow uses detection time). REST fallback, background recovery and native full snapshots must reach that boundary before the token is considered complete again. Further skipped deltas advance the boundary while one deduplicated recovery is pending. Older cached HTTP snapshots remain withheld even if received recently. This deliberately sacrifices coverage instead of reconstructing a post-gap book from a baseline older than changes already observed. Source-time watermarks are not invented exchange sequence numbers.
