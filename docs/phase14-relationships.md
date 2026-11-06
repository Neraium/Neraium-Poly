# Universal cross-domain relationship research

`UniversalRelationships` studies explicitly declared dependencies across all
shared domains. It does not invent links from keywords, infer causation from
correlation, or grant strategy approval. Review and observation-provenance
callbacks deny by default and must return the literal boolean `True`.

## Distinct claim levels

1. **Observed statistical dependency:** source-aligned, reviewed pairs form a prior
   joint relationship. This is descriptive evidence, not an independent event.
2. **Persistent relationship change:** a changed rolling joint slope/correlation
   and a residual outside declared uncertainty must persist across at least three
   novel pairs and60seconds after at least ten baseline observations.
3. **Logical probability constraint:** explicit reviewed rules, payoff scope,
   underlying event, timing and binary-event semantics are required. Mutually
   exclusive outcomes, reviewed complete two-outcome sets and reviewed subset
   relationships have distinct checks. Fractional-payout quotes cannot substitute
   for unconditional event probabilities.
4. **Causal hypothesis:** may motivate a reviewed dependency definition, but any
   finding remains a statistical change. `causality_verified` remains false.
5. **Forecast improvement:** requires a separate chronological held-out comparison.
   This engine cannot manufacture it from a persistent residual.
6. **Executable opportunity:** requires separate bid/ask depth, fees, slippage,
   settlement/timing, execution, risk and strategy authorization. Atomic multi-leg
   support is absent; `executable_opportunity` and trading authority remain false.

## Joint relationship and temporal evidence

Statistical links fit a frozen ordinary-least-squares slope/intercept and
correlation from prior paired observations. A rolling joint window must change
its correlation by at least0.3 or its slope by at least half the prior slope's
magnitude. The current residual must also exceed the maximum of the definition's
minimum residual, three prior RMS residuals, and propagated declared input-error
bounds. These thresholds are descriptive research policy, not calibrated
statistical significance or a guarantee against false positives.

This is more restrictive than thresholding a single-market price excursion. A
single excursion, absent joint variation, duplicated evidence, unknown context,
invalid timestamps or unreplayed source evidence cannot become a persistent
finding. Domain units remain explicit: reviewed temperature/energy-price links
can fit a joint relation with different units; arbitrary values above1e12 must
be explicitly normalized before input. No global forecasting algorithm is imposed.

Frozen baseline values and the individual source-evidence hashes are retained in
checkpoints. Findings include the definition hash, frozen baseline cutoff and
proofs, current pair/window evidence, engine source hash/version, model versions,
uncertainty and separate claim-level flags. A continuing persistent episode is
counted once, including across restart. Findings are not independent samples or
profitable trades. Multiple testing, common drivers and regime changes require
further independent validation; significance is null.

## Interface

```python
engine = UniversalRelationships(
    definition_validator=replay_registered_definition,
    observation_validator=replay_actual_evidence,
)
result = engine.observe(definition, observations, now=aware_utc_cutoff)
checkpoint = engine.checkpoint()
engine.restore(checkpoint)
status = engine.summary()
```

A definition supplies `id`, `kind`, `left_id`, `right_id`, `left_domain`,
`right_domain`, `relation_type`, `review_actor`, `available_at` and, for statistical
links, positive `minimum_residual`. Logical links additionally supply reviewed
`left_rules_sha256`, `right_rules_sha256`, `underlying_event_id`,
`settlement_window` and `logical_scope_reviewed=True`; exhaustive sets also need
`outcome_set_complete=True`.

Exactly two observations supply `entity_id`, `domain`, finite `value`, `semantics`,
`timestamp`, `available_at`, `evidence_sha256`, nonempty `source`, `kind` and
`uncertainty.absolute_error_bound`. Optional `model_version` identifies a
forecast-derived feature. Supported kinds are `market_quote`, `external_evidence`
and `independent_forecast`. Source callbacks must bind these fields to genuine
immutable evidence, not trust a caller's assertion of qualification.

The default maximum age is15seconds for market quotes and one hour for other
observations. Reviewed definitions may select bounded source-specific ages and
pair skew; market-quote age can never exceed the existing15second ceiling. This
allows explicit weather/energy or economic/finance sampling assumptions without
pretending hourly data is a simultaneous tick. Inputs and definitions must be
available by the evaluation time. A reviewed definition change requires a new ID.

The dependency graph contains only registered reviewed definitions and preserves
entity/domain identities. Suggested weather-energy, inflation/rates,
crypto-related-contract and government/industry links remain hypotheses until
reviewed causal evidence exists. No such genuine cross-domain finding is claimed
by this implementation workstream.

## Bounds and verification

The engine caps definitions at200, warmup windows at100, observation payloads at
16KiB, definition payloads at8KiB and serialized checkpoints at32MiB. Defaults are
ten baseline pairs, three persistent pairs and60seconds. Rejections have a bounded
64-category counter plus an overflow bucket. Restore checks configuration,
definition/provenance hashes, frozen baseline proofs, pair hashes, causal times,
finite values, persistence and counters; review callbacks must still be supplied.

Twenty controlled tests cover default-deny review, joint structural changes,
single excursions, no joint variation, source deduplication, stale/future inputs,
quote freshness, uncertainty, semantics/rules/event/window compatibility, no
causal/forecast/execution promotion, restart corruption and callback failure.
They establish software behavior, not real-market performance. Actual qualified
cross-domain findings in this workstream: **zero**; no reviewed aligned genuine
cross-domain pair cohort was registered here.
