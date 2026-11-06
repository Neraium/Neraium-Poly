# Phase10 strategy decision evidence

Inspection: 2026-11-06 UTC. Strategy investigation and implementation ran in
`citadel/poly-phase10-strategy`, isolated from the service checkout. No bankroll,
certified account, risk threshold, or running service was changed by this worker.
The MCP orientation resolved the coordinator checkout; source edits and tests ran
in the assigned isolated worktree. Parent coordinates the native Citadel campaign.

## Observed zero-trade causes

The read-only experimental archive `data/experimental-paper/events.sqlite`, fixed
at rowid 60811, contains 1079 cycles from 02:34:54.302792Z to 04:16:37.900112Z.
All cycles together report **zero eligible signals**. This is not evidence that
risk or execution rejected orders: these signals never reached admission.

Nonexclusive emitted-signal rejection counts in that prefix:

| Reason | Count | Classification |
|---|---:|---|
| Conservative roundtrip edge insufficient | 77598 | MARKET CONDITION |
| Persistent contextual relationship evidence required | 51504 | MISSING EVIDENCE |
| Unknown fee schedule | 28230 | MISSING EVIDENCE |
| Stale book | 23694 | MISSING EVIDENCE |
| Missing book | 17382 | MISSING EVIDENCE |
| Insufficient causal bid history | 12042 | MISSING EVIDENCE |
| Missing liquidity | 2856 | MISSING EVIDENCE |
| Insufficient matured horizon errors | 1910 | MISSING EVIDENCE |
| Out-of-order book | 24 | MISSING EVIDENCE |

Cross-market consistency requires independently reviewed exhaustive payoff scope
and unsupported multi-leg execution; each reason occurred 51504 times. Liquidity
spread requires a queue/adverse-selection model and unsupported two-sided
inventory execution; each occurred 51504 times. Event driven lacks independent
predecision context/response modeling (51504). Calibrated forecasting lacks
independent context, verified labels and calibration (51504). These four registered
candidates are not implemented order-entry capabilities. Registration is not
certification or a promise of trading activity.

The latest 1000 relationship records inspected at approximately 04:16 UTC had zero
qualified findings: 700 insufficient baseline, 202 reused observations, 202
out-of-order observations, and 98 no material relationship change. Reasons overlap;
these are a bounded recent sample, not independent events. Source timestamps that
fail to advance cannot legitimately increment persistence. A descriptive SII
finding would still not prove profitable repricing.

## Cost and causal-model review

The short-horizon model fits a trailing 20-bid median plus median matured residual,
with current quote excluded. Each residual label must mature after its decision
availability time plus 60 seconds; labels and all inputs must be available by the
current evaluation. Minimum history/errors and maximum gaps remain unchanged.
The empirical 90th-percentile envelope with $.01 floor is explicitly unvalidated;
it is not calibrated probability coverage. Exit target is a bid mark, not a
terminal settlement probability. Spread is paid by entering at the ask.

Existing admission edge is
`lower_bid_target*(1-fee_bound) - entry_ask*(1+fee_bound) - .02`.
The global notional fee bound matches the actual paper broker's fee assumption.
Replacing just strategy fees with an exact curve would overstate admitted edge
relative to broker costs. No such replacement was made.

The same fixed archive prefix contains 6474 unique representative rejections,
including 1010 numerical short-horizon signals. Their edge range was -$.123 to
-$.041/share; conservative pre-cost edge range was -$.045 to approximately zero
(median -$.02). Median roundtrip fee bound was $.0182/share. A diagnostic-only
counterfactual `lower-ask-r*(lower*(1-lower)+ask*(1-ask))-.02` ranged from
-$.07610725 to -$.03785, with zero passing the unchanged $.03 threshold. The
entry ask here is recovered algebraically from archived edge/fee/lower inputs,
not claimed as a reconstructed historical executable order book. This selected
sample is biased toward representative rejections; it cannot estimate universe
opportunity frequency, fill rate, or false-positive rate. False positives and
execution P/L remain null without qualifying signals and causal outcome evidence.

Reproduction: open SQLite with `mode=ro`; select `ExperimentalCycle` payload and
digest where rowid <= 60811; verify SHA256 of each payload; sum `eligible_count`
and `rejection_counts`; deduplicate `representative_rejections` by signal ID;
filter numerical `short_horizon` records. Recover ask as
`(lower*(1-rate)-.02-estimated_net_edge)/(1+rate)`. All metrics above derive only
from authentic archived records. Controlled test fixtures do not enter them.

## Counters and persistence

`engine.last_trace` reports every token/strategy evaluation before signature
deduplication. `valid_observations` means market/book operational checks passed;
fee and model/context prerequisites remain separate. `candidate_signals` requires
valid data, current verified fee input, numerical valuation and strategy-specific
evidence before cost/uncertainty gates. `qualified_opportunities` is before risk.
Unchanged signatures count as considered/valid/candidate/rejected where applicable,
but increment `duplicate_signals` and produce no new signal or order.

`DecisionTrace.status()` contains `phase10_epoch.strategies` and
`latest_cycle.strategies`, with frozen STAGES, emitted/duplicate counts and
nonexclusive categorized reasons with at most three representative samples.
The epoch is persisted across restart; latest cycle replaces on engine evaluation.
Old Phase9 `signal_counts` continue to mean cumulative newly emitted signatures.
No pre-Phase10 evaluation counters are invented. Admission attempts require an
actual intent/risk attempt; qualified signals do not imply attempted orders.
Partial-fill events count once each, with separate entry/exit counts. Expiration
and cancellation require explicit execution events. Recent 8192 admission/execution
IDs survive restart for bounded diagnostic idempotency; broker persistence remains
the authoritative lifetime order-idempotency mechanism.

Diagnostic data never authorizes trades. Source changes alter the existing
strategy code hash. Integration must explicitly archive the old research baseline
and migrate the model checkpoint with an audit record, preserving bankroll, orders,
positions, risk state and historical evidence. Silent hash replacement is invalid.

## Verification

Controlled tests verify pre-dedup counters, cost decomposition, structural/data
candidate gates, bounded samples, duplicate admission/fill events, checkpoint
restore and invalid checkpoint rejection. `pytest tests/test_phase10_trace.py
 tests/test_experimental_strategies.py -q`: 25 passed; scoped Ruff check passed.
This worker used one local pytest process; it did not run parallel CPU backtests.
The coordinator records actual overlapping agents/processes separately.
