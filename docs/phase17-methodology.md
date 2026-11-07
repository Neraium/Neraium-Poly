# Phase 17 frozen quote-mark methodology

These modules test monetary bid-mark hypotheses. They do not implement independent
terminal-event forecasts, grant trading authority, or change existing strategies.
All unit examples are controlled fixtures and are not authentic observations.

## Predeclared candidate family

`causal_forecasts(points, cutoff=...)` consumes bounded Phase16 CausalHistory points.
Each prediction requires twenty strictly prior, valid, available points for the same
token/market/parent/rules context. Current points are excluded from the twenty-point
window. Source gaps over 120 seconds or contract context changes start a new window.
Future, stale, incomplete and conflicting quote identities cannot contribute features.

All coefficients and formulas are fixed before the prospective experiment:

|Candidate|Prediction in USD per outcome share|
|---|---|
|`unchanged`|Current participating-depth bid|
|`reversion20`|Median of twenty prior participating-depth bids|
|`momentum20`|Current bid + (current bid − prior median), clipped to [0,1]|
|`depthimbalance`|Current bid + 0.01 × current observed depth imbalance, clipped to [0,1]|

No labels are inputs and no parameters are fitted to validation or held-out results.
Current market quotes are explicitly used: these models are not advertised as independent
probability forecasts. Reconstructed predictions are labeled as such. The coordinator
may separately append a prediction before maturation; reconstruction alone does not
prove that a forecast was committed prospectively.

Outputs include the original decision point ID, feature IDs/hashes, cutoff, fixed model
and feature versions, predictions, and a provenance boundary requiring caller raw replay.
No uncertainty interval is fabricated from these uncalibrated monetary-mark hypotheses.

## Evaluation contract and authenticity boundary

`evaluate_experiments(rows, training_end=..., validation_end=..., cutoff=...,
verify_row=...)` accepts up to 20,000 JSON rows and 32 MiB. The verifier defaults to
deny; it must independently bind original point and label records, model features,
quote/cost calculations and any asserted independence review to authentic source
records. A supplied `True` or source URL is not that proof. Verifier exceptions reject.

Required row keys are `id`, `event_id`, `token_id`, `decision_at`, `target_at`,
`label_available_at`, `actual_bid`, `baseline`, and all four named `forecasts`.
Supply `label_at` and `label_observed_at` to preserve original source and observation
cutoffs. Labels must target decision+60 seconds; a supplied label source must be
within the observed target+30-second window. Labels must already be available and
observed by the applicable partition end. In particular, a later observation cannot
backdate a label into training using an earlier source receipt timestamp.

Conflicting immutable row identities quarantine the original as well as the conflict.
No interpolation, terminal-price settlement inference, or fabricated missing label is used.

## Separation, overlap and effective samples

Training labels must be known by `training_end`. Validation decisions begin at least
90 seconds later and labels must be known by `validation_end`. Held-out decisions begin
at least 90 seconds after that boundary. Crossing labels and boundary rows are purged.
Within each parent event, intervals are nonoverlapping across all outcome tokens;
records sharing a parent cannot increase effective event counts by token duplication.
The watermark extends through the later target or label-known time.

`temporal_heldout` is exploratory chronological evidence. It may contain parents already
seen during training/validation. `strict_event_disjoint_heldout` removes every such parent.
Counts and parent overlap are reported separately. Shared twenty-point feature windows
can still induce temporal dependence; disjoint mark episodes are not independent events.

No monetary quote episode counts toward the existing certified 100 independent training
and 100 independent held-out event-outcome requirements. Those counters remain zero here.

## Baselines and execution economics

All candidates share the exact same retained rows and contemporaneous unchanged-bid
baseline. The evaluator reports MAE, RMSE, signed error and paired MAE improvement for
each partition. Brier score and log loss remain null: their binary event semantics do
not apply to USD bid marks, even if a quote happens to be zero or one.

Optional `costs` carries independently verified `executable`, `gross_per_share` and
`net_per_share` arithmetic. Unexecutable/missing costs do not become zero-cost trades.
All-row cost means are common quote diagnostics, not a model-dependent trading advantage.

Optional `estimated_edge_by_candidate` must be calculated solely from predecision
forecasts and predecision fee/slippage assumptions. It must never use subsequently
observed exit fees or future liquidity as a decision feature. A frozen research-only
policy selects projected edge >=$0.03/share; no threshold search is performed. The
selected rows receive hypothetical gross/net means, variability and chronological
unit-share drawdown. These are observed quote arithmetic, not actual fills, account
P/L, a portfolio backtest, or executable profit. No selected examples yields null
performance, not zero profit.

## Dependence, uncertainty and multiple comparisons

Inferential calculations require at least twenty strict held-out parent groups, all
independently reviewed. Each review must have a valid evidence SHA256 bound by the
caller verifier. One unreviewed row removes its parent from inferential eligibility;
if any strict group remains unreviewed, inference is withheld for that cohort.
Twenty is a predeclared research inference floor, not a certification threshold.

The estimand is an equal-weight mean of per-parent effects. A deterministic 1,999-replicate
bootstrap resamples entire parent means, preserving within-parent quote dependence.
One-sided cluster sign-randomization p values additionally assume exchangeable signed
parent effects under the null. Independent parent review and these assumptions are
required; the code does not establish them merely from statistical correlation.

Holm adjustment preserves a planned family of eight hypotheses: four paired accuracy
comparisons and four positive net-value tests. Missing tests remain in the family as
p=1 rather than silently reducing multiplicity. A positive effect is marked supported
only when the lower 95% interval is positive and Holm-adjusted p<0.05. This descriptive
flag never changes certification, model promotion, order admission or financial risk.
Insufficient/unreviewed groups produce null intervals and p values with an explicit
reason. No significance can be inferred from one trade or repeated same-event marks.

Validation-versus-held-out relative deterioration is research-only visibility. The
statistical module never suspends/enables production strategies or modifies risk controls.

## Reproducibility and limitations

The report binds canonical dataset SHA256, fixed candidate/model versions, exact split
boundaries, purge length, parent grouping, row rejections, inference seed, replicate
count, multiplicity policy and evidence limitations. No model is selected for deployment.
A best descriptive score cannot establish a positive return after transaction costs.
Raw source replay and independent parent review remain external evidence requirements.
