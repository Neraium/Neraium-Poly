# Phase 18 retention proposal — not authorized for removal

The effective policy remains **retain all historical originals**. Phase 18 adds only
hash-bound dry-run and audit plans; there is no deletion implementation or activation
flag. No original, journal, account, settlement, repository or unrelated file was removed.

Proposed eligible class: `proposed_raw_after_verified_cold`. A sealed original must have
spent at least86,400 seconds in warm storage, retain its immutable manifest/catalog record,
and have an unchanged independently verified gzip copy. A successful restored SQLite
integrity check and exact record-ID/catalog completeness proof are mandatory. Re-run
raw/gzip hashes, restoration and complete active-process FD/mapping checks at action time.
Unknown/inaccessible reference scans fail closed. Restored readers must deterministically
recover the same IDs and bytes. A compressed copy on this root volume is not an off-host
backup or protection from volume loss.

Protected forever by this proposal: active SQLite/WAL, legacy evidence, forecast journals,
settlements, account records, provenance manifests, searchable catalogs/indexes and audit
histories. No active SQLite file is moved, replaced, compressed or truncated. Compression
operates only on completed immutable segments through the existing crash-safe lifecycle.

**Separate owner decision required:** review a fresh exact proposal hash, list of original
paths and bytes, raw/gzip hashes, successful restoration/completeness proofs, retention
class/age and current process-reference audit. Authorize those named redundant originals
explicitly before any irreversible action can be developed or executed. Phase 18 does not
supply that authorization. Plans are bounded and paginated, not unrestricted filesystem
cleanup.

The2026-11-07T04:22:17 UTC audit covered both current catalogs without inventory truncation.
It found zero review-ready originals under the proposed24 hour minimum. Therefore no exact
removal is requested now. A future plan must be generated after the age/proof conditions
are met. Capacity exhaustion continues to fail closed; retention proposals do not disable
storage backpressure or the protected100 GiBfree-space floor.

At observed sub-day net growth,200/100 GiBbuy approximately20 days, not months. Verified
compression already coexists with retained originals. Sustainable months require a later
approved redundant-original policy, measured catalog/journal growth and evidence-preserving
cold-only read/recovery validation. No extra paid storage or AWS modification is implied.
