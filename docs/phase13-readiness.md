# Phase13 readiness and evidence

Independent sports event-outcome research is implemented. No independently
validated forecasting skill or trading advantage is established. All models are
research-only; certified approval and live execution remain blocked.

## Authentic external evidence

The canonical v3 source snapshot was acquired at **2026-11-06T06:05:18.125309Z**.
Its manifest is
`e492738f48894f2c7e0aa54a0adb35a77feaa8e9081e658c963393dd7771f21d`.
It contains **842 NFL games**: **691 older publisher-reported results**, **150
scheduled games**, and **one embargoed recent result**. The source's asset update
was 05:06:25 UTC; availability for this research starts at actual retrieval,
never that publisher time or the historical game date.

The source inventory and access restrictions are in [source report](phase13-sources.md).
nflverse publishes its schedules release under
[CC-BY-4.0](https://github.com/nflverse/nflverse-data/blob/main/LICENSE.md).
Raw license, GitHub release metadata, provider asset SHA and original CSV are
retained. Attribution: nflverse contributors / Lee Sharpe schedules; normalized
fields discard odds from predictive inputs. The raw provider CSV includes unused
odds columns, retained only for byte-exact provenance. This is a community data
release, not licensed official NFL settlement verification.

NBA's [terms](https://www.nba.com/termsofuse) restrict the contemplated statistics
use, so its sports API was not collected. No qualified ATP/esports or official
NFL automated result provider is configured. Missing injuries, lineups, rest
adjustments, roster changes, historical availability and official finality are
explicit. Missing sources are not replaced with fixtures.

## Mapping, model and experiment findings

The actual monitored universe supports exact mappings for two winner contracts:

| Polymarket market | Underlying NFL game | Scheduled start UTC |
|---|---|---|
| 5920626 Lions vs. Dolphins | 2026_09_DET_MIA | 2026-11-08 18:00 |
| 5968098 Bills vs. Vikings | 2026_09_BUF_MIN | 2026-11-10 01:15 |

Their four outcome tokens are two games, not four independent events. Full
questions, tokens, original rules and actual book timestamps are preserved with
registered forecasts. The mapper supports only one audited NFL winner template;
spreads, totals, fuzzy identities, mismatched schedules and unsupported rules
quarantine. Moved schedules are not silently matched to an old contract.

A conservative independent participant/opponent historical-frequency model uses
Dirichlet(1,1,1) win/tie/loss proportions. It has no market-price feature or
calibration claim. NBA Elo/frequency code is tested but has no licensed real-data
activation. NFL Elo is rejected because its expected-score estimand cannot be
advertised as unconditional win probability.

At the frozen experiment cutoff **06:07:27.426096 UTC**, **553** prior causal
games fell within the 730-day window. Participant counts were MIA33, DET34,
MIN34 and BUF37. Actual independent research estimates were:

| Selected team | P(win) | P(tie) | P(loss) | Expected payout if completed under supported rules |
|---|---:|---:|---:|---:|
| Lions | 0.588589 | 0.027402 | 0.384009 | 0.602290 |
| Bills | 0.512162 | 0.026014 | 0.461824 | 0.525169 |

These frozen experiments are **unrecorded research estimates**, not operational
forecasts, a win record or tradeable opportunities. Uncertainty bounds are broad
heuristic sensitivity envelopes, not calibrated confidence intervals. No injury
or lineup facts were invented. The current model SHA is
`886b8b4054711106a7bccfc086f461d33e8984a05cef16db2e94db665c197654`.
The model version is `sports-independent-baselines-v1/frequency`.

Two independent CPU studies (model candidates and evidence qualification) used
actual overlapping processes **3066745/3066748**, one numerical thread each.
A second bounded two-worker replay produced **byte-identical** model and
qualification reports at the same cutoff. Runs were sequential; four worker
launches are not four concurrent CPU workers. Manifests record actual intervals,
RSS, source/model hashes, null skill metrics and a research-only model registry.

## Historical qualification and outcome limitations

Phase12's **47 corroborated historical settlement groups** and all archived
observations remain. Formal qualification remains **0 training / 0 held-out**
against the unchanged **100 / 100 independent-event** requirement. Current NFL
retrievals do not establish historical predecision availability, independently
verified sports labels, executable depth vintages or calibrated held-out forecasts.
The 691 publisher reports are not 691 certification-qualified events.

Both prospective ledgers are append-only. New NFL win/tie/loss records use a
separate typed journal; Phase12 market baselines stay labeled as baselines.
Scheduled result checks require both strict native/finalized CTF proof and
matching separately published sports scores. No resolved result or profitable
trade is claimed before those observations actually exist. Ties/refunds require
a future fractional-proof schema and stay unresolved. Unsupported v2/negative-risk
or disputed settlement variants still reject.

The SII-inspired layer tracks persistent model/quote relationship changes against
causal temporal baselines. Its residual uses expected payout for NFL, not P(win).
Repeated evidence does not add persistence, distinct regime findings survive
restart, and no relationship finding authorizes a trade.

## Runtime observation and verification

Final live capture, restart checks, full tests and CI are recorded below after
verification. The source collector and both paper-account histories are preserved.

At **2026-11-06 06:21:16 UTC**, the collector monitored **200 actual markets /
400 outcome tokens**, with **302 fresh books**, WebSocket connected and producer
health `ok`. These are timestamped observations, not permanent guaranteed counts.
Gap recovery still withholds invalid/stale books; high message counts are not
forecasting evidence.

The automatic forecaster recorded these **two genuine prospective independent
ternary research forecasts**, separately from **34 market-baseline forecasts**:

| Market / selected side | Forecast UTC Nov6 | P(win) | P(tie) | Model expected payout | Contemporaneous quote midpoint |
|---|---|---:|---:|---:|---:|
| 5920626 / Lions | 06:16:42.614376 | 0.588589 | 0.027402 | 0.602290 | 0.745 |
| 5968098 / Bills | 06:16:48.580897 | 0.512162 | 0.026014 | 0.525169 | 0.625 |

The actual source books came from `https://clob.polymarket.com`:

| Market | Source timestamp UTC | Receipt UTC | Best bid / shares | Best ask / shares |
|---|---|---|---:|---:|
| 5920626 | 06:16:28.794 | 06:16:38.894704 | 0.74 / 27,571.92 | 0.75 / 54,426.83 |
| 5968098 | 06:16:39.439 | 06:16:43.958759 | 0.62 / 24,044.63 | 0.63 / 29,848.16 |

Full observed depth, token IDs, parent IDs, source snapshot, rules, model/data
hashes and uncertainty are in `.planning/evidence/phase13/prospective-observed.json`.
Actual runtime external retrieval was **06:16:37.146177 UTC**, after the earlier
frozen v3 experiment and before both registered forecast cutoffs. Forecast IDs:

- Lions: `f18c896710653d210eee5d140fc08a035f9adf9bae7bb2e07ca3456228ce16d1`.
- Bills: `47697de92df0a8cf359d87dfa4ef7a9bf6759a1ee88331426c111809526ab56e`.

The quotes are expected fractional contract payouts, not market unconditional win
probabilities. Their differences from model expected payout are unvalidated
research residuals, not transaction-cost-adjusted edges or trade authorizations.
Prediction horizons derive from the original scheduled starts; exact settlement
horizons remain unknown under postponement/no-result rules. Four-hour scheduling
of a resolution check is not a promise of finality.

**Two ternary pending, zero resolved, zero reviewed independent event groups.**
Binary independent ledger forecasts remain zero. Brier, log loss, reliability,
calibration, superiority confidence bounds and realized research performance are
unsupported/null. There were zero genuine outcome checks yet because the games
remain in the future. The automatic future adapter was exercised with controlled
HTTP/RPC/result fixtures; this is not a claim of an observed live settlement.

Both accounts retain **$500 cash/equity, $0 simulated P/L, zero orders, fills and
positions**. No independent strategy is enabled for trading. Standard/higher/
exceptional sizing, 20% exposure, correlation controls and certified approval
remain unchanged. The terminal broker's unsupported event-execution capability
was not bypassed, and no fees/slippage/queue assumption was turned into profit.

The existing experimental unit was restarted twice after passing local
checks and once more after a reviewed guarded code migration. Both forecast IDs, the complete existing 102-record baseline prefix and
account/positions/reservations/orders table hashes survived, with no duplicate
forecast. Collector/certified PID **2981665** was unchanged. Experimental PID after
recovery is **3073639**. Both running environments explicitly contain
`PAPER_TRADING=true` and `LIVE_TRADING_ENABLED=false`; post-repair health was `ok`.
No service definition, funded wallet or unrelated workload was changed.

The mobile event view now shows genuine ternary counts separately from baseline
counts, source status, actual model versions, mapping failures, null scores,
settlement progress and both account identities. `Upcoming` is distinct mapped
games in the last eligible frame; map rejection counts are cumulative token-row
rejections since Phase13 initialization, not unique rejected games. Journal counts
are durable current state; repeated forecasts do not multiply independent events.
Historical qualification is refreshed on the baseline cadence. The live soak also
found an existing missing-bid indexing defect that aborted mature-horizon cycles;
the guard was repaired without relaxing missing-liquidity rejection. An explicit
offline hash-guarded migration preserved its quote checkpoint and counters. After
repair, cycles again reject missing liquidity normally and the monitor shows
47 historical groups and0/0 qualifying training/held-out events.

## Software certification and actual concurrency

Final local backend run: **660 passed** in two simultaneous processes (**345 +
315**). Earlier passes had655 and656 tests; the final run also includes four missing-side
regressions for a genuine live-soak defect. Five browser tests, TypeScript/Vite build, Ruff,
scenario/replay, provenance, mapping, leakage, model reproducibility, immutable
forecasts, settlement, cancel/postpone/correction, risk/isolation, restart and
narrow monitor checks passed. A FastAPI/Starlette test-client deprecation warning
remains; there were no test failures. Python runtime and frontend audits found no
known vulnerabilities. Test-scenario fills are fixtures and are never operational
paper activity.

[GitHub CI 42174347695](https://github.com/Neraium/Neraium-Poly/actions/runs/42174347695)
passed both jobs on source **`cdc4db5`**, including **660 backend tests**, **five
browser tests**, builds and audits. Source, raw data and account evidence are
separate: raw datasets/databases remain ignored; bounded public summaries are
committed. The final report/evidence commit changes documentation only.

Genuine development concurrency was **three writing agents plus coordinator**,
using the native isolated worktrees `poly-phase13-sources`, `poly-phase13-models`
and `poly-phase13-operations`. Research jobs used **two actual CPU workers** each;
two jobs ran sequentially. Backend tests used two processes, with one browser
worker and its test API overlapping the initial backend run. Final backend worker
PIDs and all measured analysis intervals are in `concurrency.json`; no claim is
made about total host processes or all 32 CPUs being allocated. Initial resources
were 32 CPUs,238GiB available RAM,19GiB free disk and load0.79. Later disk was
17GiB, above the preserved8GiB floor. No unrelated cleanup occurred.

Reviewed integration fixes include the external settlement-reference type
boundary, post-acquisition timestamp ordering, exact publisher-result binding,
source score embargo/report-integrity checks, typed journal recovery/identity,
model replay, extreme ternary normalization and distinct SII finding counts.

## Phase14 recommendations and remaining blockers

1. Let the two actual pre-event forecasts mature; verify native/CTF outcomes and
   separately published results. Record failed checks and corrections without
   forcing labels. Acquire a licensed official NFL result/status feed if available.
2. Add a reviewed, append-only event-dependency/independence registry. Two games
   are insufficient; repeated tokens, daily forecasts and shared-team schedules
   cannot manufacture independent samples. Freeze untouched prospective cohorts.
3. Extend typed fractional tie/refund settlement and verified sport-specific
   multi-outcome evaluation before claiming complete NFL result coverage. Current
   ties/cancellations/disputes remain unresolved, producing explicit coverage bias.
4. Acquire legitimate pre-start injury/lineup/roster/rest vintages where permitted.
   Compare the simple baseline against causal home/away and regularized challengers
   only with appropriate chronological evidence. Never use betting prices as hidden
   independent features.
5. Support version-specific replay of archived source parsers/models. Current
   replay fails closed after incompatible upgrades until explicit version rollback
   or reviewed replay is available. ResearchRegistry rollback has no trading effect.
6. Monitor bounded storage. Sports research remains separately bounded even if
   the original paper archive stops admission; exhausted evidence is preserved.
   Plan reviewed lossless archival rather than deleting audit history or silently
   increasing exposure/data tolerances.
7. Maintain certified 100/100 qualification and explicit owner approval. Neither
   these research forecasts nor eventual Brier improvement alone authorizes event
   trading, proves cost-adjusted edge or changes the existing paper-only mode.


Final post-soak source is `cdc4db51b1aee801f94decff992dcd36d9f734cb`.
The missing-bid fix only requires both quote sides before diagnostic indexing;
valid-book mathematics and all strategy admission thresholds are unchanged.
`guarded-migration.json` records the exact prior/new code hashes and reviewed
reason. Final account/forecast preservation and healthy source timestamps are in
`post-soak-service-check.json`. The initial CI and pre-soak tests remain archived
separately; final CI includes660backend/5browser passes.

For API compatibility, legacy top-level `independent_model_forecasts` and research
status fields describe the Phase12 binary ledger. Genuine NFL ternary research
counts and versions live under `event_intelligence.sports`; the event terminal
uses those fields. Zero binary independent forecasts does not mean zero NFL
ternary research forecasts. Neither counter represents enabled trading models.
