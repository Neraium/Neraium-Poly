# Phase 18 storage budgets and non-destructive retention

This work adds capacity admission and a policy-driven dry-run/audit engine. It
neither changes configuration nor allocates storage. The integration coordinator
must repeat the capacity proof immediately before applying actual service limits.
There is no deletion API or retention-activation switch.

## Capacity API

`budget_capacity(service_roots, *, target_budgets, filesystem_free_bytes,
filesystem_capacity_bytes, reserve_bytes, temporary_headroom_bytes,
shared_growth_reserve_bytes)` accepts mappings of service name to
`{path,current_usage_bytes,filesystem_device?}`. Existing roots must resolve to
separate non-symlink directories on the same verified filesystem; nested/duplicate
roots fail. Inputs are integer bytes, not booleans, infinities or unknown values.

Current service bytes are already deducted from filesystem available capacity.
The maximum incremental consumption is therefore `sum(max(0,target-current))`,
not the full300GiB charged a second time. The proof reserves at least100GiB,
stricter existing floors, temporary rotation/restoration capacity and explicit
headroom for unrelated workload growth. Other projects' current consumption is
already included in the filesystem free measurement. Their future growth can
invalidate any snapshot, so the actual live global floor remains mandatory.

`measure_service_tree(path)` includes every regular file beneath a service root:
active SQLite/WAL, warm originals, cold copies, temporary/hidden files, manifests,
indexes, accounts, journals and caches. Logical file bytes match the existing
managed-store accounting. Hardlink pathnames are conservatively charged twice;
symlinks/nested filesystems/unsupported entries or excess inventory size fail.
Concurrent changes require a final remeasurement and the larger owner-reported
or independently measured usage should be used.

At2026-11-07T03:59:42UTC the independent proof admitted exact200GiBcollector and
100GiBexperimental targets with100GiBfree reserve,4GiBtemporary headroom and
64GiBadditional shared-growth reserve:

* Filesystem capacity1,038,993,555,456bytes; available505,356,926,976bytes.
* Current combined service bytes13,219,543,946.
* Maximum incremental service growth308,903,003,254bytes.
* Free at both caps196,453,923,722bytes.
* Free after temporary/shared-growth headrooms123,439,479,690bytes (114.96GiB).
* Margin above protected100GiBfloor16,065,297,290bytes (14.96GiB).

No300GiBpreallocation or AWS/EBS operation occurred. These are admission calculations,
not a guarantee against arbitrary unrelated future consumption. The all-file
managed-store guard already charges temporary rotations and preserves a global floor.
Actual configuration changes, restart and post-change proof belong to integration.

## Read-only filesystem audit

Bounded low-priority `du -x` metadata scans measured approximately347.07GB under
/home/ubuntu,1.23GB under/var and67.56GB under/tmp. Some directories were inaccessible;
these totals are explicitly partial, not complete allocations. Filesystem available
capacity independently accounts for those inaccessible files.

Largest visible directories included Neraium-1.0(89.91GB), .local(41.99GB),
WWTP10-Generator(32.63GB), Neraium-Poly(15.90GB), Neraium-2-integration(15.03GB),
WWTP8blind-validation(14.52GB) and core-recovery(14.18GB). /tmp includes ARI and other
certification/test outputs. None was inspected for secret contents, removed,
relocated or treated as disposable. Audit scripts/results remain in this worktree's
`data/phase18-storage` for coordinator preservation.

## Exact proposed retention policy

`proposed_policy(minimum_warm_seconds=86400)` produces a proposal with at least24hours
of warm retention and irreversible actions disabled. Protected classes include
active databases/WAL, legacy evidence, account records, forecast journals, settlements,
provenance, catalogs and audit trails. Only redundant sealed managed segment originals
can ever be proposed after a matching gzip copy, manifest and successful restoration
proof exist. No owner approval is implied by a policy or a proof.

`retention_plan(directory, *, now, mode='dry_run', policy=None, max_segments=512,
max_verified_segments=8, max_verification_bytes=64MiB, after_segment=None)` returns an
exact SHA-bound review proposal. Modes other than `dry_run`/`audit` reject. Pagination
provides a continuation cursor instead of silently pretending a bounded prefix is
complete. Dry-run performs bounded metadata inventory; it never marks an original
ready for review solely from proof presence.

Audit verifies unchanged original and compressed hashes, full lossless streamed gzip
restoration to the original hash, original SQLite integrity, manifest identity/count,
the earlier successful restored-SQLite proof, and current record-index completeness.
It rejects nonempty WAL/journal sidecars, changes during verification, insufficient
warm age, corruption, oversized verification or interrupted/missing copies. Byte and
record/SQLite-VM limits bound independent audits. A complete process FD/memory-map
reference scan is required; inaccessible namespaces or any active reference withhold
review eligibility. Exact paths, device/inode/link counts, hashes, record counts and
policy are bound in the proposal. Existing retain-all policy remains effective.

Even `review_prerequisites_met=true` is not removal authority. Owner approval must
name the exact proposal hash and originals; all conditions must be revalidated before
any separately implemented irreversible action. No source, compressed representation,
proof, manifest, database or retention setting is written by this module.

## Authentic restoration and current eligibility

A read-only real audit inventoried272collector and349experimental catalog rows.
No originals qualified under the proposed24hour interval. Independent restored-byte
verification succeeded for immutable collector segment00000270.sqlite(12,746,752bytes)
and experimental segment00000347.sqlite(4,505,600bytes), with matching raw/gzip SHA,
manifest/count and SQLite checks. These proofs do not authorize deletion.

Larger budgets substantially extend headroom but retain-all-originals still grows
linearly. Verified compression alone reclaims no space while originals remain.
A months-long lifecycle therefore remains dependent on explicit retention approval,
representative growth measurements and possible catalog/index design review. This
phase implements all non-destructive mechanics and keeps the decision visible.
