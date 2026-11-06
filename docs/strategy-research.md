# Phase8 competing strategy research

The research package compares six hypotheses and simple forecast models. It does
not approve a model, create an order, fabricate a historical fill, or change the
strict `ValidationPolicy`. Every `ResearchSignal.activation_eligible` is false.
Research qualification means only that the supplied setup evidence meets that
function's preconditions. Certification still requires an exact reviewed
strategy package, the existing real-data validation gate, and explicit owner
approval. There is no automatic promotion.

## Six hypotheses

| Candidate | Eligible universe and entry | Exit and value model | Main failure cases |
|---|---|---|---|
| Persistent relationship | Reviewed related binary markets, at least20 causal baseline observations and3 persistent qualified changes, plus a separate calibrated forecast whose lower bound clears costs | Verified resolution or validated evidence invalidation; lower probability minus executable ask, conservative fee and latency buffer | Regime changes, spurious association, stale or unaligned peer books; a relationship shift alone has no expected-value claim |
| Logical constraints | Independently reviewed complete and mutually exclusive payoff bundle, all observed executable legs and known fees, total cost below reviewed minimum payout | Final reviewed resolution of all legs; minimum bundle payout minus all-leg costs | Mismatched rules, missing outcomes, dispute and non-atomic partial-leg execution; correlation is never a payoff identity |
| Independent forecast | Contemporaneous independently archived external context, calibrated probability with source linkage, fresh depth and known costs | Reviewed resolution or independently validated evidence reversal; calibrated lower probability minus execution costs | Revised archives, outcome leakage, missing context provenance, poor calibration and stationarity |
| Liquidity maker | Liquid two-sided book, non-crossing tick-valid proposal, explicitly supported queue/fill probability and adverse-selection/fee bounds | Cancel/time limit or inventory cap with observed liquidation depth; supported fill probability times spread less inventory/adverse-selection/fee costs | Queue priority, adverse selection, one-sided fills, unknown liquidation; depth is not queue position |
| Event repricing | Independent timestamped publication, actual pre-publication and post-publication quotes, calibrated update available at the decision | Reviewed event resolution or evidence invalidation; updated lower probability minus executable costs | Rewritten publication times, duplicate or already-priced news, unexecutable delayed quotes |
| Microstructure | At least20 ordered, complete source books, no source gaps, calibrated fixed-horizon up-move model and measured return/cost distribution | Fixed horizon using actual observed exit depth; expected measured horizon return minus round-trip costs | Imbalance without calibration, gaps, latency reversal, missing exit quote; terminal outcome probability differs from short-horizon return probability |

Each function returns explicit reasons and source IDs. Books fail closed for
missing sides, incompleteness, future or older-than15-second source time and wide
spreads. There is no substitute of receipt time for source time. All algorithms
remain subject to risk, portfolio correlation, inventory and capital controls
before any separately authorized paper order.

`logical_constraint_signal` supports only research on BUY-all exhaustive bundles.
It does not implement shorting, split/merge/redeem, atomic baskets or negative-risk
conversion. Overpriced mutually exclusive quotes do not become a BUY arbitrage.
A favorable bundle cost is conditional on full executable legs and correct payoff
semantics; it is not a claim of a guaranteed realizable profit.

`maker_signal` proposes research quotes only. No queue reference or supported fill
probability means no qualified signal. Rebates are excluded. `microstructure_signal`
reports imbalance as a diagnostic, not an inferred probability, and requires a
separately measured horizon model and exit-cost distribution for a value estimate.

## Reproducible bundle evaluation

```python
from neraium_poly.research.evaluation import evaluate_bundle, write_report
report = evaluate_bundle(authentic_research_bundle)
write_report(authentic_research_bundle, "data/phase8/research-report.json")
```

The report schema has `dataset_hash`, `evaluation_as_of`, `analysis_mode`,
`coverage`, `models`, six `candidates`, `recommended_model`, and `certification`.
It hashes canonical sorted input records and the acquisition manifest; permuting
input order does not change the result. Conflicting record IDs or contradictory
verified labels prevent model fitting or exclude the affected event. Unavailable
future observations are excluded. All source observations retain their original
timestamps and availability fields.

One deterministic market/outcome is selected per independent event. Related
outcome legs and repeated snapshots cannot inflate event counts. Selection uses
the first historical source quote, not a lead time chosen from a subsequently
known resolution or profitable price movement. Final outcomes require verified
labels, settlement references and resolution times. Prices at or after resolution
are not forecasts.

A chronological split requires at least100 independent training and100 heldout
events before calibrated-model comparison. Training labels must precede the first
heldout decision. No threshold is reduced because a dataset is small. Calibration
uses only training data; heldout labels are used only for evaluation. Per-bin
training sample minimum remains30.

Models compared are raw market probability (explicitly a baseline, never an
independent forecast), Laplace-smoothed event-frequency histogram calibration,
a three-coefficient regularized logistic model using an independently archived
numeric context feature, and an independent probability-source baseline where
that archive actually exists. Logistic training uses fixed250 gradient updates,
training-only scaling and regularization, with no external ML package or search
across a heldout set. Missing independent numeric context makes that model
`not_evaluable`. Simplicity is preferred: the more complex model is recommended
only after conservative confidence-interval separation in heldout Brier scores.
A research recommendation is not certification or activation.

Metrics include heldout Brier score, clipped log-loss, expected calibration error,
calibration bins, event-level normal-approximation95% confidence intervals, market
category breakdowns and fixed price-band breakdowns. Fixed price bands are not
represented as a learned economic regime. Candidate selection, multiple testing
and repeated access to a holdout require a separate sealed-research review;
these confidence intervals do not correct undisclosed selection.

## Availability and execution integrity

`analysis_mode="retrospective_event_time_only"` means at least one historical
observation was downloaded now without verified contemporaneous availability.
Retrospective event-time label filtering can support explicitly exploratory
price-scoring metrics, but it does not assert that those labels or features were
publicly available at historical decisions. It does not backdate any contract or
produce a certification artifact. `point_in_time_archive` requires verified
archive availability for every selected forecast and label, but still does not
prove authenticity from source strings alone. Exact source evidence and manifest
review remain mandatory.

Missing labels, prices, causal context, authentic historical books or fee
provenance appear as concrete report deficiencies. No missing executable price is
replaced with a current book, no historical L2 is inferred from a midpoint, and
missing execution evidence leaves P/L **null**, not a fabricated zero-profit
backtest. In particular, merely downloading a historical price series now cannot
certify a historical executable strategy.

Conditional transaction-cost analysis is available only for independently
archived heldout forecasts and labels with authentic source-time books, explicit
contemporaneous token-bound protocol fee context and calibrated lower bounds.
It targets$2 gross BUY notional, caps consumption at10% of supplied best-ask depth,
reserves fee/latency/slippage costs against a$500 research bankroll and$100
aggregate cost ceiling, and releases payouts no earlier than label availability.
Drawdown follows settlement-availability order. Extra per-share cost sensitivities
are reported. The output states the conditional taker-fill assumption and records
`actual_fills=null`: it is not evidence of observed fills, queue performance or a
full integrated portfolio certification. Maker and horizon strategies need their
own actual queue/exit evidence; the generic settlement screen does not supply it.

Every candidate remains `certification_status="blocked"` in this research module,
even for a statistically favorable controlled case. A successful analysis must
next be packaged and evaluated by the existing strict validation system, reviewed
for strategy-specific assumptions, and presented for explicit owner approval.
There is no bundled profitable model or actual research result in these tests.

Tests construct controlled synthetic assertions solely to verify formulas,
causality, independent event counts, deterministic replay and suppression. They
are never installed as an operational dataset or approval.
