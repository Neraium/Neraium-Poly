# Relationship intelligence v1

`RelationshipEngine.observe(relationship, snapshots, now, context)` returns a
`RelationshipEvidence` contract for every attempt. `snapshots` is keyed by market
ID. `context` is an explicit `EvidenceContext` with measured liquidity, spread,
completeness and source; omitting it suppresses the finding. Callers must preserve
all market observations, relationship definitions and context inputs for replay.

```python
from neraium_poly.intelligence import RelationshipEngine, EvidenceContext
engine = RelationshipEngine()
evidence = engine.observe(edge, snapshots, now,
    EvidenceContext(liquidity_usd=100, spread=.02, source="book-collector"))
```

The first 20 fresh aligned observations create a frozen past baseline of the
probability difference between each pair. Later observations are compared to
that prior distribution with both a scale-adjusted threshold and a practical
minimum probability change. Three consecutive changes in the same direction
are required. A return to baseline, reversed direction, material observation gap,
or invalid input resets persistence. Replay re-instantiates the engine and feeds
original availability order; stable evidence IDs include policy and context.
The bounded state retains baseline observations plus the latest persistence
window, and keeps a cumulative persistence count. Reset or retraining requires
an explicit new engine and a new relationship version.

`discover_statistical_relationship` discovers synchronous Pearson relationships
in past **changes**, rather than correlating trending probability levels. It
excludes not-yet-available data and requires a minimum sample size. Discovery does
not establish causality, conditional probability, fair value or profitability.
The baseline detector characterizes a shift in the pair's probability gap; it is
not a general learned multivariate dependency model. Broader joint models and
multiple-testing correction remain research work. Relationship confidence is an
input quality score, not an empirically calibrated trade probability.

Logical edges have distinct meanings: `mutually_exclusive` requires the sum to
be no greater than one, `exhaustive` means an exclusive and exhaustive outcome
set whose sum is one, and directed `implication` requires P(first) <= P(second).
Every logical finding requires `rule_verified`, nonempty rule provenance in
`rule_description`, and `context.settlement_reviewed=True`. The engine cannot
verify legal or natural-language settlement equivalence itself. Conditional
edges are retained in the ontology but suppressed with
`conditional_joint_probability_required`; marginal probabilities alone cannot
establish a conditional constraint. Market rules and a resolution source must be
present even for statistical findings.

Suppression reasons cover missing data/context, stale or unavailable observations,
unaligned clocks, inactive markets, weak relationship confidence, missing rules,
insufficient baseline/persistence, volatile baselines and market liquidity/spread
conditions. Observation IDs reference actual source market records. No findings
place orders or bypass downstream model calibration, expected value or risk
approval.

Validation: `PYTHONPATH=$PWD/backend /home/ubuntu/Neraium-Poly/.venv/bin/pytest -q tests/test_intelligence.py`.
Tests use synthetic fixtures and certify implementation behavior only.
