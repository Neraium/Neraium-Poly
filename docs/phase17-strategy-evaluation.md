# Phase 17 strategy evaluation

Production strategy code, admission rules, risk limits and certified approval are
unchanged. The new fixed challengers are research-only and cannot submit orders.

## Existing short-horizon strategy

An independent read-only replay matched all11Phase16 qualified legacy signals to
authentic later quotes60.504–70.739seconds after their decision times. It verified
31cycles,1,329deltas,80full books and11signals. These are one overlapping episode
in one unreviewed parent event, not11independent trials.

Mean absolute forecast error was **0.201818/share**, versus **0.05/share** for the
unchanged decision bid. **0/11** observed future marks lay inside the unvalidated
forecast bands. Five gross crossed-quote marks were positive and six negative;
the largest positive gross mark was only.02/share. None remained positive after
the existing.02round-trip slippage assumption, even before fees. This supports a
model/regime-risk finding; no execution-control defect was found in the actual trade.

Actual historical paper round trip: market6736353/parent1322448,
12.5shares bought at.16 with.10modeled fee, sold at observed.07 with.04375exit fee.
Realized simulated loss **$1.26875**, leaving **$498.73125** cash and no position.
This occurred in Phase16 and is not a new Phase17 trade. The certified account
remains$500/P/L0. Final Phase17 deltas are in phase17-readiness.md.

Native rejection records contain five old kill-switch rejections and ten later
ownership rejections. Ownership protected against duplicating the already owned
contract. Missing producer-health snapshots and post-ready entry liquidity prevent
claiming how rejected hypothetical orders would have filled. Their counterfactual
net P/L and the causal number of losses prevented remain null. Positive hindsight
quote moves do not justify changing ownership or exposure limits.

## Existing relationship strategy

No evidence establishes useful predictive relationship changes or cost-adjusted
advantage. Existing temporal persistence and contextual-evidence requirements remain.
Shared parents indicate statistical eligibility, not logical exhaustive-set pricing,
causation or permission to trade. The causal graph, source gaps and retirement
provenance remain available through Phase16 and operations views. No relationship
threshold was weakened. Narrow static observations limit falsifiability and power.

## Other registered candidates

|Candidate|Primary remaining requirement|Disposition|
|---|---|---|
|Calibrated forecasting|Independent predecision context, verified outcomes, chronological calibration|Blocked for unsupported forecasts|
|Cross-market consistency|Reviewed exhaustive payoff/rule scope and atomic multi-leg execution|No logical arbitrage assertion|
|Liquidity spread|Queue/adverse-selection validation and supported two-sided inventory execution|Research-only capability gap|
|Event-driven|Independent causal event context and response model|Unsupported numerical forecasts withheld|

Registration and emission of setup rejections are not order-admission authority.
The short-horizon and persistent-relationship pathways retain their existing approved
experimental admission rules, including conservative net edge, freshness, fees,
liquidity, position ownership, event/correlation exposure and capital reservation.

## New fixed research challengers

Unchanged bid, prior20-median reversion, prior20-median momentum and fixed depth
imbalance use strictly causal evidence. Reversion/momentum tie the unchanged baseline
on20static temporal held-out episodes; imbalance is worse. All have zero cost-selected
cases and no event-disjoint heldout. None is promoted, certified or claimed profitable.

Drift monitoring reports descriptive relative error on the last128matched marks;
it does not treat simulation profits as independent training evidence or automatically
change production strategy state. Baseline comparison, inferred superiority,
execution feasibility and actual paper performance remain separate concepts.

## Rejection investigation

`.planning/evidence/phase17/strategy-counters.json` records before/after persisted
epoch frequencies, categories and nonexclusive reasons. Candidate and order counts
have different scopes: per-cycle/epoch evaluations include duplicates, emitted
signatures exclude them, and a qualified signal can still fail admission or risk.

The new default-deny rejection framework admits numerical counterfactual quote
comparisons only when source, identity, cutoff and later cost evidence independently
replay. Data-quality failures and unavailable labels remain unmatched. No threshold
change is recommended on current evidence. Any future proposal requires a separately
reviewed independent holdout and approval, not a trade-count target.
