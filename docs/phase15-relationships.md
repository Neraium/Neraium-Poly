# Phase 15 source-bound relationship research

## Claim boundaries and implementation

`RelationshipResearch.observe(frame, observed_at=...)` wraps the unchanged Phase
14 `UniversalRelationships` engine. It builds a bounded graph from distinct YES
contracts that explicitly share a parent event in Polymarket metadata. YES and NO
tokens of one market are never treated as separate markets. Parent membership
establishes statistical research eligibility only: it proves neither payoff
exclusivity, exhaustive outcomes, causal effects, independent events, calibrated
probabilities, nor executable opportunities.

A machine source-proof reviewer verifies raw metadata hashes, source identity,
parent/market/token identities, contract semantics, definition version and cutoff.
It is deliberately labeled `machine:shared-parent-source-proof-v1`, with scope
`shared_parent_statistical_eligibility_only`. It is not an owner or human logical
constraint approval. This wrapper installs statistical definitions only, even if
a caller labels an unsupported relation as logical.

Each quote observation replays the exact source record's hash and its associated
metadata hash against the current frame. Schema validation rejects crossed or
malformed books, missing sides, incomplete depth, mismatched identities, ambiguous
duplicate tokens, and unapproved sources. Source timestamps AND source receipt
availability must be no older than 15 seconds and must not be future timestamps.
Metadata may legitimately precede the quote; its availability must precede the
research cycle, and altered rule/question/window semantics require new review.
Sources are the Gamma metadata origin and public Polymarket CLOB HTTP/WebSocket
origins already used by the collector. Hashes demonstrate consistency with
captured source records, not independently signed exchange authenticity.

The scalar is `(best bid + best ask) / 2`, with uncertainty bound half the quoted
spread. Its semantics are explicitly USD per outcome share, **not an independent
outcome probability**. Midpoints are descriptive variables, not executable fill
prices. No trade spread-crossing, liquidity, cost, or risk authority is inferred.
Duplicate exact source quote pairs do not increase temporal persistence merely
because market discovery generated another metadata receipt.

The inherited engine fits a causal prior joint relation and checks changes in
rolling slope/correlation together with residual magnitude beyond spread and
baseline uncertainty. It preserves minimum 10-observation warmup, at least three
persistent observations, and at least 60 seconds of persistence. It is not a
single-price anomaly detector. It has no independent significance guarantee,
causal proof, calibrated forecast improvement, or executable-profit proof.

## Cross-domain interfaces

`qualify_cross_domain_driver` accepts a documented statistical hypothesis,
explicit domains, source URL, raw UTF-8 hash, source/retrieval/availability times,
and an independent review callback bound to the complete definition hash. It
defaults to withholding. Even positive review creates only a research candidate;
it does not install a logical constraint, operational link, forecast, or order.
No real weather-energy, macro-finance, political-industry, or other cross-domain
driver was independently reviewed during this experiment. Actual reviewed
cross-domain findings therefore remain zero.

## Bounds, counters and restart behavior

Default graph capacity is three pairs; configurable range is 1–20. At most one
pair per parent is selected, so a large outcome grid does not crowd out other
parents. Selection is deterministic by parent and market identifiers, with no
claim it is optimal for signal discovery. The monitored source classification is
preserved, including `other` when strong category evidence is unavailable.

Frames are limited to 8 MiB, 1,000 market records, 2,000 book records, and 64 KiB
per metadata record. Engine windows, definitions, source proofs, rejection
categories and counters are bounded. Checkpoints are limited to 8 MiB and must
also pass schema/configuration, source-definition hashes and inherited causal
baseline verification. The caller must independently verify the whole checkpoint
hash before restore and write checkpoints atomically; this module does not
replace source archives or forecast/account journals.

Counters are cumulative since instance creation or checkpoint restore:

- `cycles`: strictly increasing research cycles processed.
- `candidate_parent_pairs_cumulative`: qualified same-parent pair appearances
  across cycles; never an independent event count.
- `registered_statistical_candidates`: bounded distinct retained definitions.
- `engine.evaluations`: complete registered quote pairs actually submitted to the
  joint engine; rejected source records do not become evaluations.
- `statuses_cumulative`: per-evaluation warmup/observation/rejection outcomes.
- `source_rejections_cumulative`: per-record or registered-pair source rejection
  counts, distinguished by explicit reason keys.
- `engine.persistent_findings`: newly announced persistent descriptive changes;
  not trades, forecasts, or profitable signals.

Restore preserves accumulated counters, frozen baseline evidence and persistence.
Reobserving an exact quote pair cannot duplicate evidence. Earlier or equal
research times are rejected. No source archive, account, service, or approval
state is modified by this wrapper.

## Bounded authentic experiment

The local read-only collector endpoint `/api/market-frame` on port 18742 was
sampled every 20 seconds, starting 2026-11-06 20:35:28 UTC. Capture was bounded to
25 cycles and 32 MiB. Only six YES-token source books and metadata for three
shared parents were retained per cycle; whole response hashes were recorded
without retaining all unrelated markets. Each immutable cycle file records actual
request/receipt time, exact selected records, whole-response SHA-256, and the prior
cycle file hash. SHA chaining detects changes relative to the retained chain head;
it does not imply external timestamp notarization or retention of the full HTTP
response. No fixture was counted as a real observation.

| Parent event | Distinct market IDs | Observed contract questions |
|---|---|---|
| 1243079 | 6099746 / 6099748 | Venezia FC / Udinese Calcio win November 6 |
| 1244078 | 6104867 / 6104872 | Hamburger SV / Borussia Mönchengladbach win November 6 |
| 1244079 | 6104870 / 6104879 | Toulouse FC / RC Strasbourg Alsace win November 6 |

These are identifiable football questions, but the existing structured
classification projects them as `other`; this experiment does not invent stronger
category metadata or claim cross-domain findings. Separate win contracts are
not assumed exhaustive: a draw, cancellation or rule difference can matter.

The experiment is short prospective research, not an out-of-sample strategy
backtest or certification cohort. No independent event outcomes, forecasts,
execution assumptions, or profits are generated.

## Controlled verification

Synthetic unit fixtures cover duplicate outcome tokens, shared-parent semantics,
source hashes, stale/future/incomplete/mismatched books, metadata rule changes,
spread uncertainty, default-denied drivers, chronological replay, constant-price
withholding, checkpoint corruption, restart continuity and capacity limits. They
are kept separate from authentic capture records.

## Observed experiment result

The completed capture spans **20:35:28.738361–20:43:28.727887 UTC** on
2026-11-06, approximately eight minutes. All 25 cycle files were retained and
hash-chain replay succeeded. This limited duration is not sustained-production
certification and does not establish economic skill.

- 708,201 bytes of immutable cycle evidence, below the 32 MiB capture budget.
- 150 authentic selected source-book records across six tokens and three parent
  groups; 25 distinct source-book hashes per market.
- Source quote age ranged 0.234382–11.750061 seconds; maximum receipt-availability
  age was 11.075126 seconds. All admitted quotes met the unchanged 15-second cap.
- 75 complete pair evaluations: 30 warmup, 30 withheld for insufficient joint
  variation, 15 observing joint relationships.
- Zero source-quality rejections in this small selected cohort; this does not
  describe quality across the entire 200-market universe.
- **Zero persistent changes, zero reviewed cross-domain findings, zero reviewed
  logical constraints, zero executable opportunities.**
- No forecasts, outcomes, simulated orders/fills, or account changes were created.

Evidence resides under `data/phase15/sii/`: append-only `cycle-000.json` through
`cycle-024.json`, `analysis.json`, `results.json`, and
`research-checkpoint.json`. The bounded capture and replay scripts are preserved
there as research evidence. Immutable files are created exclusively; no original
record was replaced. Capture/hash verification and chronological analysis were
run after the final cycle completed.

| Integrity identity | SHA-256 |
|---|---|
| Final cycle / chain head | `23a81707d59a10a75b2dbfe5839b6404a9007e8219fa44f3de8cd429043ceeda` |
| Ordered cycle manifest / dataset | `8e976c1e4854024961c908d19b86b8fd05f3371e077d82d806710fe18315b882` |
| Research checkpoint bytes | `402d8dbaada1627c21e8046b26f3cdf7ca8705a715fe579ad0276d2f093663d3` |

Actual concurrency was one network sampler process overlapping development and
single-process test runs. No additional CPU pool, service, or strategy was started
by this workstream. Final targeted validation: 49 tests passed across Phase 15
relationships, inherited Phase 14 relationships, and Phase 15 domain research;
Ruff passed. These test fixtures are excluded from all observation counts above.
