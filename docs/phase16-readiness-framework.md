# Phase 16 qualification readiness and terminal calibration

These components are read-only research summaries and pure cohort evaluators. They
cannot certify a strategy, change a risk threshold, clear a stop, submit orders or
promote a model. Existing sports and market-baseline journals remain untouched.

## Readiness contract

`build_readiness(history_summary, execution=None, calibration=None, now=...)`
reports historical coverage, original quote freshness, missing evidence, cost
conditions and implementation defects separately. Its status is one of:

- `implementation_defect`: invalid/future timestamp, malformed metric or a failed
  history-integrity check. This is not an opportunity or a market observation.
- `insufficient_evidence`: causal history, matured mark targets, source freshness,
  depth/fee evidence or independent event calibration is not sufficient.
- `cost_threshold_not_met`: observed prerequisites exist but the conditional
  modeled net edge is below the unchanged $0.03/share requirement.
- `research_prerequisites_observed`: the caller reports these research inputs;
  this status still grants no operational authorization or certification.

Per-token readiness requires at least 40 retained causal quote observations, 20
matured sixty-second mark targets, sixty seconds of coverage, no retained gap above
120 seconds, source AND receipt ages no greater than 15 seconds, exact token/market/
parent identities and complete execution evidence. Eight tokens with five points
each cannot masquerade as a token with forty prior observations. Rendering time
cannot make an older original source quote fresh. Observed parent groups and
microstructure mark labels are never counted as independent resolved outcomes.

The current cost assessment is accepted under `estimated_net_edge_per_share` (and
explicit compatibility aliases). It remains a conditional USD/share model estimate;
nonfinite numbers are defects, missing estimates stay null, and a failed cost
threshold does not establish a statistically proven unprofitable strategy. All
thresholds and positive order-admission decisions remain with the existing engine.

## Terminal-outcome cohort contract

`calibration_cohort(rows, cutoff=..., heldout_start=..., verify_raw=...,
embargo_seconds=0)` accepts a bounded cohort of at most 10,000 canonical rows.
The held-out boundary is an externally fixed experiment input, not selected by
searching test results. The default raw verifier denies all rows. A supplied
independent verifier must replay original append-only forecast evidence, external
features and model training cutoff, contemporaneous market baseline, exact event
mapping and resolution rules, verified outcome source, and dependency-group review.
A record's booleans or hashes do not themselves authenticate its provenance.

Each row binds forecast/event/market/token/group IDs; domain, model/feature version
and contract semantics; forecast/model/dataset/outcome-proof hashes; exact original
resolution-rule text and hash; matching outcome rule hash; probability and market
probability; verified binary outcome; and explicit forecast, recording, source
availability, model-training, market, outcome and outcome-availability times.
Only `binary_terminal_event_probability` semantics are supported. Ternary sports
forecasts, cash payout fractions and sixty-second future bid marks must not be
converted to binary events to manufacture a calibration cohort.

Strict causal checks require source availability <= evidence cutoff <= forecast,
model-training cutoff <= evidence cutoff, original recording within thirty seconds,
forecast before resolution, and verified outcome availability by evaluation cutoff.
The market baseline must be observed and available before the forecast and no more
than sixty seconds older. A later market price cannot replace that baseline.

Repeated forecasts within a reviewed dependency group select the earliest eligible
forecast deterministically. A group appearing across train and held-out splits is
quarantined entirely and blocks scoring. All training labels plus any declared
embargo must precede the held-out boundary, and held-out model training cutoffs must
not precede the required training labels. Mixed model/feature/contract cohorts block
scoring. Hashes bind the complete input row multiset independent of row order.

Certification minima remain **100 independent training groups and 100 independent
held-out groups**. Until all structural checks and counts pass, metrics are null.
A sufficient research cohort reports held-out Brier score, proper log loss, market
baseline scores, reliability bins, paired Brier differences and a conservative
95% distribution-free bound. The interval assumes independently reviewed groups;
it is not an independence test. A wrong probability of exactly zero or one has
mathematically infinite log loss, represented as null numeric value plus explicit
`positive_infinity` status/count rather than a fabricated finite clipped score.
Improved forecasting accuracy does not establish executable profit; execution
performance remains null and all authority flags remain false.

## Authentic coverage snapshot

At **2026-11-06 22:50:18 UTC**, native SQLite read-only/query-only snapshots verified
all three forecast-journal hash chains:

| Evidence | Actual count/status |
|---|---|
| Market-baseline forecast records | 289, spanning 36 unreviewed dependency groups |
| Baseline records past scheduled close | 30 records / 17 distinct markets |
| Baseline records before scheduled close | 259 |
| Verified outcome journal records | 0 |
| Independent ternary NFL forecasts | 2; outcomes 0; event groups unreviewed |
| NFL scheduled starts | DET–MIA November 8 18:00 UTC; BUF–MIN November 10 01:15 UTC |
| Universal domain journal | 22 evidence records, 0 forecasts/outcomes |
| Independent binary calibration training / held-out events | 0 / 0 |
| Brier/log loss/independent trading advantage | null |

Authentic primary API GETs sampled due markets 6675981, 6490622 and 6288562. Gamma
reports 6675981 and 6288562 closed/resolved; 6490622 remains not closed and is a
negative-risk contract. These flags alone do not verify the payout or finalized
settlement timing. The prior 250-event canonical historical qualification remains
47 corroborated settlements, 616 historical price rows, zero authentic historical
book rows and zero qualifying training/held-out events. All 250 lack qualified
historical rule versions, predecision price availability, executable depth,
independent grouping and independent context; 203 lack corroborated settlement.

The bounded attempt for market **6675981**, forecast
`fc1b12b94416c0afbfbb2fbd2e0333918c093d953dfb8306319b51d6ea289752`, exposed an
implementation defect before any payout verification: Gamma's `/markets/6675981`
response omits both `eventId` and `events`. Existing normalization therefore raises
`missing market/event identity`, and settlement acquisition stops after one GET.
This is distinct from an unverified payout and must not be “fixed” by inserting
an assumed parent ID. A separate authentic GET `/events/1313864` supplied a unique
child 6675981 with matching condition, tokens and rules, demonstrating a possible
verified structured join. The integration coordinator owns any shared-adapter repair
and its native/chain replay tests; this workstream changed no shared adapter.

Original market response SHA-256:
`ed3b0df03876f5bea385ba20c0d1c174debc289b25391bedc825c8dd564fc9b8`.
Official parent response SHA-256:
`c88bd71824368a60ca6a27550a7c3ec5a8caef0f72f3688ac06c8be1446894fa` (174,229 bytes).

Raw responses, the exact journal heads, failed bounded acquisition, timestamps and
qualification funnel are preserved under ignored `data/phase16/readiness/` in the
root checkout. No production account or forecast journal was opened for writing.
Synthetic test cohorts are deliberately labeled controlled fixtures and are never
counted as authentic events or profitable results.
