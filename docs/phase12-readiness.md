# Phase 12 event-outcome intelligence readiness

**No independent event-outcome forecasting skill has been established.** The
infrastructure now supports event-level research, immutable prospective records
and independently corroborated outcome scoring. Actual historical observations
fail point-in-time qualification, so unsupported performance remains null.

Verified implementation source: `da63cac9ac96c10bba5b506da90f8c9c0e44aaf1`, based
on `b84a6d7`, pushed to main after isolated worktree integration. Documentation and
verification evidence follow in a separate commit. No strategy was promoted.

## Actual running state and prospective records

Observed **2026-11-06 05:43:20.759062 UTC**:

| Metric | Actual observation |
|---|---:|
| Real public markets / outcome tokens | 200 / 400 |
| Fresh source books / selected fresh books | 276 / 50 |
| Selected experimental tokens | 64 |
| Parent events with prospective records | 4 |
| Pending forecasts | 6 |
| Market-baseline forecasts / independent-model forecasts | 6 / 0 |
| Resolved forecasts / reviewed independent event groups | 0 / 0 |
| Experimental event opportunities / event order attempts | 0 / 0 |
| Experimental cash/equity / simulated P/L | $500 / $0 |
| Certified cash/equity / simulated P/L | $500 / $0 |
| Paper orders, fills and open positions, either account | 0 |

Both services were healthy; the public WebSocket was connected. Collector PID
**2981665** was preserved; experimental PID **3057206** follows the authorized
restart and restart-recovery check. Both running environments contain
`PAPER_TRADING=true` and `LIVE_TRADING_ENABLED=false`. The operational strategy
hash, account tables and trace epoch **04:22:19.671107 UTC** were preserved. Risk,
execution, account and operational strategy/intelligence code did not change.

The six records are **token-specific market baselines**, never independent model
predictions. Their probabilities equal actual contemporaneous bid/ask midpoints.
They were recorded while the markets were reported active, with fresh books and
before known scheduled closes. Final settlement verification will determine
whether a record is eligible for scoring; a scheduled close is not a settlement.

All first records have forecast/cutoff timestamp **05:41:08.128088 UTC**:

| Market | Recorded outcome token label | Baseline probability | Book source timestamp UTC | Scheduled close UTC |
|---|---|---:|---|---|
| 6675981 | Natus Vincere | .705 | 05:41:00.575000 | Nov 6 12:30 |
| 6490622 | No | .992 | 05:40:53.578000 | Nov 6 14:55 |
| 6288562 | Yes | .074 | 05:41:02.717000 | Nov 6 17:00 |
| 6423883 | No | .0025 | 05:41:04.816000 | Nov 6 17:00 |
| 6423884 | Yes | .988 | 05:41:04.816000 | Nov 6 17:00 |
| 6423888 | Yes | .085 | 05:41:05.713000 | Nov 6 17:00 |

Outcome labels matter: a No-token price is not a Yes probability. Several records
share an underlying Bitcoin event and are not independent observations. Full
questions, token IDs, receipt times, actual executable bid/ask sizes, model/data/
rule hashes and immutable forecast IDs are in
`.planning/evidence/phase12/prospective-observed.json`. The 18 journal records
(two evidence records plus one forecast each) were independently hash-chain
verified. A second actual service restart preserved all six forecast IDs. No
fixture forecast/outcome or profit was copied into operational storage.

A later check at **05:48:59 UTC** observed **12 pending market-baseline records
across eight parent events**, from two automatic collection cycles. Independent
model forecasts, resolved forecasts, independent event groups and orders remained
zero. Counts above are timestamped observations; additional baseline records are
not additional independent evidence or trading.

At final verification **2026-11-06T05:52:04.331070+00:00**, the service had **18
pending market-baseline records across 11 parent events**, zero
independent-model forecasts/resolved forecasts/orders/fills, both accounts $500
and simulated P/L $0. Both services reported `ok` /
`ok`; fresh source books were 270.
This later count is the continuing bounded producer, not independent evidence.

## Architecture and reproducibility

See [architecture](phase12-architecture.md), [canonical data/category research](phase12-data.md),
[terminal-outcome models and SII](phase12-models.md), [forecast ledger](phase12-ledger.md)
and [future outcome verification](phase12-outcomes.md).

Canonical records preserve stable parent/market/token identifiers, exact question,
source rule text, API-reported creation/closing times, source/availability times,
price history, missing depth, verified payouts, finality provenance, category and
proposed dependency groups. Reported closing times are not substituted for exact
settlement. Missing historical rule versions and external-context qualification
remain explicit.

Authoritative dataset: `data/phase12/dataset-v3`, SHA-256:

```
9e20ac5ccaef7616c2f0047df789a696916ff0d4b3d7d3938334bb190f77353d
```

Event/evidence/outcome files and original bundle/qualification/proof hashes are
bound in the manifest. Current snapshots never become past executable books.
Original download availability remains collected-now. Two preliminary dataset
versions were preserved; v3 is the authoritative aligned-proof-contract version.

Both final-source research executions produced identical model, relationship and
category outputs. Source-file hashes, input/output hashes, process IDs and task
intervals are in `data/phase12-results/run-v2/manifest.json` and its replay. Code
fixes were versioned separately; repeated execution is not new evidence.

```
uv run neraium-poly event-research \
  --dataset data/phase12/dataset-v3 --output NEW_OUTPUT --workers 2
uv run neraium-poly monitor --view events
```

## Historical qualification funnel

| Stage | Genuine count |
|---|---:|
| Canonical market propositions / reported parent groups | 250 / 250 |
| Original API-labelled outcome groups | 51 |
| Corroborated finalized CTF outcome groups | 47 |
| Historical market-price observations | 616 |
| Actual linked historical order-book/depth observations | 0 |
| External METAR observations | 95 |
| Price observations available at their historical prediction time | 0 |
| Independent context rows before grouping | 0 |
| Reviewed independent events | 0 |
| Eligible chronological train / validation / held-out rows | 0 / 0 / 0 |
| Fully qualifying certified training / held-out events | 0 / 0 |

All **616** price rows are rejected as unavailable at the historical decision
cutoff. Metadata/rules were also collected after the historical period; current
rule text is not asserted to be the historical version. All 250 propositions
lack qualified historical executable depth, predecision availability, independent
group review and qualified external context. **203** lack exact corroborated
settlement in this dataset. These are distinct deficiencies, not summed events.

Four additional read-only RPC requests, **12,725 response bytes**, searched
newly finalized blocks **96823207–96824488** for unresolved conditions; no new
proof was found. Counts remain 47/51, not fabricated progress. A fresh official
EGLC METAR probe used one GET / **1,699 bytes**, returning four observations at
**05:14:57 UTC**. This is current external context; it was not backdated or turned
into a probability. A failed resolution search is not proof of non-settlement.

Certification still requires **100 independent training and 100 independent
held-out events**, calibrated point-in-time evidence and explicit owner approval.
Multiple prices, market outcomes or forecasts cannot substitute for those events.

## Category selection and rejected alternatives

The ranking uses the frozen historical corpus and genuine source availability,
not popularity or observed quote volatility:

| Category | Propositions | Finalized corroborations | Qualified PIT external context | Decision |
|---|---:|---:|---:|---|
| Sports | 52 | 21 | 0 | Primary outcome-linkage/prospective research |
| Weather | 2 | 0 | 0 | Secondary station/rule/context research |
| Financial events | 183 | 25 | 0 | Defer independent forecasting |
| Politics | 1 | 1 | 0 | Insufficient independent breadth |
| Economics | 0 | 0 | 0 | No frozen historical corpus |
| Entertainment | 0 | 0 | 0 | No frozen historical corpus |
| Other / Esports | 12 | 0 | 0 | Sparse outcomes/context |

Sports has the most useful audited winner-outcome linkage beyond repeated asset
windows: 46 of its 52 propositions have rule/source text. Independent feature
vintages and event/dependency review are still missing, so selection is not model
readiness. Weather has 95 authentic external METAR rows and explicit station/
temperature rules, supporting a prospective context pipeline, but no corroborated
payouts here. Its two London high/low propositions share station/day drivers;
their separate parent proposals do not make them independent.

Financial breadth includes 148 repeated Up-or-Down windows and only 53 proposed
underlying groups among 183 propositions. Politics' 520 chart rows concern one
proposition. Neither provides hundreds of independent examples. Economics and
entertainment cannot be selected on absent historical evidence. Historical
liquidity, executable spreads, depth and statistically assessed settlement
reliability remain null where unavailable.

The current baseline producer samples eligible contracts already in the selected
live universe, favoring earlier known closes. It is a generic forward recorder,
not a claim that independent Sports or Weather models are running. Live forecast
categories remain Unknown unless supported; historical category research does not
retroactively classify predictive features.

## Event probability models and calibration

Implemented research baselines/challengers:

- Actual contemporaneous token market probability.
- Earlier verified-event frequency and Bayesian frequency updating.
- Regularized logistic regression on independent numeric external features.
- Validation-only temperature calibration and reliability/discrimination metrics.
- Chronological dependency-group separation, matured-label and feature cutoffs.
- Category/horizon scoring and an independent-group bounded-loss confidence interval
  only when the required genuine rows exist.

The actual dataset permits **zero** rows for these comparisons. Actual Brier,
log loss, calibration, reliability curves, discrimination, confidence intervals
and cost-adjusted trading performance are **null**. Mathematical fixture tests
exercise these methods; their scores are not market results. Frequency estimates
from biased or correlated post-resolution samples are not silently issued as
independent probabilities. Gradient boosting and ensembles remain deferred.

This phase therefore does not prove either success or failure of an independent
outcome model: the valid scientific result is **insufficient causal evidence**.
Phase 11's unsuccessful quote-prediction findings were not reinterpreted as event
forecasting skill, and no thresholds were loosened to produce an apparent result.

## SII event relationships and execution boundary

Research explicitly separates statistical relationships, reviewed logical
constraints, causal hypotheses and executable opportunities. The historical
corpus has **120 proposed dependency groups**, **zero reviewed logical constraints**,
**zero verified causal hypotheses**, and **zero predecision price/depth evidence**.
Historical persistent findings, false-positive rate and independent confidence
intervals remain null, not invented zeros. The live temporal engine preserves
baseline/persistence state and qualifies only fresh, aligned, context-supported
observations; capture showed zero qualified findings.

A logical checker requires explicit reviewed rule hashes and payoff scope,
synchronous actual bid/ask, known fees, depth and timing. Statistical correlation
or raw probability sums cannot establish tradable arbitrage. Atomic multi-leg
execution is unsupported, so no logical check can auto-submit a paper order.

Event proposals check independent forecast provenance, calibration, uncertainty,
identity, rule hash, freshness, fee, spread and small-position liquidity. Automatic
records are market baselines and fail those independence/uncertainty requirements.
The existing isolated paper broker supports horizon marks; **terminal-event
execution is not approved**. The adapter explicitly blocks it rather than
relabelling a terminal probability as a future bid. No event strategy is enabled.
This is a disclosed capability/validation blocker, not a functioning terminal
trading strategy or risk approval. Existing supported horizon paper trading
continues through its unchanged risk engine.

The $500 accounts, $2–$5 / $5–$15 / $15–$25 position tiers, 20% aggregate exposure,
correlation/event concentration, loss/drawdown limits and exceptional-evidence
requirements remain unchanged. Event research never changes account settlement,
capital reservations, positions or P/L. No live order path was enabled.

## Persistent forecasts, resolutions and adaptation

The existing experimental service owns a separate child journal. Records are
append-only with content hashes and a chained head. A separate coordinator anchor
rejects rollback to a valid older journal; interrupted valid appends can recover.
Forecasts cannot be backdated or revised. Evidence must be available by cutoff;
book/rules/token identity and actual midpoint baseline must match. Unknown or
review-unapproved independent models, groups and outcomes deny by default.

Each known-close pending forecast can trigger a bounded future resolution check.
The service checks at most one candidate per five minutes. Native public final
resolution and payout must agree with replayed finalized Polygon CTF log, receipt
and canonical block evidence, original token mapping and original forecast rules.
Preparation logs, disputes, unsupported v2/negative-risk variants, multiple matching
logs, oversized fields and missing finality decline without fallback. Raw native
and chain responses are retained. HTTPS RPC corroboration is not an independently
verified node-consensus proof; that trust limitation remains recorded.

No prospective event had resolved at capture. Resolution collection had zero
attempts/verified outcomes because all six known closes were still in the future.
The adapter was validated with controlled HTTP/RPC fixtures, not reported as a
successful live settlement. Its automatic future path is installed inside the
existing service, not a newly deployed daemon.

Later verified outcomes score only causal matching forecasts with the same rule
hash. Scores use the original probability and its contemporaneous market baseline;
earlier baseline snapshots are not substituted. Model hash/feature versions,
category/horizon summaries, rolling calibration and independent-group counts stay
separate. Multiple forecasts do not multiply independent evidence. Conflicting
final outcomes require review and do not rewrite old forecasts.

The Phase 11 research registry is reused for versioned event model reports,
baseline comparisons, drift and research-only rollback. Current versions contain
insufficient-evidence/null metrics, not fitted real-data weights. A model cannot
self-certify or acquire trading authority. Independent validation and explicit
owner approval remain required for certified operation.

## Safety, resource limits and repairs

No existing unrelated service, database, repository, certification job or evidence
was removed. Original inspection evidence and all worktrees were retained. The
host initially had 32 CPUs, about 238 GiB available RAM and 25 GiB free disk;
observed free disk later was about 21 GiB. No unrelated cleanup was performed.

Bounds: six baseline records/cycle, 300-second default cadence, one per market/hour,
20,000 child journal records and 64 MiB journal by default; resolution attempts
reserve at most 8 MiB (native 2 + RPC 5 + bounded metadata 1), at most 15 RPC reads,
and 32 MiB total proof storage. A forward-only guard rejects ambiguous log lists
and oversized quantities before report expansion. The 8 GiB disk floor and
existing operational archive ceilings remain; exhaustion preserves evidence and
withholds research. No historical book or settlement fallback is invented.

Repaired and regression-tested defects include duplicate canonical identities,
model-copy field-validation bypasses, complementary-token post-resolution admission,
unpaired market baseline scores, nested symlink/hardlink storage aliases,
proof-report size expansion, stale decision cutoffs after proof refresh, journal
rollback, and failed-startup child-lock cleanup without garbage collection.
Unavailable event research is explicitly withheld while the paper account remains
available; its failure cannot grant financial authority.

## Verification and delivery

Final local backend suite: **569 passed**, in two real worker processes. Five
browser tests, TypeScript/Vite build, Ruff, scenario/replay, timestamp/leakage,
grouping, resolution, immutability, calibration, cost/risk, account isolation,
restart and narrow terminal checks passed. Runtime Python and frontend dependency
audits found no known vulnerabilities. Controlled fixture outputs are never
operational activity.

GitHub CI: **both backend and dashboard jobs passed** on the final implementation
source, including **569 backend tests** and browser/build/audit checks. Completed
status is preserved in `.planning/evidence/phase12/ci.json`.
[Run 42169870103](https://github.com/Neraium/Neraium-Poly/actions/runs/42169870103).

Actual parallelism: **three concurrent writing agents plus coordinator**, each
writer in a separate Citadel worktree. Research tasks used **two actual CPU
workers/job**; final replay PIDs **3056154/3056157** overlapped, with coordinator
**3056149** and resource tracker **3056153**: four job processes, two CPU workers.
Final pytest worker PIDs **3056118/3056119** overlapped. One browser worker overlapped
backend testing. Research runs were separate bounded jobs, not all simultaneous;
no claim of 32 agents or 32 allocated CPU workers. Controlled spawn tests also
start bounded helpers, not a complete host-wide process census.

Key source milestones: contracts `ed69cd6`; canonical data `cc4dedb`; models/SII
`4e2ab0e`; prospective ledger/view `50de828`; runtime integration `b1dd155`;
startup cleanup `f31c4de`; final proof bounds and verified source `da63cac`.

Primary evidence: `.planning/evidence/phase12/`, canonical data and model summaries
in their committed workstream evidence directories. Raw canonical/source/proof
artifacts are retained in ignored `data/phase12/`; experiments in
`data/phase12-results/`; actual forecast journal under
`data/experimental-paper/event-intelligence/`; capture copies in
`data/phase12-operations/`. No database, credential or raw download was committed.

## Phase 13 recommendations

1. Acquire Sports predecision schedules, roster/injury/form vintages and verified
   outcomes with exact source availability, narrowing to a reproducible sport and
   contract type. Retain independent-event/dependency review; do not pool unrelated
   winner markets into a calibrated frequency model without evidence.
2. Build Weather forward station/day datasets tied to exact rule stations and
   official forecast issuance times, not merely current observations. High/low
   contracts on the same station/day are correlated; retain that grouping.
3. Let forward baselines mature, verify their outcomes and compare prospective
   independent challengers on untouched event-disjoint cohorts. No retrospective
   price/context availability repair or post-outcome forecast insertion.
4. Continue bounded searches for the four unresolved historical locators and
   acquire genuine executable-depth/rule/context vintages. Formal qualification
   remains 0/100 training and 0/100 held out until every required field is supported.
5. Keep event execution and model promotion blocked. Design a separately reviewed
   terminal-position/settlement/risk capability only after a probability model
   qualifies; do not route it through the horizon broker by changing a label.
