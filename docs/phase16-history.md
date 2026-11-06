# Phase 16 causal quote and relationship history

This module advances source and temporal evidence without granting execution,
forecast calibration or strategy certification authority. It does not modify either
paper account, the original strategy-code hash, any admission rule or risk limit.
Controlled tests use clearly labeled fixtures; no fixture is authentic market data.

## Causal observation contract

`CausalHistory.observe(frame, now=...)` accepts existing JSON MarketSnapshot and
OrderBookSnapshot records. It returns newly accepted compact `accepted` points,
newly `matured` pairs and a coverage summary. `points(token=None)` and `matured()`
return bounded deep copies. `checkpoint()` / `restore()` preserve current history,
label decisions, missingness and cumulative counters. The caller must persist the
original frames, append-only study records and independently hashed checkpoints;
this module owns no database or filesystem writer.

Metadata must come from the declared Gamma origin, match the quote's market,
exchange and outcome token, have available resolution rules/source, and be active
with no passed end time. Both metadata clocks must precede the decision cutoff.
Fresh complete two-sided public CLOB/market-WebSocket quotes are required. Source
and receipt must be no older than15seconds, spreads no wider than$0.05 and all
clock/identity checks must pass. Missing/crossed/incomplete/mismatched/duplicate or
out-of-order data do not add history. Repeated exact quotes do not create apparent
sample growth or persistence. A reused quote ID with changed contents is rejected.

Each point records:

- Original quote/metadata identities and SHA-256, market/token/parent IDs, source,
  source event time, receipt availability and actual observation cutoff.
- A hash of question, rules, resolution source, outcome, close time, tick size and
  minimum order quantity; changed context starts a new history epoch.
- Best bid/ask, spread, actual top-three bid/ask levels, their observed depth and
  imbalance. Fixed5-share bid/ask VWAPs use at most25% of each observed level;
  insufficient depth remains null. No deeper liquidity is inferred.
- A qualified public CLOB fee observation, its source/time/reference and hash when
  available. This is structural source/time qualification, not exchange-signed
  authenticity. Raw response replay remains the evaluator's responsibility.
- Explicit missingness. Unknown producer health, absent original frame ID, missing
  fees, insufficient top-three depth or an exchange minimum above5shares prevent
  `execution_evidence_complete`. An archived authentic quote can still support
  descriptive mark research when the old archive omitted producer health. Missing
  health is never invented as healthy.

Selection retains established fresh histories and ranks new tokens by current
observed two-sided depth. Future outcomes and hindsight performance are not
selection inputs. A source gap exceeding120seconds or changed contract semantics
starts a new causal epoch. That discards only a bounded memory cache; the caller's
immutable archived studies remain the original evidence.

## Matured targets are marks, not outcomes or fills

A decision cutoff is when the caller actually observed the frame. Its target is
60seconds later. The first qualifying future source quote must be at/after that
target and within30seconds, with its own source and receipt already available at
the scoring cutoff. Receipt time alone cannot substitute for future source time.
No interpolation, current-price replacement or selection of a later favorable
quote repairs a missed label. The first eligible mark with insufficient depth is
withheld rather than replaced with a later liquid observation.

The target and unchanged-bid baseline are observed fixed5-share top-three depth
bid marks. They are USD/share, not event-outcome probabilities, actual executions,
settlements, independent events or certified trading profit. Features, forecasts,
fees and labels must still be separately replayed by the model evaluator. Both
source and availability cutoffs are retained in the mature pair.

Per-token summaries report observation count/span, maximum retained gap, current
missingness and matured labels matching the current context/window. Old epochs
cannot qualify a new window by contributing stale label counts. Aggregate parent
counts are explicitly not independently reviewed event counts. Independent final
outcome events remain zero in this quote module; it cannot satisfy100training plus
100held-out event certification requirements.

Defaults are8tokens,240points per token and512retained mark pairs. Token/row/label
configuration, input frame size, metadata size and checkpoint bytes are bounded.
Restoration validates ordering, source/availability/cutoff, context bindings,
VWAPs, fee bindings, cumulative versus retained counts and denial of trading
claims. Whole-checkpoint hash verification is required in the caller. Raw frames
remain external provenance; compact hashes are not a substitute for raw replay.
Full checkpoints can be several MiB. Do not append them uncompressed every cycle:
measure lossless checkpoint encoding or use a durable checkpoint/delta replay
scheme within the existing service budget. No retention deletion is introduced.

## Versioned relationship research graph

`RelationshipHistory.observe(frame, now=...)` wraps the existing Phase15 source
validator and Phase14 joint relationship engine. Both sides need at least3distinct
causal source observations spanning60seconds before graph selection. Existing
stable pairs retain their causal baselines. New pairs are ranked by observed
history completeness and two-sided depth, at most one pair per metadata parent.
The default graph retains3pairs, with bounded selection coverage.

Pairs retire when a contract closes/ends, semantics change, or a pair is absent
from the observed universe for120seconds. A short stale-book interval alone does
not retire a pair. Retirement records preserve definition, source proofs, prior
joint state, reason, time, graph version and their hash. The bounded32-entry memory
ring is not the historical archive: every study checkpoint must be archived by
the caller before the oldest cache entry can age out. Reintroduced pairs require
new warmup rather than silently restoring an old regime's baseline.

The original engine still requires10baseline observations, at least3persistent
observations and60seconds persistence, joint relationship change beyond residual
and spread uncertainty, and source/provenance verification. The graph establishes
only shared-parent statistical research eligibility. It does not assert logical
exclusivity, exhaustive payoffs, causal relationships, predictive superiority or
executable arbitrage. Those claim counters remain denied. Matured mark comparisons
and independently held-out evidence are separate prerequisites, never automatic
trading authority.

## Verification

Controlled regressions cover source and receipt time, availability cutoffs,
future/ended contracts, mismatched IDs, missing rules/producer/fees, duplicate and
changed quotes, first-label timing, missed labels, participating top-three depth,
source gaps, context epochs, memory bounds, deterministic restart, malformed
checkpoints, causal graph selection, inactive/absent retirement, graph versioning,
retirement-provenance corruption and unchanged persistence thresholds.
