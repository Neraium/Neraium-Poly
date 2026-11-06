# Phase 15 sustainable paper research

The collector and experimental account remain separate processes and storage roots.
The certified account requires the existing validation and explicit owner approval.
All new domain and relationship components have research authority only.

## Evidence lifecycle

ManagedEventStore owns append-only active SQLite segments. Rotation checkpoints and
closes a segment before publishing its immutable manifest. Completed raw segments
remain WARM. A deterministic gzip is published only after exact-byte recovery.
Phase 15 independently restores completed copies into a bounded 64 MiB derived
cache, runs SQLite quick_check and validates every payload, ID, timestamp, count and
global catalog entry. Immutable cold proofs identify all source hashes. Completed
verified representations are COLD; their original files remain present.

Managed historical queries and restart recovery support verified cold-only sources
for a possible future owner-approved retention batch. This is tested with controlled
fixtures. No production original was removed and there is no deletion API. Legacy
archives, catalogs, account databases, forecasts and audit journals remain protected.
Catalogs provide historical search by kind/time/ID and deterministic replay ordering.
See [the exact retention proposal](phase15-retention.md).

The collector retains its 64 GiB budget and the experimental service its 16 GiB
budget, including active/warm/cold/catalog/state/derived cache. Both retain their
64 GiB filesystem reserve, stronger than the global 8 GiB floor. Hard admission
fails closed; soft tier allocations and horizon alerts provide advance warning.
The bounded rolling growth estimator resets on restart and exposes an unknown
horizon until enough observations exist; durable byte accounting is rebuilt from
the filesystem. No infinite retention is claimed. Catalog growth continues even
if original raw retirement is later authorized, so compression alone cannot make
these budgets sustain months at the measured workload.

## Independent research

The universal domain contracts and existing NFL forecasts are preserved. New bounded
source acquisition includes official NWS provider precipitation probabilities,
Federal Reserve release context and public closed crypto candles. Mapping, semantics,
point-in-time availability and independent chronological calibration are separate
gates. Provider probabilities are not silently promoted into market forecasts.
Unsupported metrics stay null and all new operational authorizations remain false.

RelationshipResearch qualifies only shared-parent statistical graph candidates,
with exact raw metadata and quote hashes, source and availability cutoffs, half-spread
uncertainty, causal baselines and unchanged temporal persistence. It does not infer
logical exhaustiveness, causation or executable edge. ContinuousRelationships
appends bounded source frames, results and hashed checkpoints every 20 seconds to
the existing managed archive. Restart restores the latest committed study; failed
writes roll back the in-memory study. Experimental trading remains an independent
risk-controlled pathway and cannot consume this component as order authorization.

## Operations and recovery

`neraium-poly monitor --view operations` uses a compact loopback read-only endpoint,
without loading full historical event or order histories. It exposes source freshness,
archives and capacity alerts, domain progress, capability prerequisites and both
accounts. Missing or stale observations are labeled rather than shown as live.

Readiness assessment reads native SQLite snapshots and source evidence. The original
stop is preserved. Future storage stops atomically record bounded actor/reason/evidence
hashes. Invalid audit context cannot prevent activation of a stop; it cannot release
a stop. No reset endpoint or automatic model-promotion path was added.
