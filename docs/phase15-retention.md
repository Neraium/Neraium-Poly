# Phase 15 verified cold archive and proposed retention

This implementation preserves every historical original. It does not implement an original-removal function, authorize deletion, clear emergency stops, or grant trading authority. The filesystem safety floor remains 8 GiB by default. The collector and experimental archives remain separate.

## Lifecycle and trust

* **ACTIVE:** the current writable managed SQLite segment, catalog, and SQLite sidecars. No cold processing or original removal.
* **WARM:** a closed, immutable, sealed managed segment plus its independently verified gzip representation and seal manifest. Originals remain present.
* **COLD_PENDING_VERIFICATION:** a sealed segment older than the explicitly configured warm interval, awaiting independent restored-SQLite and per-record verification.
* **COLD_VERIFIED_ORIGINAL_RETAINED:** a completed independent restoration has verified raw SHA-256 and length, gzip SHA-256 and length, manifest identity, SQLite `quick_check`, every payload SHA-256 and record identity, and the exact global catalog identities and count. Original, gzip, manifest, catalog, and proof all remain present.
* **PROTECTED_LEGACY:** the pre-segmentation archive. It has no eligible original-removal transition in this implementation.

The age bound is the latest of the segment's final catalog availability time, raw modification time, and seal-manifest modification time. This avoids treating an old source observation as evidence that its newly completed segment has already satisfied warm retention. Receipt/availability time is used for retention, not a retrospective event timestamp.

`verify_cold_segment` publishes a separate immutable `*.cold-proof.json`. Its deterministic contents include the raw/gzip/manifest hashes, record counts, a hash of ordered catalog record identities, and the successful restore result. Reverification cannot silently overwrite a different completed proof. These are integrity checks within the local trust boundary, not externally signed proof against a hostile administrator.

## Recovery and bounded derived cache

`ColdSegmentReader(cache_directory, min_free_bytes=..., max_cache_bytes=...)` provides `.open(raw_path, catalog_row=...)` as a context manager yielding a read-only SQLite connection. `.verify_metadata(...)` additionally verifies every restored record against the global catalog; abbreviated verification is rejected. No network provider is involved.

Restoration streams gzip into a private derived cache with explicit compressed/raw hashes, expansion-size bounds, per-write filesystem-floor checks, fsync and exclusive publication. This verifies bytes independently rather than merely trusting gzip's CRC. Interrupted temporary publication is restart-safe. Corrupt compressed bytes, corrupt cached bytes, inconsistent manifests/catalogs, active SQLite WALs, and symlinked paths fail closed. The original source is never opened for writing, compressed, truncated, replaced, or moved.

The cache has a separate hard bound and uses shared inode locks while context-managed readers are active. Eviction requires a nonblocking exclusive lock, the exact derived-cache marker, and an intact surviving compressed source. Only reproducible cache files and owned publication temporaries can be removed. Direct external access to cache files is unsupported; callers must use the context manager to retain their pin. Cache directories must be private to this reader, separate from historical evidence directories. A segment larger than available cache capacity is rejected rather than streamed into an unbounded file. Configure enough capacity for a normal segment and publication overhead while retaining the filesystem floor.

Cold-only reading is exercised using controlled fixtures whose original is deliberately absent. That proves recovery capability without authorizing any production original removal. Reader integration must preserve catalog ordering and replay IDs and must warn about unexpectedly missing originals. It must not rehydrate all historical segments at once. Append-only catalogs and forecast/account journals remain retained and are outside cache eviction.

## Exact proposed policy requiring owner approval

Proposed warm intervals for review are **24 hours for the collector** and **12 hours for experimental observations**. They are not permission to delete originals. Default retention class is `retain_original`; the alternative `proposed_raw_after_verified_cold` produces a review document only.

For each age-qualified segment, `retention_proposal(...)` emits exact absolute raw/gzip/manifest paths, raw device/inode/link count, byte counts, raw/gzip/manifest/proof hashes, record count, ordered catalog identity hash, age eligibility time, process-reference evidence, and rejection reasons. A canonical SHA-256 binds the complete proposal. Non-age-qualified, unverified, active, and legacy records are excluded. An incomplete procfs descriptor/mapping audit fails closed. Any active reference rejects eligibility. The proposal always states `approval_required=true`, `removal_authorized=false`, and `original_removal_implemented=false`.

A future action would require the owner to explicitly approve the exact proposal hash and listed raw files, followed immediately by revalidation of identities, complete privileged process-reference checks, cold-copy recovery, reader compatibility, destination capacity, and retention class. The approval must identify its scope; a generic approval of Phase 15 does not qualify. No such irreversible action is performed here. Filesystem snapshots/backups remain separate recovery safeguards and this single-filesystem gzip copy is not off-host disaster recovery.

**Not eligible for this policy:** account ledgers, forecast journals, raw external evidence, model artifacts, research provenance, global catalogs, active SQLite files or sidecars, seal manifests, gzip copies, cold proofs, legacy archives, unrelated project files, and unknown files. Preserve these indefinitely pending a separately reviewed policy.

## Read-only production measurement

At **2026-11-06 20:38:37 UTC**, read-only catalog snapshots reported:

| Archive | Completed segments | Completed raw bytes | Completed gzip bytes | Gzip/raw ratio | Catalog records | Catalog database bytes | Catalog WAL bytes |
|---|---:|---:|---:|---:|---:|---:|---:|
| Collector | 118 | 1,526,915,072 | 404,287,038 | 0.2648 | 1,467,847 | 690,614,272 | 18,577,112 |
| Experimental | 126 | 559,587,328 | 186,963,978 | 0.3341 | 327,514 | 150,130,688 | 4,185,952 |

These actual completed gzip sizes show approximately 73.5% and 66.6% smaller representations respectively; no new compression or deletion was performed to obtain the measurement. Current combined raw-plus-gzip storage for those completed segments is 1,931,202,110 and 746,551,306 bytes. Keeping both copies increases consumption; compression alone does not reclaim space. Protected legacy raw sizes are 2,017,935,360 and 517,521,408 bytes respectively. Active segments, SQLite sidecars, journals, and other project files are additional consumption.

Catalog database bytes per indexed record in these snapshots are approximately 470.5 and 458.4 bytes, excluding WAL. This is an empirical allocated-size ratio, not a guaranteed future marginal rate. Global per-record catalogs grow linearly even under a hypothetical approved raw-original transition. A 90-day plan must model that catalog growth plus gzip, active/warm retention, cache, journals, proof/manifest overhead, and unrelated workloads. A finite budget cannot promise indefinite lossless operation. Budget increases, external destinations, and any original-removal policy require separate decisions; no AWS resources or charges are introduced here.

## Verification

Controlled regression tests cover full restoration and record/catalog hashes, read-only connections, gzip-only recovery, inode-pinned cache eviction, corruption, interrupted publication and restart, filesystem floor, exact proposal hashing, active/unknown process references, catalog mutations, malformed proofs/manifests, and active SQLite/symlink rejection. Fixture outcomes are not real market research evidence. Operational soak and full integrated certification are reported separately by the integration coordinator.

A second observation at **20:39:42 UTC** measured a **65.50-second** interval. Collector catalog records grew by 2,144 (32.734/s) and experimental records by 502 (7.664/s). Catalog database plus WAL allocated bytes increased by 1,003,520 (15,321 B/s) and 249,856 (3,815 B/s). WAL preallocation/checkpoint behavior makes short allocated-byte rates noisy. Multiplying the observed record rate by current allocated catalog bytes per record yields approximately **111.5 GiB collector** and **25.45 GiB experimental** of additional index storage over 90 days, before compressed observations or any other data. These are explicitly conditional short-window extrapolations, not a sustained workload measurement or a capacity guarantee. Nevertheless, existing 64/16 GiB budgets cannot support that scenario even if a future owner-approved raw-original policy were implemented. The integrated capacity monitor must alert and backpressure; no automatic budget increase or cleanup is authorized by this measurement.

## Optional continuous proof generation

Managed archives support `cold_verification_enabled=False` as an explicit opt-in constructor setting. When enabled, maintenance independently restores and verifies at most one oldest sealed gzip segment lacking a proof per 60 seconds. It uses a 64 MiB derived-cache ceiling, the greater of the configured filesystem floor and 8 GiB, and the existing service budget. This creates an additional integrity proof while retaining originals. It does not change retention authority. Failed verification blocks archive admission and remains blocking across throttled maintenance calls until a subsequent permitted verification succeeds; disabling the option does not clear an already observed integrity error. Existing startup recovery still verifies source integrity independently.

Status reports process-local scan/success times, the last verified segment, and errors separately from proof-file presence. `tier_usage_bytes` accounts for active files, sealed raw originals (warm), actual gzip copies (cold), protected legacy, derived cache, segment metadata, and residual catalog/service state. Presence counters and tier sizes are not claims of current cryptographic verification. All reported capacity remains conditional on continuing workload and filesystem conditions.
