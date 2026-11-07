# Phase 23 independent models

Implemented four research-only challengers in phase23/models.py, sources.py and continuous.py:
- Gaussian first-passage with future-window starting-price integration.
- Empirical joint OHLC moving-block bootstrap, preserving intrabar lows and 15-minute dependence;512paths.
- NFL Davidson team strength with explicit win/tie/loss probabilities.
- Existing independently trained NFL ternary frequency as a contemporaneous competitor.

Exact daily-low contract interpretation extends existing unchanged Binance rules to future local-day windows up to72hours. No terminal-close ambiguity bypass. Native source byte/hash/timestamp replay, complete elapsed windows and fresh two-sided depth are required. Numeric estimates are uncalibrated with explicit[0,1] uncertainty and no trading/certification authority. NFL win probability is distinct from expected payout under half-payoff ties; the existing NFL Elo gate remains unchanged.

ChallengerResearch(store,clock=None,can_write=None) exposes async step(frame) and status(). Two source groups collected concurrently per300s, at most16crypto contracts plus8sports contracts; same model/parent/market/token/horizon is durably deduplicated. Immutable enrollment+versioned code hashes and restart-checked compressed checkpoints live in ChallengerStudy records in existing managed archive. Append failure does not advance state. Reference-hashed NFL originals remain in existing sources; no databases moved or modified. Runtime auto-discovers managedstore.directory/event-intelligence/sports/sources; optional sports_directory supports controlled/isolated experiments.

Authentic isolated experiment:8prospective forecasts,3parent events across crypto/sports. Gaussian3/bootstrap3/Davidson1/frequency1. NFL models used553causal historical games. Full original source bytes, rules/books and timestamps are in worker data/phase23/authentic-records.json; compact hash and predictions in authentic-prospective-summary.json. These are isolated research records, NOT production paper trades or certified performance. No resolved labels, calibration, edge or profitability established. Source inputs within each model pair are shared, not independent corroboration. Source selection did not force stale/illiquid contracts.

Verification:13focused tests passed; Ruff passed. Fixtures cover causal/future input rejection, exact future-day mapping, model reproducibility, no hidden market-price features, complement semantics, immutable enrollment/restart dedup, actual2source concurrency, depth/source failures, budget rejection, disk-full state preservation, NFLties and unchangedElo gate. All fixture results are controlled engineering verification only.

Coordinator owns outcome adapter/scheduler: forecast_models(contract,evidence,cutoff) replays crypto model outputs; bind evidence by forecast.evidence_ids, exact contract and forecast cutoff. For NFL preserve outcome_distribution semantics and source_reference; no binary scoring or marketwin baseline inferred from payoutquote. No auto promotion.
