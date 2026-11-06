# Phase 16 executable depth and causal bid-mark research

The existing strategy source, model hash, risk engine, admission registry and
broker remain unchanged by this workstream. The new modules have **research
status only** and never create an order, reservation, simulated fill, independent
outcome probability, certified approval, or strategy promotion.

## Observed-depth execution assessment

`research.phase16.execution.assess_execution(market, book, now=...,
target_notional=2, fee_observation=None, forecast_lower_bid=None)` accepts the
existing market/book contracts or their JSON form. The monetary forecast input
is a conservative **future best-bid mark in USD/share**, not a terminal event
probability. Source/receipt cutoffs, metadata identity, active lifecycle, rule
presence, token mapping and the existing 15-second quote/one-hour metadata
freshness bounds are enforced. A resolution metadata field is not asserted to
be an independent settlement-rule review.

Standard sizing matches the existing account: `max(target_notional/best_ask,
market.min_order_size)` shares. A minimum lot exceeding the $2–$5 standard
notional range is rejected. Higher tiers are explicitly unsupported by this
standard-size research helper; its callers must not use it to grant larger
allocation authority. Fees-inclusive reservation is separately reported because
the existing tier ranges apply to principal notional and portfolio controls
include fees. Ticks, maximum $0.05 spread and 25% participation remain unchanged.

The important distinction is between the **actual current best-ask limit** and a
hypothetical sweep. Only ask shares available at that exact limit count toward
the existing broker's participation allowance. Deeper asks cannot make a thin
best-ask order pass. A separate sweep walks observed levels at 25% of each
level's size and reports supported/unavailable shares, VWAP, levels and impact.
A similarly conservative current bid quote exposes exit depth and curvature.
These are source observations and model assumptions, not paper fill reports or
proof of future liquidity. Missing depth is never filled in or interpolated.

Fees must be a recent (at most 300 seconds), nonfuture public CLOB observation
with a source reference; unknown rates remain null rather than zero. Existing
raw-response/evidence IDs are preserved where supplied. The caller must replay
those raw sources when claiming empirical results. The fee used is the existing
conservative global notional bound, not a claim of exact future maker rebates.

When a qualified monetary lower forecast is supplied, the assessment subtracts
observed entry curvature, a current-exit curvature proxy, fees on each leg and
at least $0.01/share slippage per leg. It retains the $0.03/share minimum net edge.
The current-exit proxy is explicitly **not verified future depth**. Real paper
execution still requires the existing risk approval, fresh executable books at
execution time, latency/partial-fill logic, and all other admission prerequisites.

Result fields include `execution_checks_pass`, `cost_adjusted_edge_pass`,
`estimated_net_edge_per_share`, `execution_reasons`, `valuation_reasons`, exact
market/book/rule hashes, quantities, reservation, best-limit capacity and the two
depth projections. `trading_authority` and `certification_authority` are always
false. An integrating caller may use this only to add conservative rejection;
no positive result can substitute for an existing gate.

## Causal short-horizon challenger

`research.phase16.short_horizon.replay_forecasts(points, cutoff=...,
verify_point=..., horizon_seconds=60, max_label_delay_seconds=30,
min_prior=40, min_matured_errors=20)` evaluates compact `CausalHistory.points()`
records. Required fields are:

- `source_at` (or `timestamp`), `available_at`, `observed_at`;
- `book_id`, `market_id`, `token_id`, parent `event_id`, `rules_sha256`, `source`;
- current `bid`/`ask`, fixed-size `bid_vwap`/`ask_vwap`, `quantity=5.0`, and
  `depth_scope="top3_observed"`;
- optional point-in-time `fee_observation` for cost analysis.

The default raw replay verifier rejects every point. An explicit verifier must
replay the archived quote and context hashes, and supplied fee provenance; a
source URL or self-asserted `verified` field alone is insufficient. Invalid or
future points and ambiguous identities are rejected. Exact duplicates add no
evidence. A changed observation under an existing identity quarantines both
copies. Cohorts are split by token and rule identity. A source gap longer than
120 seconds resets the local causal history and error pool.

The challenger uses the median of the prior 20 depth bid marks plus the median
of previously matured horizon residuals. It requires at least 40 prior points
and 20 matured residuals. The current quote is withheld from fitting. Its error
envelope is the previous 90th-percentile absolute residual around its median,
with the unchanged $0.01 floor; it is an unvalidated monetary error envelope,
not statistically guaranteed probability calibration. Forecast and naive
unchanged-current-bid baseline share the same actual decision cutoff.

A target is the first original source quote at or after decision + 60 seconds,
within a maximum 30-second tolerance. The source, receipt and study availability
times must satisfy all original cutoffs. Labels are not interpolated, and a
currently unavailable or late label cannot mature a forecast. The first 60% of
time-ordered observations defines the training interval; a 90-second purge
precedes held-out decisions. **Residual bias and uncertainty fitting are frozen
to labels available in the training interval throughout held-out evaluation.**
Lagged public features can update causally, but held-out labels cannot fit the
model. Records expose every feature ID, point/label hashes and latest fitting
label time so this separation can be audited.

Scores are monetary MAE/bias against the contemporaneous unchanged-bid baseline.
Brier score and log loss remain null because monetary bids are not resolved
binary outcome labels. Parent groups and overlaps are reported, but repeated
quotes and the same events across time are not independent certification events.
The required 100 independent training/100 held-out event thresholds remain
untouched; this exploratory temporal replay grants zero eligible certification
events and no model authority. Confidence intervals and superiority claims stay
unavailable when independent evidence is insufficient.

Where both archived fee observations are verified, an observed-quote round trip
subtracts the entry ask, future observed bid, fees and $0.02 total slippage. This
is not simulated account P/L, queue priority or an executable trading result.
The separate estimated-edge projection uses only the decision-time fee and
forecast lower bound; future fees/labels never select a historical entry.
`positive_projection_before_other_qualification` is deliberately not an admitted
opportunity. Conditional selected-quote results, if any, remain exploratory.

Historical forecasts are reconstructed after collection, not claimed to have
been committed prospectively at their old timestamps. The dataset/config/model
hashes, chronological intervals and caveats preserve reproducibility; later model
selection on the same dataset still needs a genuinely untouched evaluation cohort.

## Verification and empirical scope

Controlled tests cover thin top levels versus deep liquidity, fractional depth,
partial support, disappearing exit depth, fees, age/identity failures, minimum
lots and tier limits, causality, target tolerance, frozen held-out calibration,
purged intervals, source replay, ambiguity quarantine and nonfinite inputs.
Synthetic test accuracy is never reported as genuine forecasting skill. The
coordinator's Phase 16 artifacts contain authentic source replay results and
limitations; this implementation alone makes no empirical edge claim.
