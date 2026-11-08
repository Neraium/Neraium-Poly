# Phase 26 incremental research index

Scope: source-anchored derived P23/P24/P25 competition metadata; no production changes.

`ResearchIndex(path, source_directory=..., readonly=False)` owns its SQLite projection; `step(store, as_of=..., forecast_verifier=..., outcome_verifier=..., max_records=32, max_bytes=16*1024**2)` advances bounded original-catalog rowid work. `report(as_of=...)` publishes complete indexed counts with explicit bootstrap status. `close()` releases the cache. Readonly CLI uses the same path with `readonly=True` and cannot ingest.

Forecast callback `(original_study, forecast, as_of=...)` must replay native original source and frozen model; only literal `{'verified': True, ...}` succeeds. Outcome callback `(original_outcome_study, original_forecast)` must return literal verified True, exact forecast_id/event_id/market_id/token_id/rules_sha256, resolved_at, available_at, plus native terminal proof. Missing callbacks never authorize flags. Temporary evidence OSError aborts/retries the batch.

Original archive receives immutable ResearchProjectionAnchor records only through the supplied owner store. Each anchors source cursor/id/raw SHA, cache content-addressed chain, entry count, and projection implementation SHA. Cache-first commit interruption leaves unpublished orphan branches. Reports verify original anchor, chain hashes, and batched original-catalog witnesses; full integrity scanning remains separate. Existing cache/source/path/policy rebinding rejects; code-policy changes require an explicit new cache generation.

Memory limits: 32 source records/16 MiB per default step, 50,000 compact entries/64 MiB metadata fail-closed inventory bound, 2 MiB SQLite cache; original source/model replay occurs only on new records. Reports omit full books/raw training arrays. Model declarations remain visible with zero forecasts; duplicate IDs conflict, source identity conflict, unsupported outcomes, SII flags and uncalibrated predictions cannot create calibrated or certified metrics.

Validation: 19 controlled engineering tests passed in 2.99s, Ruff passed. Includes interrupted anchor, corruption with recomputed local checksums, retries, readonly, source/path binding, temporal integrity, declared-model requirement, outcome proof, no promotion. Fixtures are not genuine market forecasts/performance. No production archive writes or live benchmark performed by this agent.
