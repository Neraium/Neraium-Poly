# Phase 11 research findings and readiness

**No strategy demonstrates a credible, repeatable, cost-adjusted advantage on the
available evidence.** A directional classifier improved some scores but worsened
calibration. This phase delivered reproducible research infrastructure, explicit
failed hypotheses and isolated adaptive research, without activating a model.

Verified source: `1f30a2335c724b8df8bbcb447fd0db05f8f569b8`, pushed to main after
reviewed worktree integration and full local gates. Baseline `e4122b0` preserved.
The final documentation/evidence commit follows that source; GitHub CI ignores
Markdown and `.planning/` changes.

## Actual services and trading observations

Capture **2026-11-06 04:55:34.430982 UTC**:

| Observation | Actual value |
|---|---:|
| Public markets / outcome tokens | 200 / 400 |
| Fresh source books | 299 / 400 |
| Experimental selected tokens / fresh books | 64 / 48 |
| Experimental cash/equity / simulated P/L | $500 / $0 |
| Certified cash/equity / simulated P/L | $500 / $0 |
| Experimental attempted/submitted orders, fills, positions | 0 / 0 / 0 / 0 |
| Certified orders / positions | 0 / 0 |

Both services were healthy and the public WebSocket was connected. Collector PID
**2981665** was preserved; experimental PID **3034662** follows the authorized
restart. Both process environments retain `PAPER_TRADING=true` and
`LIVE_TRADING_ENABLED=false`. Risk, account, broker, operational strategy and
operational intelligence code are unchanged from Phase 10. The research update
added only a bounded read-only summary to the experimental API. Before/after
account tables were identical, no operational code-hash migration was needed,
and tracing retained epoch **04:22:19.671107 UTC**.

Fresh quote evidence, not fills:

| Market | Source timestamp UTC | Best bid / shares | Best ask / shares |
|---|---|---|---|
| 5458682, first outcome | 04:55:33.237000 | .59 / 2,306.84 | .60 / 15,892.60 |
| 5458682, second outcome | 04:55:33.237000 | .40 / 15,892.60 | .41 / 2,306.84 |
| 559652 | 04:55:33.542000 | .125 / 221.00 | .128 / 49.78 |

Full token IDs, receipt timestamps, book IDs, source URLs, health, flags, limits,
reconciliation and raw capture hashes are in
`.planning/evidence/phase11/observed-state.json`. Public endpoints remain Gamma,
CLOB and the Polymarket public market WebSocket; experimental research reuses the
existing collector and its authentic archive. No wallet or financial order path
was connected. Counts are observations at capture, not promises about later
liquidity or service status.

At the latest completed engine evaluation, **04:55:33.705945 UTC**, all six
strategies considered 64 tokens, with 48 valid data observations each. Short
horizon produced 43 candidates; the other five produced zero. Every strategy had
zero qualified opportunities, risk rejections, order attempts, submitted orders
and fills. Edge and missing-evidence gates reject before portfolio admission;
zero trades were neither manufactured nor attributed to a broken broker.

## Reproducible experiments and dataset

See [architecture](phase11-architecture.md), [microstructure](phase11-microstructure.md),
[model research](phase11-models.md) and [segments/evidence](phase11-segments.md).

The immutable dataset contains **30,000 authentic book observations**, **34
markets**, **65 tokens**, **20 reported event groups**, and **zero independently
reviewed events**. Source timestamps span **03:34:59.236–04:41:30.222 UTC**;
receipt availability spans **03:35:04.111574–04:41:30.279472 UTC**. Source SQLite
high-water is **77789**. Dataset SHA-256:

```
4bca310fb839d1f8a24ddaa334e71147f374bef83f3f8546014ee726f540c95d
```

Full depth was reconstructed from actual immutable full books, deltas and
receipts, with source hashes verified. Point-in-time metadata and fees were
matched as of each quote. **2,549** observations lacked fresh fee evidence;
missing context was never filled from the future. This is a bounded sampled
archive, not complete tick history or guaranteed future liquidity.

Experiment **eb8577019f445ac1ad5edde5a238e696** binds feature/target definitions,
model versions, intervals, grouping, costs, failure cases, limitations, source
file hashes and result hashes. A second real execution reproduced **all three
quantitative output files byte-for-byte**: models, microstructure and
relationships. Worker identities, generation times and summary timestamps are
operational metadata and appropriately differ.

## Forecasts, baselines and calibration

Strictly chronological **26,475** supervised 60-second observed-bid labels;
**915** boundary labels were purged. Splits:

| Split | Labels | Decision interval UTC |
|---|---:|---|
| Training | 15,521 | 03:35:34.486634–04:13:54.554327 |
| Validation | 4,803 | 04:14:56.077820–04:26:32.226959 |
| Held out | 5,236 | 04:27:34.062315–04:40:28.583172 |

Features precede decisions; training labels must mature before the next split.
Model/temperature choices use validation only. **18 reported event groups overlap
training and held-out sets**, and independence is unreviewed. This is purged
chronological quote forecasting, **not** event-independent strategy certification.
No independent confidence interval is asserted. Targets require actual future
observations with mature source/receipt times; a displayed bid is not a promised
fill. All 30,000 captured decision contexts had active point-in-time metadata and
rules; explicit lifecycle/horizon guards also reject unsupported future datasets.

Held-out mark MAE, USD/share:

| Model | MAE |
|---|---:|
| Unchanged bid — selected on validation | .00081818 |
| Training mean change | .00082231 |
| Regularized ridge | .00089008 |
| Current midpoint | .00441377 |

The exact existing operational horizon helper was separately replayed on **5,224
identical eligible held-out rows**: MAE **.00151804** versus unchanged bid
**.00081776**, about **85.6% worse**. New challengers were not silently substituted
into operational trading. Ensemble/boosted complexity was deferred because the
simple baseline won; no advanced model has demonstrated independent improvement.

Bid-rise probabilities predict **a 60-second observed bid increase**, not terminal
settlement. Held-out results:

| Model | Brier | Log loss | ECE |
|---|---:|---:|---:|
| Historical frequency | .07450047 | .28172831 | .00894640 |
| Bayesian frequency | .07449949 | .28172096 | .00889126 |
| Logistic | .07148484 | .26202902 | .02976831 |

Logistic improved Brier by about 4%, while ECE worsened substantially. Validation
selected temperature 1.0, so calibration scaling did not repair this discrepancy.
Reliability bins, temporal blocks and per-token scores are preserved. Overlapping
labels, event dependence, limited time/regime coverage and unverified economic
translation prevent a credible-advantage claim. **Terminal Brier, terminal log
loss, terminal calibration and certified profitability remain null.** A current
market price is not an independent terminal-probability estimate.

## Microstructure and execution costs

There were **28,976** valid feature rows. Fixed causal features measure spreads,
top-five imbalance, concentration, quote persistence, prior volatility and depth.
The study evaluates **6,000 retrospective quote-capacity scenarios**, not orders,
fills, portfolio returns or guaranteed executions. It uses actual post-100ms
entry asks, later bid depth, 10% displayed participation and timestamped fees.
Unknown fees, inadequate depth/minimum lots and missing mature books reject.

| Target USD | Complete known-cost scenarios | Median net difference, existing fee bound | Exponent-1 protocol-curve sensitivity |
|---|---:|---:|---:|
| $2 | 633 / 768 | −$0.33027 | −$0.27971 |
| $5 | 1,433 / 1,744 | −$0.65626 | −$0.26993 |
| $15 | 1,325 / 1,744 | −$1.94531 | −$0.75912 |
| $25 | 1,286 / 1,744 | −$3.31897 | −$1.24944 |

**Zero scenarios remained positive with an additional $.01/share/leg stress under
either fee treatment.** Exact-curve values are explicitly research sensitivity,
restricted to observed compatible fee parameters; operational broker/reservation
fees were not changed. Additive stress is a conservative cost bound, not an
assertion that arbitrarily adverse executions physically occurred. Queue
priority, passive fills, realized market impact and passive profitability remain
null: displayed snapshots alone do not identify them. Scenarios do not authorize
higher-tier or exceptional orders; all operational risk limits remain intact.

## All six strategy hypotheses

| Strategy | Measured finding / evidence | Research disposition and disable condition |
|---|---|---|
| Short horizon | Current estimator loses to unchanged bid; no surviving supported edge | Exploratory only; suspend models worse than baseline; no operational replacement |
| Persistent relationship | 7,990 valid paired observations; 500 learning and 7,490 ordinary; zero persistent findings | Exploratory descriptive research; missing complete fresh pairs or qualified context blocks action |
| Cross-market consistency | Zero independently reviewed logical constraints | Suspended from executable research selection until payoff scope and multi-leg execution are supported |
| Liquidity spread | Aggressive costs unfavorable; passive queue/inventory evidence unavailable | Suspended from executable research selection until two-sided inventory and adverse-selection/queue validation exist |
| Event driven | Independent predecision event-response context unavailable | Suspended research; no context or independently tested response model means no signal |
| Calibrated forecast | Bid-rise classifier is testable; certified terminal outcomes/context absent | Suspended terminal-strategy research; directional scores cannot replace terminal calibration |

Statistical relationships remain distinct from enforceable logical constraints.
SII analysis requires temporal baseline, persistence, source alignment, context
and significance. Missing/stale/reused pairs cannot inflate persistence; known
peer expiry suppresses evidence. A relationship shift would still need separate
edge and execution qualification. Structural-change false positives, logical
arbitrage profit and independent structural confidence intervals remain null.
Research suspension labels do not mutate existing operational registration: its
six guarded research candidates remain as before, with only two supported
experimental admission paths and no new qualified trades.

## Segment comparison

Current official-tag enrichment used **50 archived public GETs / 13,923,029 bytes**.
Capture was **04:41:00 UTC**; tags were acquired later and are descriptive only.

| Segment | Markets / tokens | Statically research-suitable tokens | Median spread |
|---|---:|---:|---:|
| Financial markets | 34 / 68 | 40 | .005 |
| Politics | 80 / 160 | 24 | 0.002 |
| Sports | 35 / 70 | 16 | 0.01 |
| Economics | 6 / 12 | 6 | 0.01 |
| Unknown | 45 / 90 | 16 | 0.01 |

Suitability means available eligible quotes/rules/minimum lots, not fee,
probability, risk approval or profit. Unknown/ambiguous tags remain unknown;
weather/entertainment cannot be inferred absent verified classification. Volume,
historical resolution reliability and evidence sufficiency remain null where
not supplied. Financial/economic contracts offer measured data-quality research
potential; this is not a profitability ranking.

A reproducible **descriptive-only** join of held-out token scores and later
current tags found unchanged bid beats ridge in every captured segment.
Held-out labels: financial 2,213; politics 978; sports 937; economics 610;
unknown 498. These sum to 5,236. The post-hoc join never enters training or
strategy selection, and missing current-universe tokens stay Unknown. Results
and both input hashes are in `segment-model-comparison.json`.

Coverage remains bounded at 200 markets/400 subscriptions. No measured evidence
justifies raising count merely to inflate activity; prioritize data quality,
new independent events and validated context first.

## Adaptive research and terminal interface

Two genuine watch iterations processed newly accumulated **10,000-observation
windows** into separate immutable datasets and model versions. Registry history,
baseline comparisons, drift deltas and source hashes are persistent. Overlapping
windows are explicitly dependent, not new independent evidence. The registry
suspends worse-than-baseline exploratory models; rollback is tested, preserves
all versions and changes only research selection. No model self-certifies or
enters either account. Four unsupported strategy families are excluded from
executable research selection.

`research-watch` is a bounded foreground command, not a new deployed daemon.
This delivery exercised two cycles successfully; persistent paper services
continue independently. Latest terminal research displays the canonical frozen
30,000-row experiment. The separate adaptive run history is retained under
`data/phase11-adaptive/`; no claim that the foreground loop remains running.

```
uv run neraium-poly monitor --view research
uv run neraium-poly research-experiment \
  --dataset data/phase11/dataset-v1 --output NEW_DIRECTORY --workers 2
uv run neraium-poly research-watch \
  --database data/experimental-paper/events.sqlite \
  --research-output NEW_RESEARCH_ROOT --max-observations 10000 \
  --cycles 2 --interval 30 --workers 2
```

The research monitor combines actual selected-scope evaluation/candidate/rate
counters with clearly labeled research baselines, calibration/evidence status,
confidence and rejection reasons. It renders at narrow phone widths; physical
Termius/iPhone rendering was not independently observed. Unknown metrics stay
unknown. Old or future-dated/malformed summaries withhold inference. Paper P/L
with stale marks is explicitly `P/L(last)`.

Research storage is bounded: 30,000 books/dataset, 512 MiB watch artifacts, 8 GiB
free-disk floor, 32 registry versions, maximum two workers/job and one numerical
thread/worker. Budget exhaustion stops research and preserves prior evidence;
there is no unbounded automatic cleanup. Final disk free was about 26 GiB.

## Historical qualification and repaired defects

**250 groups, 51 API-labelled groups, 47 corroborated exact finalized settlement
groups; zero qualifying training and held-out events.** Required thresholds stay
**100 independent training / 100 independent held-out events**. Four more bounded
read-only RPC requests, **13,276 bytes**, searched newly finalized blocks
**96819884–96823206** for the unresolved conditions; no new proof was found.
Earlier evidence, outcome timing, dependency checks, rule/context/depth gaps and
availability provenance were revalidated. A failed search does not prove absence
of settlement. Publisher archives, lifecycle or preparation timestamps were not
promoted to execution-certified evidence.

New research defects repaired and regression-tested:

- Strict loader verifies observation/source-binding hashes, counts, identities,
  ordering, official source and duplicate rejection.
- Quote persistence now safely reinitializes after long gaps without changing
  operational evidence or trading thresholds.
- Archived fee evidence IDs now satisfy the research adapter's legacy reference
  requirement; real known fees are no longer misclassified as all unavailable.
- Research horizon and relationship decisions reject missing/closed/expired
  point-in-time metadata and expired peer legs.
- Research registry ownership serializes coordinators, preserves append-only
  versions/audit and releases ownership on startup failure.
- Summary time/integrity checks suppress stale/future inference; terminal counters
  no longer cap 100k–999k values incorrectly at 99k.

## Validation, concurrency and delivery

**496 backend tests passed locally** in two actual pytest processes, and
**496 passed in final-source GitHub CI**. Five local browser tests, TypeScript/Vite
build, Ruff, replay/scenario, causal/leakage/calibration/cost/risk/account isolation,
restart and terminal checks passed. Runtime Python and frontend dependency audits
found no known vulnerabilities. Both [CI jobs passed](https://github.com/Neraium/Neraium-Poly/actions/runs/42165283884).

Actual concurrency, with PIDs and intervals recorded:

- Three concurrent writing agents plus coordinator; one separate Citadel worktree
  per writer, followed by reviewed integration branch and fast-forward landing.
- Two CPU workers/job. Full experiment PIDs **3032959/3032962**, coordinator
  **3032565**, resource tracker **3032958**: four job processes, two CPU workers.
- Replay and first adaptive job overlapped, reaching **four concurrent analysis
  tasks across two jobs**, eight job processes including their control processes.
  Across four analysis runs, eight worker launches occurred; not eight simultaneous
  CPU workers. Peak full-dataset worker RSS was about 1.9 GiB each.
- Two pytest worker PIDs **3032573/3032574** genuinely overlapped. One browser test
  worker overlapped backend testing. Controlled spawn tests also use bounded
  helper processes; this is not a complete host-wide process census.
- The 32-CPU host retained capacity for existing workloads. No unrelated service,
  repository, database, certification job or archived evidence was removed.

Key integrated commits: foundation `4a2ab3a`; coordinator `adcdf5b`; dataset
`6fd8ccd`; model research `69c62ed`; segment/monitor `ba1c71c`; final research safety
`0c326db`; descriptive segment comparison and verified source `1f30a23`.

Primary evidence: `.planning/evidence/phase11/`, plus the committed micro/segment
summary directories. Raw artifacts/datasets remain in ignored `data/phase11/`,
`data/phase11-results/`, `data/phase11-adaptive/` and `data/phase11-operations/`.
Source/file hashes bind outputs; databases, credentials and raw downloads are not
committed. Original Phase10/inspection evidence and all worktrees are preserved.

## Phase 12 recommendations

1. Collect longer forward periods and **new independent events**, retaining
   complete source/receipt depth, fee/rule versions, outcomes and causal external
   context. Replacing ineligible coverage at the same subscription cap is more
   defensible than increasing counts without evidence quality.
2. Test the directional classifier on untouched days and event-disjoint cohorts,
   including calibration drift and expected move magnitude after costs. Do not
   convert its small Brier improvement into a trading probability or promotion.
3. Require event-independence review before clustered confidence intervals or
   certification. Complete historical executable depth/context/rule provenance;
   expand bounded settlement proof searches without substituting lifecycle data.
4. Keep unchanged bid as the mark baseline. Do not add model complexity or loosen
   fees/risk merely to make the current weak hypotheses trade.
5. Research passive queue/adverse selection and logical payoff scope only with
   adequate independent data and execution capabilities. Preserve their suspension
   until that evidence exists. Certified activation still requires owner approval.
