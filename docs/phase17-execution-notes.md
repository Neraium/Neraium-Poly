# Phase 17 execution economics and rejection research

This workstream adds research functions only. It changes no strategy, admission,
risk, broker, emergency stop, account, or certified approval record.

## Displayed-depth round trips

`research.phase17.economics.evaluate_roundtrip(decision, label, quantity=5,
fee_multiplier=1, slippage_per_leg=.01, latency_seconds=.1)` consumes the existing
Phase 16 causal-point contract. Both points must retain exact market/token/parent/
rule binding, source-frame and quote identities, metadata/book/fee hashes, qualified
producer evidence, nonfuture source/receipt times at most fifteen seconds old,
valid sorted top-three levels, tick-grid prices and exchange minimum lot evidence.
Only twenty-five percent of each observed level supports the modeled quantity.

The exit source must follow the predetermined sixty-second horizon plus the specified
latency, within the original thirty-second label tolerance. A late receipt cannot
turn a pre-horizon source quote into a label. A missing or early label is rejected;
no price interpolation, unchanged-quote outcome fabrication or liquidity invention
is permitted. Fee evidence is independently available at each corresponding cutoff,
at most 300 seconds old, on the public CLOB source, and bound to its canonical hash.

For fully supported depth the measurement is:

```
gross/share = observed future participating bid VWAP - decision participating ask VWAP
fees/share = multiplier * (entry VWAP * entry rate + exit VWAP * exit rate)
net/share = gross/share - fees/share - 2 * slippage_per_leg
```

Those are retrospective quote measurements. Future exit fees and depth must never
select a historical entry. The default fee rates are the archived conservative
notional bounds, not exact future exchange fee charges. Sensitivity scenarios are
labeled assumptions; a multiplier/slippage/latency below the default is not a new
production risk allowance. Price impact, spread crossing, decision spread, adverse
bid movement, observed capacity and partial unsupported quantity are exposed.
Unknown fees do not become zero and partial liquidity never becomes a full fill.

A deep sweep is separately labeled from the existing broker's best-limit capacity.
The common five-share mark is not always a $2–$5 wager: standard-principal eligibility
is reported separately. Higher quantities can be evaluated from actual depth, but
this helper grants no higher-conviction or exceptional allocation authority.

Two-point observations cannot verify that the decision ask survives the entry
submission latency. Consequently `entry_post_latency_verified`, `execution_certified`,
`actual_fill`, `trading_authority` and `certification_authority` remain false, and
`account_pnl` remains null even for positive measurements. Source hashes/identity
are structurally checked here; a source-replay verifier must independently bind the
points to native archive records before empirical results are reported.

## Rejection research

`summarize_rejections(rows, verify_row=None)` counts at most 10,000 supplied sampled
candidate rows, with nonexclusive reason categories and up to three representative
IDs per reason. Exact duplicates add no evidence. Conflicting payloads under the
same identity quarantine all copies. The caller must not extrapolate sampled counts
into population counts or combine them silently with cumulative trace counters.

A default-deny verifier must bind the original decision and matched future quote
(and reproduce the cost calculation) before retrospective net measurements are
shown. Missing source/label/fee/depth data yields null comparison metrics, not a
zero-profit trade. Positive hindsight marks do not demonstrate a restriction is
wrong, and negative marks do not prove a rejected order would have filled or that
its rejection causally prevented a loss. Threshold-change authority is always false.

## Phase 16 losing-trade review

The preserved native audit for market 6736353 / parent 1322448 records one existing,
unvalidated short-horizon BUY: 12.5 shares at $0.16 plus $0.10 modeled fee. The
post-horizon source-supported SELL at $0.07 returned $0.875 less $0.04375 fee, for
realized simulated P/L **-$1.26875**. All 23 existing audit checks passed; this
workstream found no evidence of an execution-control defect in that audit.

The original strategy is a trailing-twenty-bid median plus prior matured residual
bias. Its $0.31 forecast and $0.24 lower mark both missed the later observed $0.07
bid. The contemporaneous unchanged-bid baseline was $0.15: absolute errors 0.24
for the model and 0.08 for that baseline. A persistent downward repricing can make
a trailing-level reversion estimate obsolete. This is a testable model/regime-risk
hypothesis, not proof of causality, a guaranteed forecast failure rule or grounds
to change production thresholds. One trade establishes neither skill nor significance.

Useful prospective experiments include frozen momentum/unchanged-price comparisons,
predeclared volatility/activity/imbalance strata, and adverse-selection sensitivity
using only original source timestamps. Sample dependence and selection must be
handled in the statistical framework; this economics module does not claim an edge.

## Controlled verification

Tests cover unchanged quotes losing costs, positive hypothetical repricing without
fill claims, missing/mismatched identity and fee provenance, partial depth, sweeps
versus best-limit capacity, minimum lots/ticks, source/receipt ordering, stale data,
post-horizon latency, nonfinite assumptions, duplicate identities, default-deny
counterfactuals and unavailable source replay. Fixtures are never real observations.
