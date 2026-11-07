# Phase 17 storage and reliability

Existing managed archives retain their hard64GiBcollector and16GiBexperimental
budgets. The global64GiBreserve remains, stricter than the8GiBminimum. No original,
account record, journal, repository or unrelated project was removed or compacted;
no paid infrastructure or budget increase was introduced.

## Measured capacity

A native-service measurement through2026-11-07T00:13:55UTC spans approximately
12,019seconds (3.34hours), not a representative24hours:

|Service|Usage bytes|Budget bytes|Net retained growth B/s|Conditional remaining days|
|---|---:|---:|---:|---:|
|Collector|8,221,798,297|68,719,476,736|113,495|6.17|
|Experimental|2,685,388,876|17,179,869,184|55,704|3.01|

The final ten-minute post-deployment measurement is in phase17-readiness.md and
operation.json. Rates include raw segments, additional gzip copies, catalog/index
and restart state, metadata, derived caches and allocation jumps. Free capacity
also changes with unrelated workloads; per-service growth is not total host growth.
No short soak proves indefinite or monthly unattended operation.

## Implemented non-destructive components

* Pure bounded storage-growth analysis uses up to1,008ordered observations, rejects
  future/non-increasing/stale evidence, requires at least five minutes to estimate
  positive growth, and never reports missing/negative growth as infinite runway.
* The continuous research checkpoint persists at most128capacity samples. Warnings,
  remaining headroom, proposed-write effects and filesystem floors survive restarts.
* Retention classes distinguish ACTIVE open SQLite/WAL, WARM immutable originals,
  COLD verified additional compressed representations, PROTECTED accounts/forecasts/
  catalogs/manifests, and DERIVED caches with retained recovery sources.
* ReadonlyArchive verifies source payload/index binding and complete parent chains
  through short-lived native read-only handles, with record/query/byte limits.
* Immutable segment verification checks manifest, raw SHA, row count, SQLite
  integrity and bounded streamed gzip roundtrip. No active database is compressed,
  replaced, moved, extracted or rewritten.
* New research uses the existing archive and bounded verified in-memory gzip
  checkpoints; it does not create another collector or an unbounded prediction DB.
  Each update preserves raw forecasts, labels and provenance before advancing state.
  Ambiguous writes replay idempotently; failed writes roll back volatile state.

The independent genuine audit verified eight studies,50recomputed points and
experimental segment00000212.sqlite:4,263,936bytes, raw SHA
`90bbfa7f17ba0d48fbb61a6faee57bf38b334e61cdbdb8251e84f1a7eb06e54e`.
Its compressed copy restored byte-for-byte without modifying originals. Final
source/account/journal and checkpoint recovery evidence accompanies the readiness report.

## Limits and approval-dependent decision

All-originals retention grows linearly. Lossless gzip adds a recoverable copy but
reclaims no space while originals remain. Phase16 bounded preview ratios of.2354
collector/.3045experimental at level6 were already lossless; re-running compression
cannot turn that into authorized original deletion. The live derived cache tier is
bounded and reproducible only with verified source copies; its measured size is
shown in the capacity records. Even reclaiming such caches buys minutes, not months.
No cache was deleted to conceal the growth problem.

The existing hard budgets provide safe backpressure rather than silent evidence
loss. The remaining decision is an owner-approved retention class/window and an
exact hash-listed batch of eligible completed originals, with independently verified
compressed completeness, successful restoration, provenance manifests and no active
references. That approval does not exist. Newly completed warm segments must not be
retired merely to extend this phase's runway; protected legacy/account evidence
requires its own explicit decision. Any future batch must be generated and rechecked
at approval time. This phase grants no removal authority.

Alternatively, an internal-capacity proposal must explicitly reserve capacity for
other workloads and retain filesystem floors; it must use representative24-hour and
seven-day rates. Existing budgets are not raised on a3-hour estimate. No new AWS
resources or spending is authorized or necessary for the implemented components.

## Operational recovery

Only the approved experimental service was restarted; the collector remained running.
Existing Phase16 checkpoint policy/source hashes and production strategy guards are
unchanged. New research recovery rejects mismatched code, corrupted checkpoints,
inconsistent identity/timestamps and excess bounds rather than resetting records.
Stops are never cleared. A producer-degraded cycle was safely withheld during the
bounded soak and recovered on the next cycle; it is reported, not erased from health
statistics. The monitor now withholds current research scores when the experimental
service is degraded, even if its previous metric timestamp is recent.

Unit/integration regressions cover crash/ambiguous acknowledgement, corruption,
missing depth/fees, unavailable storage, proposed disk-full writes, restart isolation,
causal labeling, parent-chain gaps and narrow terminal warnings. Fixtures are not
market evidence. Long-term capacity remains an explicit approval-dependent blocker.
