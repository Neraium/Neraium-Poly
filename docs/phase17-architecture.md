# Phase 17 empirical research architecture

The existing collector, Phase16 causal history, archive and paper risk/execution paths remain.
A research-only consumer reads committed Phase16 points and produces fixed challengers:
unchanged participating bid, prior20-median reversion, prior20-median momentum and .01-depth
imbalance. No model uses account profits, event outcomes or future quote labels as features.

Prospective forecasts are immutable EmpiricalResearchUpdate records in the existing managed
archive. Each binds original source study, feature IDs, actual creation time, observed quote
baseline and effective forecast lead. A nominal60second target measured from its source
decision point can have45–60seconds of lead after recording delay; this is disclosed.
The later first observed depth mark is matched by the original causal-history engine.
Neither a monetary mark nor a hypothetical book sweep is a verified event outcome or fill.

Each update carries a bounded lossless verified in-memory checkpoint. Ambiguous append
acknowledgements replay idempotently. Recovery rejects source-code or integrity changes and
never resets historical state. The original Phase16 checkpoint codec and code hashes remain
unchanged. Research errors withhold the research component; no new module can grant order,
risk, stop-reset or certification authority. Original strategies and risk limits are unchanged.

The evaluator separates purged chronological diagnostics from parent-event-disjoint heldout.
All tokens sharing a parent share a nonoverlap watermark extending through actual label
observation. Fixed model selection rules and all planned comparisons remain explicit;
cluster bootstrap and Holm correction require adequate reviewed independent parent groups.
Unavailable inference/calibration remain null. Research quote arithmetic is separate from
actual paper P/L, and entry quote survival after latency is never assumed proven.

ReadonlyArchive independently authenticates source index/payload hashes and recomputes
points from retained raw frames using short native read-only SQLite handles. Missing data
cannot receive substitute current quotes. Completed immutable segments support independent
raw/manifest/count/SQLite/gzip-roundtrip verification without modifying originals.

Storage sampling is bounded and restart-safe in the research checkpoint; existing64/16GiB
budgets and global floors remain enforced by ManagedEventStore. Capacity and retention-class
reports have no deletion or budget authority. All original evidence remains retained.

`uv run neraium-poly monitor --view edge` displays research progress, baselines, unavailable
inference, both paper balances and stop/configuration status on narrow terminals. An absent
or stale source cannot report fresh research or verified live-trading safeguards.
