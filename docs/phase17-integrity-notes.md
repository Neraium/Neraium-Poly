# Phase17 source integrity and non-destructive capacity evidence

`phase17.provenance.ReadonlyArchive(directory)` is a bounded audit reader for the
existing segmented archive, not another collector or a replacement store. It never
opens ManagedEventStore, creates an archive owner, extracts an open SQLite database,
restores compressed data to disk, changes a retention policy or deletes anything.
Every native SQLite handle uses URI `mode=ro` plus `query_only` and closes after its
short query. Existing active WAL owners continue operating.

`latest(kind,limit=100)` returns stored dictionaries, newest first, with limits of
1000 rows,16MiB per payload and64MiB per query (configurable bounded limits).
`get(id)` matches the existing store's `(kind,payload,digest)` return shape. The
catalog and source segment must agree on record identity,kind,timestamps,SHA256,
and the existing qualified flag including the legacy `-1` for records without it.
Duplicate JSON keys and nonfinite JSON values reject. Missing raw originals reject
explicitly: this reader cannot silently synthesize history or create a restored DB.

`verify_study(study)` authenticates the exact persisted QualificationStudy.
`verify_point(point,study)` independently recomputes the Phase16 point from that
study's source frame, including raw book/market hashes, source/receipt/cutoff times,
fee observation and monetary-depth features. `verify_pair(pair,a,b)` verifies both
points, token/market/event/rules identity,60–90second source horizon, availability,
actual observed monetary marks and explicit non-settlement semantics. Two endpoints
alone do not prove the chosen target was the first eligible quote; chronological
replay of intervening studies remains necessary. No hash proves an external source
assertion true, and these checks never confer certification or trading authority.

`verify_segment(name)` applies only to an existing immutable completed source. It
checks its bounded raw size/hash,manifest identity/count/policy,SQLite quick_check,
record count,and existing gzip size/hash and lossless streamed decompression hash.
It never compresses/moves the original or writes an extracted file. Default maximum
raw verification size256MiB can be configured up to1GiB; larger legacy files require
an independently bounded audit rather than silently exceeding the limit.

`phase17.storage.storage_growth(samples,now=...,budget_bytes=...,free_bytes=...)`
is pure and restart-safe with caller-owned durable samples. At most1008 observations
are accepted. Five minutes of positive chronological net retained allocation are
needed for a provisional runway. Unknown,zero,negative,future,duplicate or stale
samples do not become infinite capacity. Service saturation and filesystem floor
violations fail closed, with at least8GiB retained regardless of a smaller supplied
floor. The existing64GiB production reserve and64/16GiB service budgets are unchanged.
Additional future research throughput can be modeled separately. A24hour span is
recorded separately from representative workload evidence; this helper never
asserts the latter from endpoints alone.

ACTIVE sources,WARM immutable originals,COLD additional compressed representations,
PROTECTED account/catalog/audit/forecast records and DERIVED verified cold caches
are explicitly classified. `retention_proposal(...)` returns an owner-reviewable
non-executable proposal and exact retirement prerequisites; it cannot authorize
removal. Existing cold caches are already bounded64MiB; removing only such a cache
cannot solve multi-GiB/day original/catalog growth. Compression duplicates do not
reclaim disk while originals remain. Catalog growth also remains after hypothetical
future approved raw retirement. New derived research must remain bounded, and a
separate exact owner-approved retention/capacity decision is still required.

Initial authentic read-only audit (2026-11-07T00:02:23Z) verified8existing studies,
independently recomputed50points and round-trip-verified a4,263,936byte completed
segment. Over the approximately7minute phase-start comparison, net growth was
110,867B/s collector and64,544B/s experimental; conditional cap horizons were
6.32days and2.61days. These are provisional net allocation measurements, not a
representative day or guaranteed sustained operation. Original hashes and all
records were preserved. This audit accepted no new independently resolved outcome.
Existing missing native resolution/transaction fields are not manufactured from
quote marks; terminal outcome qualification remains a separate evidence gate.

Controlled tests cover active-owner read-only invariance,source corruption/truncation,
missing source,symlink/traversal rejection,payload/query budgets,point/pair mutation,
checkpoint replay,manifest corruption,gzip corruption,unknown growth and disk-floor/
service-budget backpressure. Fixtures are not authentic research evidence.
