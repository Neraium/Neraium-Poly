# Phase 17 research findings

No statistically supported or economically executable advantage was established.
This finding is limited to the observed cohorts; it is not a claim that all
Polymarket markets are efficient or that no advantage can exist.

## Preregistered comparison

Protocol was frozen2026-11-06T23:57:32.313223UTC before the future validation and
held-out periods. Training ended at that cutoff, validation at00:02:32.313223,
and the future window ended00:12:32.313223UTC. Formulas were fixed before analysis:
unchanged participating bid, prior20-median reversion, clipped prior20-median
momentum and a fixed .01 depth-imbalance adjustment. No held-out parameter tuning,
model promotion or threshold change occurred.

The complete source chain contains181 authenticated Phase16 studies,21,557,788bytes,
1,094 accepted causal points and972 matured marks. Independently reconstructed
forecasts yielded816 matched rows;89 native fee observations were rebound to raw
public responses, token/condition membership and the conservative official fee curve.
The full ordered source window, not just endpoint hashes, was replayed to select
first eligible observed labels among retained study observations. The study cadence
does not claim every intervening exchange quote was sampled.

After90-second boundary purging and parent-level nonoverlap through actual label
knowledge, there were53training,6validation and20temporal held-out episodes.
628overlapping rows and109boundary/crossing-label rows were excluded. All three
held-out parent groups also occur in fitting periods; strict event-disjoint heldout
has **zero samples** and **zero reviewed independent groups**. Quote rows, tokens
and repeated forecasts are not independent events.

|Fixed candidate|Temporal held-out MAE USD/share|Unchanged-bid MAE|Selected cost-qualified cases|
|---|---:|---:|---:|
|Unchanged bid|0|0|0|
|Reversion20|0|0|0|
|Momentum20|0|0|0|
|Depth imbalance|0.004834|0|0|

Zero errors reflect static observed bid marks, not perfect forecasting skill.
There is no superior candidate; the simpler unchanged-price baseline ties two
challengers and outperforms imbalance. Fourteen held-out cases met displayed-depth,
minimum-lot and fixed-five-share standard-notional assumptions. Their unconditional
modeled after-cost quote mark averaged **-$0.088679/share**. No model met the frozen
predicted net-edge>=.03 rule. Selected net value, return variability and selected
unit-share drawdown remain **null**, rather than assigning performance to zero trades.

## Execution-cost sensitivity

Across813 structurally supported matched marks (not813 independent events or fills):

|Fee multiplier|Slippage per leg|Mean net quote mark/share|Positive marks|
|---:|---:|---:|---:|
|0|0|-$0.009375|0|
|1|$0.01|-$0.076542|0|
|1.5|$0.02|-$0.120126|0|
|2|$0.03|-$0.163709|0|

Three labels failed the post-latency source-window check. Hypothetical depth sweeps
are distinct from the existing best-limit broker. Entry quote survival after latency
is unverified in the two-point research dataset, so none is execution-certified.
Standard-notional eligibility is checked separately from fixed-five-share mark
measurement. A quote-mark sum or expectation is not account P/L, proof of fillability
or independently validated expected return. Selection uses only the decision-time
fee bound; later exit fees/depth are retrospective outcomes, never entry features.

## Sampling and microstructure

All816 matched examples had more than seven days to contract end. Spreads ranged
.001–.02 with median.01. Mean observed quote age was4.806seconds, maximum14.970seconds.
Static long-horizon contracts are an important limitation of the fixed cohort.

A separately retained00:17:22UTC broad-universe snapshot observed200markets,
400outcome tokens and94unreviewed parent groups. Of these,314tokens were active
before contract end,274had fresh valid two-sided books,218met both, and192passed
a preliminary$2–$5 displayed-depth sizing screen. Fees, forecasts, future liquidity,
resolution evidence and risk were not approved by this snapshot. Rejection counts
are nonexclusive. Source body SHA and original quotes are retained.

The eight-token/three-parent research cohort represents2%of monitored tokens and
cannot establish performance across94parents or all categories. No retrospective
reselection was performed after viewing these results. Public anonymous L2 does not
identify market-maker intent, queue priority or actual adverse-selection costs.

## Statistical uncertainty and outcomes

The framework implements parent-cluster bootstrap, paired cluster sign-randomization
and Holm correction for eight planned hypotheses. None was tested inferentially:
strict heldout has no reviewed independent groups, below the research requirement
of20reviewed clusters. Confidence intervals, pvalues and significance are **null**.
The20-cluster research rule does not replace certified100training/100held-out events.

Targets are monetary bid marks. Brier score and log loss are not applicable to these
targets. The separate independently resolved event-forecast cohort remains empty;
its calibration metrics are unavailable. Two existing NFL ternary forecasts remain
pending. Historical certification remains250groups/47corroborated settlements/
0fully qualifying training/0held-out events, with51official outcome groups distinct
from independently corroborated provenance. Missing historical rule vintages,
predecision availability, executable depth, reviewed independence, external context
and native settlement linkage remain blockers. No quote was converted into an outcome.

## Reproducibility and limitations

Artifacts, hashes, source IDs, preregistration, replay code and complete results are
under `.planning/evidence/phase17/research`; large raw frames remain in local
`data/phase17/capture` and original managed archives. Reproduction requires those
retained genuine source records. Forecasts in this offline replay are reconstructed
under a prospectively frozen hypothesis; they are not falsely labeled individually
committed prospective forecasts. The continuous service records new forecasts before
labels and separately exposes its operational progress.

Sampling, sparse independent events, incomplete entry latency evidence and absent
verified terminal outcomes preclude an advantage or profitability claim. Advanced
ML is not justified by this sample. Future experiments must use new preregistered
activity/horizon strata and parent-disjoint evidence rather than retuning this holdout.
