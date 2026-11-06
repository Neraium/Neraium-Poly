# Phase 11 chronological model and relationship research

This workstream adds exploratory, reproducible comparisons. It cannot write an
account, submit an order, approve a strategy, or promote an experimental model.
`run_models(observations, manifest)` and `run_relationships(observations, manifest)`
consume the same frozen `ResearchObservation` dataset, and return JSON reports
with `ExperimentSpec` metadata and explicit missing-evidence metrics.

## Causal forecast experiment

The price target is the first actually observed future bid whose source and
receipt times are at least 60 seconds after the decision receipt, with a maximum
30-second additional label delay. It is an observed bid mark, not a fill.
The binary target is whether this bid rose above the current bid. **Bid-rise
probabilities are not terminal settlement probabilities.** Brier score, log loss,
ECE and reliability bins for that target are reported separately from mark MAE
and from execution results. Terminal Brier/log loss/calibration remain null:
there is no qualified point-in-time independent final-outcome dataset here.
Current market prices cannot supply that independent missing target evidence.

Features use only the current book and earlier receipts: spread, top-five-level
share imbalance, last bid change, last-five bid change, log total top-five depth,
and current bid level. Warmup needs five prior observations. Incomplete, stale,
wide-spread, duplicate and non-monotonic source observations cannot inflate the
training sample. Reference prices are bounded to [0,1]. Dataset metadata/fees
must have been available before the feature time; missing context stays missing.

Unique global decision timestamps define 60/20/20 train, validation and held-out
partitions. Training labels that mature in validation, and validation labels that
mature in held-out time, are purged. This prevents target overlap across cutoffs.
Feature scaling, ridge coefficients, frequency/Beta(1,1) posterior and logistic
weights fit training only. Ridge regularization .1 and logistic optimization
schedule are fixed in source. Validation alone selects the mark model and one
of fixed logistic calibration temperatures {.5,1,2}. Held-out data is scored
without refitting or choosing parameters. Three later time blocks and per-token
metrics expose drift and support descriptive segment joins.

Comparisons include unchanged bid, midpoint, training mean bid change, regularized
linear mark forecast, historical bid-rise frequency, Bayesian-shrunk bid-rise
frequency, and regularized logistic bid-rise forecasts. The existing operational
median/bias/error-envelope helper is replayed causally as a separate same-row
reference; its partial warmup coverage is not mixed into the challenger's model
selection. Statistical forecast accuracy alone does not establish cost-adjusted
edge. Advanced boosting and ensembles are deferred: the simpler mark challengers
must first beat the baseline reproducibly, and a larger model adds research
selection risk without additional independent evidence.

Reported event groups overlap between chronological partitions. These are not
100 independent training or 100 independent held-out events. Repeated overlapping
horizon labels and unreviewed cross-event dependencies prevent a defensible
independent confidence interval; CI stays null with a reason. No confidence level,
calibration certification or profitability is inferred from sample volume.

## Actual frozen-data result

Frozen dataset SHA-256:
`4bca310fb839d1f8a24ddaa334e71147f374bef83f3f8546014ee726f540c95d`.
It contains 30,000 real archived observations, source times approximately
03:34:59–04:41:30 UTC on 2026-11-06, 65 tokens / 34 markets / 20 reported event IDs.
These counts describe the frozen artifact, not current service coverage.

The first causal run produced 26,475 labelled cases: 15,521 training, 4,803
validation, 5,236 held-out, with 915 purged boundary labels. Eighteen reported
event IDs appeared in both training and held-out; reviewed independent events=0.
The validation-selected mark forecast was **unchanged bid**.

| Held-out mark model | MAE, USD/share |
|---|---:|
| Unchanged bid | .000818181818 |
| Training mean change | .000822312598 |
| Ridge | .000890081961 |
| Midpoint | .004413770053 |

The operational helper had 5,224 eligible held-out cases, MAE .001518041730,
versus .000817764165 for unchanged bid on those exact same cases. This corroborates
its Phase10 accuracy limitation without assigning the new challenger's metrics
to the live strategy or creating paper trades.

For the **bid-rise** target, logistic held-out Brier .07148484 and log loss .262029
were lower than frequency-baseline .07450047 / .281728. However, logistic ECE
.029768 was worse than baseline .008946. Validation selected temperature1 (no
calibration change). This small descriptive directional score improvement is a
research lead, **not an executable edge**: it predicts direction, not sufficient
move magnitude to cover spread, fees, slippage, latency and queue uncertainty.
The same-event, single-window dependence prevents a credible significance claim.
The parent pipeline reruns final source under its recorded CPU workers; use that
SHA-bound artifact as authoritative for final source outputs and per-token detail.

## SII-inspired relationship experiment

The relationship study uses causally available same-event YES contracts on
distinct markets as contextual dependency hypotheses. It never assumes exhaustive
payoffs or logical arbitrage. It builds bounded (at most 200) pair states using
actual aligned current book midpoints, a baseline of 20 earlier usable paired
observations, departures of at least .03 and three baseline scales (floor .005),
and persistence across three separately refreshed paired observations. Both source
timestamps must advance; the source-time skew may not exceed five seconds.
A gap above120seconds resets persistence. Missing or stale legs suppress new
observations rather than fabricating a relationship state.

This is evidence-persistence research rather than isolated anomaly scoring.
A structural departure cannot supply a forecast price, causal interpretation,
external corroboration or executable payoff. The actual initial study found
7,990 paired observations, 500 baseline-learning observations, 7,490 ordinary
variations, and **zero persistent findings**. It suppressed7,182 skewed pairs,
4,148 one-leg refreshes,3,362 stale/incomplete pairs and121 reused/out-of-order
source pairs. It retained18 gap-reset events. Counts are nonexclusive gates;
they are not independently labelled events or trading opportunities.

Follow-up bid changes, when findings mature, are diagnostic labels only and do
not feed an earlier signal. With no independently labelled structural regimes,
false-positive rate, net edge, logical arbitrage and confidence intervals remain
null. Even a future persistent finding cannot establish profitability by itself.

## Existing strategy dispositions

| Existing research family | Evidence bottleneck / disable condition |
|---|---|
| Short horizon | Operational mark helper loses to unchanged bid; do not promote without independent out-of-sample cost-adjusted improvement |
| Persistent relationship | No independently contextualized persistent finding or exit-price model; withhold admission absent evidence |
| Cross-market consistency | Exhaustive payoff review and executable multi-leg hedge absent; retain as blocked hypothesis, not trading capability |
| Liquidity spread | Queue priority/adverse selection and two-sided inventory implementation absent; passive profit cannot be inferred from quotes |
| Event driven | No independent predecision event-response context; suspend admission until causal external evidence exists |
| Calibrated forecast | No qualified final-outcome calibration dataset; research bid-rise probabilities cannot substitute for terminal probabilities |

The operational registry and risk/approval policies are unchanged by this
workstream. Unsupported studies are explicitly classified as blocked research;
there is no obligation to keep six executable strategies or force activity.

## Verification and continuation

`tests/test_phase11_models.py` covers causal features under future perturbations,
source-matured labels, boundary purging, train-only fit/scaling, validation-only
selection, target separation, invalid probabilities, duplicate sources, missing
context, bounded forecasts, persistent paired changes and reused-source rejection.
Fixtures are controlled and never installed into operational datasets/accounts.

Phase12 research recommendation: freeze the directional logistic model and compare
it on new days and disjoint reviewed event groups; build independent price-move
magnitude and execution-cost labels before any trading claim. Collect exogenous
point-in-time context and reviewed logical-payoff groups independently. Leave
terminal metrics and activation blocked until authentic evidence is sufficient.
