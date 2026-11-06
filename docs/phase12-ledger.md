# Prospective event forecast ledger

`EventForecastLedger` is a separate research SQLite journal. It has no account,
order, risk approval or strategy promotion interface. Runtime integration belongs
to the coordinator; no service or account was changed by this workstream.

API:

- `EventForecastLedger(directory, clock=None, outcome_validator=None,
  independent_forecast_validator=None, independence_validator=None,
  max_records=100000, max_bytes=128*1024**2)`
- `record_evidence(EventEvidence)`, `record_forecast(EventForecast)`,
  `record_outcome(VerifiedEventOutcome)`; exact retries return false, ID reuse
  with changed content rejects.
- `forecasts()` / `pending_forecasts()` return immutable model tuples.
- `summary(now=None)`, `verify()`, `close()`.

A process lock prevents simultaneous writers. SQL triggers forbid updates and
deletes. Every accepted record has a canonical JSON digest and a chained digest
binding the prior record, kind and ID. Startup and summaries replay the chain;
corrupt content fails closed. This is tamper evidence, not a signature or a claim
that an attacker rewriting the entire database and every external checkpoint is
prevented. Storage stops at the configured record/byte budget or 8 GiB disk floor;
prior evidence is preserved. No automatic archive deletion or rollover occurs.

Forecasts must be recorded within 30 seconds of their timestamp. New forecasts
are separate records; backdating after seeing an outcome is rejected. Repeated
exact IDs remain idempotent across restart, even after their observation ages.
Referenced evidence must already exist, match event/market identity and have both
source and availability times no later than the cutoff. The cutoff cannot exceed
the forecast time. Payload hashes are checked at evidence admission.

Order-book evidence accepts `payload={"book": actual_book}` and rules evidence
`payload={"market": actual_market}`. Direct equivalent payloads are supported.
The nested official book must be fresh, complete and identity matched. The
market baseline must equal its observed bid/ask midpoint. Nested market metadata
must be active, causal, identity matched and not past its known closing time;
nonempty rules/source and the exact rules digest are mandatory. The midpoint is
an observed market baseline, not independent probability skill. No fee, edge or
executable trade is inferred from recording a baseline.

Independent-model forecasts require bounded uncertainty, genuinely nonmarket
external evidence and an injected independent forecast reviewer returning the
literal `True`. Historical-frequency forecasts also need this trusted training
provenance reviewer. These paths deny by default. A JSON flag asserting
independence does not grant authority. Reviewed event grouping similarly requires
an injected reviewer; unknown grouping remains unreviewed and contributes zero
independent groups. Conflicting dependency groups for the same parent event
reject rather than inflate sample counts.

Outcome admission requires an injected `outcome_validator(outcome)` returning
literal `True` after independently replaying authentic proof. A claimed
`verification` dictionary is not sufficient. Its canonical hash must match the
recorded proof hash. The integration supplies a trusted canonical proof loader;
without it all outcomes reject. Conflicting finalized outcomes need separate
review and are not overwritten. Forecasts for an already known resolved token
reject. Scoring requires forecast and cutoff strictly before settlement and the
same event, market, token and rules hash. A rule mismatch remains an unmatched
rejection rather than silently scoring a different proposition.

The earliest forecast per dependency group, kind and **model version + full model
hash + feature version** is used for descriptive scores. Repeated snapshots do
not multiply independent events. Model-specific scores remain separate. Primary
`scores` contain only reviewed independent-model groups; `baseline_scores` are
separate reviewed market-baseline groups. Unknown independence produces null
primary scores. `uncalibrated_resolved_scores` are explicitly descriptive and may
never be represented as certified model skill. Brier/log loss, reliability and
ECE are available for eligible observations; confidence intervals stay null
without sufficient independent support. None of these are trading P/L.

## Terminal view

The coordinator adds `--view events` to `uv run neraium-poly monitor` and exposes
`state["event_intelligence"]`. The monitor accepts a direct ledger summary or:

```
{
  "ledger": ledger.summary(),
  "relationships": {"qualified_findings": 0},
  "historical_qualification": {
    "events": 250, "chain_corroborated_exact_settlement_groups": 47,
    "qualified_training_events": 0, "qualified_heldout_events": 0
  },
  "rejections": {}, "experimental_opportunities": 0
}
```

Numbers above illustrate the schema; operational values must come from actual
providers. The view distinguishes **RESEARCH FORECAST**, **EXPERIMENTAL PAPER**
and **CERTIFIED PAPER**, retaining all identities at narrow phone widths and
showing unavailable/stale metrics explicitly. Physical Termius/iPhone rendering
has not been observed. Tests use controlled inputs only.

Verification in this workstream: nine controlled ledger tests plus 38 monitor
tests passed. They cover prospective timestamps, future/missing evidence, model
review, false outcome flags, append-only storage, deduplication, grouping, causal
scoring, unknown/expired rules, restart, tamper detection, ownership, storage limits
and narrow/empty/stale rendering. No fixture forecast or outcome is installed in
an operational ledger.
