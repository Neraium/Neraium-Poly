# Lossless archive lifecycle

Neraium-Poly keeps market observations and execution evidence for deterministic
research and audit. Expanding the root filesystem provides space; it does not
change the services' separate archive budgets. This lifecycle replaces a growing
single event database with bounded active segments and an all-history catalog.
It grants no trading, model-promotion or settlement authority.

## Why the original services stopped

The first production collector configuration in commit `53c0371` allowed512MiB
of event SQLite files and required2GiB of free filesystem space. Commit`0d1ac6b`
raised these to2GiB and8GiB when discovery expanded to200markets and streaming was
integrated. Experimental operation in`d3b0c70` used a separate512MiB budget and
8GiB free-space threshold. These are configurable capacity budgets enforced as
hard runtime stops. They were not a historical-retention policy or a rotation
mechanism. Original configuration models also impose upper bounds on these
settings; changing only JSON beyond those bounds would not work.

Before this change, the collector counted`events.sqlite*`; the experimental
service counted all top-level`*.sqlite*`. Thus the two usage values covered
different sets of data. Neither implementation automatically removed records,
rotated archives or compressed completed observations. The existing documentation
explicitly left archive lifecycle management to an operator. The initial caps
were conservative deployment budgets, not scientifically necessary trade-risk
thresholds; evidence integrity and fail-closed behavior remain required when
capacity allocations change.

## Storage allocation

The intended production allocations on the expanded root filesystem are:

| Owner | Total service budget | Active event segment target |
|---|---:|---:|
| Live collector / certified paper data |64GiB|16MiB|
| Experimental paper / research data |16GiB|8MiB|

Budgets cover retained originals, verified compressed copies, catalog/index files,
SQLite sidecars and non-rotating state under each service's data directory. These
are independent allocations, not permission for one account to consume another's
capacity. Account and forecast databases remain in their original locations and
are never rotated with market observations.

The global8GiB safety floor remains. Production uses a stronger64GiB free-space
threshold, including that floor, to reserve capacity for unrelated workloads.
Both service allocations together are80GiB, less than one fifth of the roughly
485GiB verified available after expansion. This is a capacity allocation, not an
assumption that other projects will stop growing. Actual free space is checked
again before writing; the service may stop before consuming its nominal budget
when another workload consumes the shared filesystem.

Segment targets bound the ordinary active SQLite file size. One already admitted
bounded record, SQLite pages, indexes and WAL can make physical size exceed the
target briefly before sealing. Total-budget checks therefore reserve write and
maintenance headroom rather than treating the segment target as a byte-exact
filesystem quota. Archive health must report both event-store usage and total
service usage so index/state growth cannot disappear from accounting.

## Immutable history and query continuity

Existing`events.sqlite` remains at its original pathname and becomes a read-only
legacy source after the previous writer closes. It is not moved, replaced,
compressed or deleted. Migration streams its rows, verifies payload digests and
builds the managed catalog without loading its full contents into memory. A
legacy-indexing checkpoint is not permission to skip unverified rows after an
interruption.

New event segments receive unique permanent paths. The active database is never
renamed or compressed. When a segment reaches its target, its SQLite writer is
checkpointed and closed before it is sealed. The next writer uses a new unique
segment path. Only completed, closed managed segments are compression candidates.
Exclusive ownership and the event-store lock serialize append and rotation.

The catalog tracks event identity, payload digest, kind, timestamps and segment
location across legacy and managed history. Duplicate IDs with identical payloads
remain idempotent after rotation and restart; reuse with different payloads fails.
Definition lookup, cumulative counts, latest-history queries and deterministic
replay must use this all-history API. Querying only the current segment would
silently lose relationship definitions, reset evidence counts or conceal orders.

An event is durably committed to its segment before its catalog entry is
published. Recovery reconciles committed segment records with the catalog before
accepting new writes. An interruption between these steps must recover the same
record once, not discard it or emit it again as a new identity. Unknown segment
files are not disposable temporary files: they may contain the last successful
pre-crash append and require integrity validation and reconciliation.

## Compression and retention policy

The policy is **retain all originals and verified compressed copies**. There is
no automatic purge, expiration, truncation, vacuum-based history removal or
deletion of old segments. Compression provides a portable lossless copy; while
originals are retained, it does not reclaim their occupied capacity. Compression
ratios must not be advertised as net disk savings under this policy.

Compression works only on a closed immutable managed segment. It writes a
temporary gzip copy, verifies that decompression reproduces the original bytes
and expected hash, flushes it durably, and publishes its completed manifest
atomically. Interrupted or corrupt copies cannot become trusted archive history.
Compression work is bounded to one segment at a time and remains inside the
service budget and free-space threshold. The original stays available throughout.
SQLite catalog and manifests retain the hashes and provenance required for replay.

An unfinished compression operation can be retried from the preserved original.
A pre-existing file at a target archive path must not be silently overwritten
without proving it is the expected completed copy. Corrupt segments, conflicting
event identities, inconsistent manifests and unverifiable recovery states fail
closed. Quarantine or operator review must preserve the suspect bytes.

Finite storage cannot retain an unbounded stream forever without deletion or
additional capacity. Reaching a service budget or the shared free-space threshold
therefore stops new collection safely and exposes the precise reason. Long-term
operation still needs an explicitly reviewed retention/migration policy. No source
deletion is authorized by compression success alone. Any future retention policy
must identify approved destinations, verify complete copies and integrity, define
which originals may be removed, and preserve account/forecast audit requirements.

## Monitoring and exhaustion estimates

Archive status reports usage, budget, remaining bytes, active-segment size,
completed/compressed segment counts, total record count, legacy count, filesystem
free bytes, configured thresholds, retention policy and failure reason. Reported
growth is measured from timed observations, not inferred from market count or
manufactured by fixtures. Startup indexing and copying old history are migration
work, not a steady-state ingestion rate.

Growth and time-to-exhaustion are unknown until enough elapsed-time observations
exist. If measured positive net growth is`r` bytes/second, the archive-only estimate
is remaining budget divided by`r`. It is an estimate, not a promise: compression
copies, SQLite WAL/checkpoint behavior, variable book depth and other projects'
filesystem writes change consumption. A valid zero-growth interval does not
prove infinite retention; negative short-term file-size changes do not justify
negative growth or exhaustion values. Display unsupported metrics as unavailable.

The phone monitor should distinguish live source freshness, archive health and
paper-trading authority. A connected WebSocket alone does not establish successful
durable archival. A useful narrow layout shows each service's usage/budget,
growth and estimated exhaustion, segment progress, global free space, both account
balances, the experimental emergency-stop state and live-financial-trading-disabled
status. Storage recovery does not clear an account stop or certify a strategy.

## Recovery verification

Before operational activation, tests cover segment/catalog interruption, immutable
source and compressed-copy corruption, full-budget/free-space failures, duplicate
identities, all-history lookup/count/replay and repeated restarts. Tests use
controlled synthetic records and never count them as genuine market evidence.
Production acceptance requires multiple completed rotations on authentic observed
market data, verified segment copies/manifests, no lost or duplicated record IDs,
stable account/journal histories and several healthy collection cycles. A brief
reconnection is insufficient.

Only the necessary Neraium-Poly services may restart. Preserve the existing
experimental emergency-stop latch unless its documented independent reset
conditions have been satisfied. Certified strategies remain approval-blocked;
`PAPER_TRADING=true` and`LIVE_TRADING_ENABLED=false` remain mandatory. Do not
compress or relocate any open account, forecast, risk, broker or evidence database.

Final configured values, observed growth rates, source timestamps, integrity
results, real segment rotations and remaining blockers belong in the operational
evidence/report produced after integration. This design document is not a claim
that a production soak has already passed.
