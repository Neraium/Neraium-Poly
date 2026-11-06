# Phase 12 canonical event data and specialization

The event corpus preserves actual event time separately from availability time.
A historical chart downloaded today is not evidence available before its event
resolved. No past book is inferred from a chart or a current quote.

## Interface and reproducibility

`build_dataset(source_dir, qualification_dir, output, chain_dir=...)` verifies the
original acquisition bundle and qualification row bindings, replays archived
finalized Polygon CTF proofs, then writes a new versioned directory.
`load_dataset(directory)` returns `manifest`, `events`, `evidence`, `outcomes`
using the shared `CanonicalEvent`, `EventEvidence` and `VerifiedEventOutcome`
contracts. It validates file hashes, manifest identity, evidence payload hashes,
proposition links, token/rule/payout matching and outcome verification digests.
Output never overwrites an existing dataset. Combined artifacts are bounded to
512 MiB with an 8 GiB free-disk floor.

Canonical market propositions retain parent event ID, market ID, outcome token
mapping, exact question/rules/source, actual known creation/closing time, scheduled
end time as separately labeled provenance, source and receipt time, category,
proposed dependency group and missing fields. Current rule text is not asserted
to be the rule version available at a historical prediction. Token orientation
comes from the original Gamma array, not from price or outcome-name guesses.

Every historical price/context observation keeps its original source record,
source/raw hash, timestamp, receipt time, and current-download availability basis.
Book evidence is included only when genuinely present. Verified outcomes require
matching original API payout and replayed final CTF inclusion evidence; outcome
proofs preserve exact block time and acquired-now availability. HTTPS RPC proof
replay is attributed evidence, not independent node consensus verification.

Authoritative actual dataset:

```
data/phase12/dataset-v3
SHA256 9e20ac5ccaef7616c2f0047df789a696916ff0d4b3d7d3938334bb190f77353d
```

Preliminary v1/v2 artifacts remain retained, but their outcome proof hash used the
inner proof before the shared ledger contract required hashing the entire
verification dictionary. They are not the authoritative delivery artifact.

## Qualification funnel

| Stage | Actual count |
|---|---:|
| Canonical market propositions / reported parent groups | 250 / 250 |
| API-verified final outcome groups | 51 |
| Independently replayed finalized CTF outcome groups | 47 |
| Historical market-price observations | 616 |
| Actual historical executable book rows | 0 |
| External observed METAR rows | 95 |
| Total evidence records, including metadata/rules | 1,211 |
| Resolved events with a predecision-available price | 0 |
| Reviewed independent events | 0 |
| Fully qualifying training / held-out events | 0 / 0 |
| Required independent training / held-out events | 100 / 100 |

All 250 retain missing historical executable depth, historical rule-version
verification, predecision availability, independently reviewed grouping and
qualified external context. Forty-seven exact settlements do not repair these
other gaps. Eventual payouts never enter feature records as historical knowledge.
One political event contributes 520 prices; these are one event, not 520 samples.

## Specialization decision

`run_categories(dataset)` ranks research suitability, not trading return. It
keeps unsupported reliability/spread/liquidity/skill metrics null, and records
why alternatives are deferred. Actual corpus aggregation:

| Category | Propositions | Proposed dependency groups | Corroborated outcomes | Independent context observations |
|---|---:|---:|---:|---:|
| Sports, including tennis/PPA | 52 | 52 | 21 | 0 |
| Weather | 2 | 2 | 0 | 95 |
| Financial events, including crypto/up-down/index | 183 | 53 | 25 | 0 |
| Politics | 1 | 1 | 1 | 0 |
| Entertainment/esports | 12 | 12 | 0 | 0 |
| Economics | 0 | 0 | 0 | 0 |

**Sports** is primary for outcome-linkage and prospective event research: 21 of
52 propositions have corroborated outcomes, compared with 25 of 183 financial
propositions, and clear winner/rule identities can support future evidence
collection. Distinct proposed parent groups are still unreviewed, not independent
samples. Independent predecision features remain missing.

**Weather** is secondary, prospective context-first research: the corpus has
95 authentic station observations and explicit temperature/station rule sources.
Only two events and no independently corroborated settlements are available, so
there is no training, calibration or skill claim. Station observations are not
calibrated event forecasts.

Financial events have repeated asset windows and unavailable point-in-time
external drivers/depth; the large row count is not a reason to select them.
Politics has a single event despite many chart points. Economics lacks historical
rows in this corpus. Esports has no corroborated labels and minimal price
coverage. Current live liquidity and classification from Phase 11 remain a
separate descriptive snapshot; none is retroactively inserted here. Historical
liquidity, spread, queue data, resolution reliability and independent confidence
intervals remain null. No category has qualified training or held-out evidence.

## Authentic bounded follow-up

New read-only Polygon acquisition searched blocks **96823207–96824488** for the
four remaining known unresolved conditions. **Four requests / 12,725 bytes**
yielded no matching final resolution proof. Raw unsuccessful searches remain
archived. Absence in this bounded range is not proof that settlement never
occurred. Counts remain 47 corroborations and zero qualifying train/test events.

A current official EGLC METAR probe used **one GET / 1,699 bytes**, returning four
station observations at **2026-11-06 05:14:57.514144 UTC** receipt time. EGLC is the
station named in the two historical weather rules. Those markets were already
closed; these newly acquired observations are a source-collection probe, not
predecision features for them. No probabilities or labels were derived.

References checked 2026-11-06: [NWS public API documentation](https://www.weather.gov/documentation/services-web-api)
and the actual [Aviation Weather public METAR API](https://aviationweather.gov/api/data/metar).
Current source collection retains observed station times and receipt times; it
never backdates availability. External forecast/observation values require target
mapping and independently validated uncertainty before they can support an event
probability model.

## Verification and artifacts

Focused tests exercise point-in-time gaps, rule/token payout identity, original
qualification binding, no overwrite/backfill, file/payload integrity, suspension
of unsupported metrics and authentic-source acquisition timing with controlled
fixtures. Fixtures never enter real artifacts or count as historical outcomes.
No paper account, operational service, strategy, risk limit or approval changed.

Small committable summary: `.planning/evidence/phase12-data/summary.json`.
Raw dataset, source probe and RPC responses remain in ignored `data/phase12/` in
this worktree; the integration coordinator copies fixed outputs after SHA checks.
