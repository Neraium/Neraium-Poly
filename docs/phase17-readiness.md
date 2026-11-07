# Phase 17 readiness and executive delivery

Observed **2026-11-07T00:27:17.074995+00:00**. Source integrated/pushed to main:
`362d58f` (latest monitor recovery fix), deployed research core `49cd0b0`.
Final documentation/evidence commit follows. **No statistically supported,
economically executable or repeatable advantage was established.**

## What changed

The existing Phase16 causal-history/archive pipeline now feeds a bounded prospective
four-candidate research evaluator. Forecast records bind original source studies,
feature IDs, actual creation times and effective lead times. Matured observed bid
marks are scored against unchanged prices. Scores, drift and inferred profitability
remain distinct; new research models have no order/certification/threshold authority.
Models never train on account P/L. The original strategy and intelligence source hashes,
risk limits, certified gate and Phase16 recovery code are unchanged.

Added depth-walk fee/slippage/latency economics, strict raw-source/point/parent-chain
verification, purged parent-aware evaluation, dependence-aware bootstrap/Holm machinery,
non-destructive capacity/retention reports and `monitor --view edge`.
A reviewed defect in parent episode exclusion was fixed to include actual label-observed
time. A reviewed performance defect was fixed by caching history/ID maps once per update.
After a genuine producer-degraded cycle, a monitor regression was fixed so recent metrics
cannot hide degraded experimental health. No gate was loosened.

## Research results

A preregistered future-window experiment authenticated181studies,1,094causal points,
972matured pairs and89native fee observations. It yielded816matched model/label rows.
Purging/nonoverlap left53training,6validation and20temporal held-out episodes.
Strict event-disjoint heldout **0**; reviewed independent groups **0**.

Unchanged bid, reversion20 and momentum20 all had MAE0 on static held-out marks;
imbalance MAE0.004834 was worse. There is no superior candidate. All four selected
**zero** cases under the fixedafter-cost.03threshold. Fourteen depth/minlot/standard-
notional-compatible held-out examples averaged-$0.088679/share in hypothetical quote
arithmetic. Across813matched quote cases, mean after-cost mark was-$0.076542/share;
none was positive, even with fees/slippage removed. Entry quote survival after latency
is unverified, so these are not fills or execution-certified returns.

Bootstrap confidence intervals and multiplicity-adjusted significance are unavailable
because the reviewed event-disjoint sample is empty. Brier/log loss are not applicable
to monetary targets; independently resolved event forecasts are separately insufficient.
No strategy was selected/promoted. All816examples had>7days to expiry; the eight-token/
three-parent cohort is too narrow to generalize to the200markets/94parents observed in
a separate broad snapshot. See phase17-research-findings.md for full methodology/results.

The independent Phase16signal audit found modelMAE0.201818 versus baseline0.05 across
11overlapping signals in one event episode;0/11future marks were inside forecast bands.
Even the largest positive gross crossed-quote mark.02/share failed the unchanged
slippage assumption before fees. This is a negative model/regime finding, not a
profitability claim or proof that rejected orders would fill.

## Actual paper performance and capital preservation

|Metric|Phase17 change|Observed lifetime/current|
|---|---:|---:|
|Qualified emitted experimental signals|0|16|
|Order intent attempts|0|6|
|BUY orders submitted|0|1|
|BUY fill events|0|1|
|Horizon SELL fill events|0|1|
|Realized simulated P/L|$0.00000|$-1.26875|
|Experimental cash/equity|$0.00000|$498.73125|
|Open positions / reservations / exposure|0|0 / $0 / $0|
|Certified cash / P/L|unchanged|$500 / $0|

Both initial bankrolls remain$500. Experimental equity reflects the existing Phase16
loss; it was not reset. Lifetime6intent attempts include5old stop rejections plus1old
risk-approved BUY;16qualified signals include5old stop-rejected and11later legacy
signals. No new Phase17paper trades or profits were fabricated. The completed roundtrip
is one BUY and one SELL, not two independent profitable trades. Tiny unrealized residual
~1e-14 is zero within1e-9floating tolerance. Ledger reconciliation is consistent.

## Live deployment and observation

Only experimental was restarted, PID3226049; collectorPID3185204 stayed running.
Both active, zero automatic restarts. Both actual process flags verified
PAPER_TRADING=true and LIVE_TRADING_ENABLED=false. Certified approval remains
`validation_blocked`; emergency stop remains clear, with **no reset in this phase**.
Existing20%aggregate exposure, sizing, correlation, daily-loss and drawdown controls remain.

Observed for **606.2seconds**,00:17:00–00:27:00UTC,
31samples,**30/31fully healthy**. One experimental sample was
degraded after00:19:17producer-degraded rejection; collection recovered next cycle at
00:19:24without relaxing the fail-closed gate. No order was admitted during that rejection.
Raw failed samples/log evidence remain. Some five-second CLI requests also timed out;
they displayed unavailable/config-unverified warnings rather than invented balances.
Subsequent requests and final monitor rendering recovered. This is bounded recovery
evidence, not a claim of uninterrupted or indefinite availability.

Final monitored markets **200**, subscribed tokens400. Fresh books ranged
260–326; final **295**.
WebSocket connected and genuine source/receipt timestamps retained.

The live research consumer recorded **88prospective point forecasts**
(each with four fixed candidates), **75matched point labels**,
11pending and2expired without fabricated scores,
across3unreviewed parents. These are monetary research
forecasts, not independent event-outcome forecasts. New formal certification events0.
Research last_error is null. Individual forecasts have45–60second effective lead
relative to the retained60second source-decision target; creation lag is recorded.

## Integrity, recovery and storage

All **796baseline immutable files** and existing forecast-
journal prefixes passed integrity checks. A separate scan verified
**848current immutable files**. Risk/broker SQLite
checks passed; certified tables, experimental registry and append-only account audit
prefixes were preserved. Original forecasts, fills, settlements and raw sources remain.

Independent read-only recovery replayed64Phase16studies and restored the Phase17
checkpoint to exact stored hashes; no live store owner, source rewrite or extra restart.
Controlled tests also cover ambiguous committed writes, corruption, gaps and restart stop
preservation. A baseline helper reused an older derived scratch-output path once;
the fresh report was copied into Phase17 and the incident recorded. Original native
archives/journals and checked-in Phase16recovery evidence were unchanged.

Available filesystem capacity: **473.02GiB**.
Global reserve64GiB, service budgets unchanged. Ten-minute provisional measurements:

|Service|Usage bytes|Budget bytes|Net retained B/s|Conditional days to cap|
|---|---:|---:|---:|---:|
|collector|8,314,127,839|68,719,476,736|116136.1|6.02|
|experimental|2,729,686,596|17,179,869,184|64306.6|2.60|

The3.34-hour estimate was113,495/55,704B/s and6.17/3.01days. Different provisional
windows/allocation jumps explain different runways; neither is representative24-hour
or seven-day evidence. No months-of-operation guarantee. Existing managed backpressure
bounds consumption by withholding collection before service/filesystem limits.
Long-term all-originals retention remains approval-dependent. Compression adds a
verified copy, not authorized removal. No data deletion, destructive compaction,
retention change, budget increase, AWS resource or spending occurred.

## Historical evidence and qualification

Historical250groups/51official-outcome groups/47corroborated settlement groups.
Historical executable depth, point-in-time evidence and reviewed independent grouping
remain insufficient;0fully qualified training and0heldout, required100/100unchanged.
Native settlement provenance gaps remain; no temporary/terminal quote became a resolved
label. Existing two independent NFL ternary forecasts remain pending in their separate
ledger. Broader event baseline forecasts are market baselines, not independent skill.

## Verification and actual parallelism

Final **GitHubCI:1,119backend tests passed**, frontend build and5browser cases passed,
Ruff and dependency audits passed. Local full backend:1,118tests across two overlapping
workers; final monitor health regression:20focused tests. No repeated full local suite
was needed for that monitor-only change; final CI ran the complete source tree.
A Starlette test-client deprecation warning remains. Fixtures are not market evidence.

SourceCI onmain:
https://github.com/Neraium/Neraium-Poly/actions/runs/42317888416
Research-coreCI:
https://github.com/Neraium/Neraium-Poly/actions/runs/42317106608
Feature finalCI:
https://github.com/Neraium/Neraium-Poly/actions/runs/42317723023

Peak4agents includingcoordinator;3isolatedwritingworktrees, no shared writers.
Five requested research areas were covered by A:economics+strategydiagnostics,
B:models/statistics, C:provenance+storage, and coordinator integration.
Local tests used2concurrent processes. Replay/capacity analysis used2actual concurrent
processes, overlap~0.33seconds; replay consumed28.33CPUseconds, capacity0.035CPUseconds.
This is not a claim of two saturated CPUs or32workers. Original1/.5CPUservicequotas
remain. Resource and PID evidence is versioned.

## Remaining blockers and Phase18 priorities

1. Preregister broader independent parent/activity/horizon strata. The current static
   long-horizon cohort cannot test transient-event forecasting or generalize globally.
   Preserve old experiments and checkpoint compatibility when expanding research coverage.
2. Acquire independently verified outcomes, historical rule vintages, native settlement
   transaction provenance and truly predecision external context; review event dependencies.
   Collect100training/100held-out qualified independent events before certified approval.
3. Study regime-break failure of the existing short-horizon model using a NEW holdout,
   realistic source latency/entry survival, and unchanged-price baselines. Any proposed
   production threshold or strategy change requires separate approval.
4. Measure24-hour/seven-day retained growth. Obtain an exact owner-reviewed retention
   decision or shared-capacity proposal before current budgets saturate. No originals
   are removable under this phase. Cache-only savings cannot solve months of growth.
5. Continue prospective challenger scoring and investigate source/monitor latency tails;
   keep source-degraded withholding, historical immutability and no automatic promotion.

Required architecture, research findings, strategy evaluation and storage/reliability
reports are adjacent to this file. Detailed evidence and reproducible source manifests
are under `.planning/evidence/phase17`; larger original captures remain local and preserved.
