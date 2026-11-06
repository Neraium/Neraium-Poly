# Phase 12 terminal event models and SII relationship research

The historical evidence does **not establish independent terminal forecasting
skill**. The actual canonical dataset has 250 propositions, 47 corroborated token
outcomes, 616 historical price observations and 95 contextual observations. All
616 price observations were acquired after their historical decision times.
**Zero** point-in-time market-comparison rows, independent training rows,
validation rows or held-out rows qualify. Terminal Brier, log loss, calibration,
independent confidence intervals and cost-adjusted returns therefore remain null.

Audited dataset SHA-256:

```
9e20ac5ccaef7616c2f0047df789a696916ff0d4b3d7d3938334bb190f77353d
```

These are authentic historical records whose availability is collected-now. They
cannot become past model inputs by copying their event timestamps into availability
fields. Historical outcomes remain labels, never predecision evidence. The
small actual run used one process; it is not described as parallel. The parent
coordinator runs the integrated CPU-worker experiments separately.

## Model interface and safeguards

`run_event_models(dataset)` accepts the canonical loader dictionary
`{manifest,events,evidence,outcomes}` or a dataset directory. Every evidence body
and complete outcome-verification body is checked against its SHA-256. Conflicting
outcomes require correction review rather than silent replacement.

Eligible samples require identity-matched market prices and event metadata
available by the decision, reviewed rule versions, verified matching rules at
settlement, and a final payout occurring strictly after the forecast. An
independent model additionally requires reviewed event/dependency independence and
reviewed numerical **external** context available before prediction. Direct label,
payout and market-probability feature names are rejected. Current market prices
alone never qualify as independent context.

The first eligible forecast per reviewed dependency group is selected before
examining labels. Research uses chronological 60/20/20 partitions; training and
validation labels must mature before the next split, and dependency groups cannot
overlap. This does not relax certified-strategy requirements: 100 independent
training and 100 independent held-out events remain mandatory, with owner approval
and execution/risk qualification separate.

Implemented baselines and challengers:

- Contemporaneous market-implied probability, retained as the explicit comparison.
- Historical event frequency and a Beta(1,1) Bayesian frequency baseline, fitted
  only on matured training outcomes.
- Standardized L2 logistic regression using independently sourced numeric context;
  scaling and weights fit on training only.
- Validation-only temperature calibration, selecting among .5/1/2 by validation
  log loss. Final model comparison uses validation Brier, never held-out selection.
- Boosting and ensembles deferred until enough real independent data demonstrates
  improvement over simpler models.

Metrics include terminal Brier, log loss, ECE, reliability bins and AUC (null for
single-class targets), category and horizon reports. When genuine independent
samples exist, the selected-minus-market Brier difference has a conservative
95% distribution-free Hoeffding interval. This interval is conditional on the
independence review and does not establish executable profit. Research reports
cannot self-certify or grant automatic promotion. Controlled tests demonstrate
working model mathematics and leakage guards; their scores are never reported as
real-market evidence.

## Four SII relationship layers

`EventRelationshipEngine.observe(frame, now)` evaluates actual fresh public
quotes using a persisted temporal baseline, evidence persistence, significance,
source alignment, liquidity context and unchanged gap controls. `checkpoint()` and
`restore()` preserve descriptive research state. Same-event YES membership is
an explicit **statistical prior**, not an enforceable payoff constraint or causal
claim. Missing/degraded/stale/ambiguous frames cannot generate new evidence.

The layers remain distinct:

1. Observed statistical relationships and qualified persistent temporal changes.
2. Independently reviewed logical payoff relationships, including exhaustive,
   mutually exclusive and conditional sets.
3. Causal hypotheses, requiring separate evidence.
4. Executable opportunities, requiring actual execution and capital capability.

`evaluate_logical_constraint()` requires predecision actor/evidence review,
compatible settlement scope, exact rule hashes, current official books, source
alignment within two seconds, verified current fees, minimum lots and bounded
10% displayed depth participation. Reviewed exhaustive buy bundles may have a
positive quote-level difference after conservative fees/slippage. This is still
**not an executable opportunity**: coordinated multi-leg latency/atomicity,
settlement and capital execution are unsupported. Conditional/sell hedging is
rejected explicitly. No such reviews are invented from market names or prices.

`run_event_relationships(dataset)` records 120 proposed dependency groups in the
actual 250-proposition sample, zero reviewed logical constraints, zero historical
predecision price observations and no historical executable depth. Persistent
historical findings, false-positive rates and independent structural confidence
intervals remain unavailable, rather than invented zeros. Live descriptive
research remains available independently; relationship changes never establish
profits by themselves.

## Verification

Fourteen focused tests cover controlled model scoring, terminal target identity,
held-out leakage, dependency deduplication, label maturity, rule/outcome hashes,
reserved label features, validation calibration, timestamp guards, persistent
relationship restart state, and conservative logical arithmetic/depth/fees.
All focused tests and scoped Ruff pass. Parent integration coordinates full
backend, browser, account isolation and final-source CI verification. No account,
operational strategy, risk, execution, approval requirement or service changed in
this workstream.

Reproduce after integration:

```python
from neraium_poly.research.phase12.dataset import load_dataset
from neraium_poly.research.phase12.models import run_event_models
from neraium_poly.research.phase12.relationships import run_event_relationships

data = load_dataset("data/phase12/dataset-v3")
model_report = run_event_models(data)
relationship_report = run_event_relationships(data)
```

Actual artifacts remain in the isolated worktree under
`data/phase12/model-study-v2/`; the bounded summary is committed under
`.planning/evidence/phase12-models/summary.json`.
