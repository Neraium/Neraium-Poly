# Phase 19 readiness

Verified source: `53c75e4`; latest operational check: 2026-11-07T07:42:43.891689+00:00.

## Implemented

- Fixed volume-only discovery excluding supported current-day contracts. Three bounded public
  metadata/book requests add up to 12 exact-rule research markets without evicting the broad feed.
- Preserved native WebSocket baselines on unchanged subscriptions; changed or failed streams restart.
- Added capital-reference protection, expiry grace and immutable token/settlement identity checks.
- Rejected absent/invalid native book times rather than treating receipt time as fresh source data.
- Added read-only forecast replay and an event-disjoint qualification funnel with explicit blockers.
  Source, probability model, financial settings, certification requirements and stops are unchanged.

## Genuine evidence

3 genuine prospective crypto research forecasts were recorded and replayed exactly as of 2026-11-07T07:45:56.651770+00:00.
They share one unreviewed Bitcoin parent event; neither is a calibrated or execution-authorized forecast.

| Market | Forecast timestamp UTC | Research probability | Recorded executable bid / ask |
|---|---|---:|---|
| 6771152 | 2026-11-07T07:34:24.210568Z | 0.10851174 | 0.110 / 0.120 |
| 6771162 | 2026-11-07T07:39:25.076164Z | 0.00150930 | 0.019 / 0.020 |
| 6771168 | 2026-11-07T07:44:30.777617Z | 0.00000119 | 0.003 / 0.004 |

Every forecast retains native book depth, source/availability times, full external evidence,
rule/model/dataset hashes, uncertainty and append-only recovery state. Both forecasts precede
their November 8 closing time. Model uncertainty remains [0,1]; no forecasting superiority,
Brier/log-loss advantage or profitable edge is established. Existing NFL research is preserved.
Weather/economic and other models remain withheld where evidence or contract semantics are insufficient.

Qualification: **0/100 training; 0/100 held-out**.
Native terminal outcomes, independent parent review, frozen calibration artifacts and sufficiently
large event-disjoint samples remain missing. Repeated tokens and forecast updates do not count as
independent events. The historical 250-group / 51-official / 47-corroborated dataset is not execution-certified.

High-throughput and high-conviction assessments both rejected the research candidates. There are
**zero new qualified opportunities, order attempts, orders, fills or positions**. Certified admission
remains blocked; no models were promoted. Experimental equity remains **$497.30244282**, cumulative
simulated P/L **−$2.69755718**; certified equity **$500**, P/L **$0**. Initial bankroll configurations
remain $500. Existing lifetime experimental attempts/orders/fill-events remain 13/8/6.

## Capital capacity

Hypothetical capital creates no accounts and changes no approved position/risk limits. The five
scenarios sweep actual participating depth; larger capital cannot scale profits proportionally.

| Forecast market | $500 principal capacity | $1,000 | $10,000 | $100,000 | $1,000,000 |
|---|---:|---:|---:|---:|---:|
| 6771152 | $50.00 | $100.00 | $253.91 | $253.91 | $253.91 |
| 6771162 | $50.00 | $100.00 | $420.21 | $420.21 | $420.21 |
| 6771168 | $50.00 | $100.00 | $297.41 | $297.41 | $297.41 |

These are instantaneous displayed-liquidity stress bounds using 10% participation, not authorized
order sizes or edge-supported capacity. Existing $5/$15/$25 single-order maxima remain unchanged.
Fees, latency survival, queue priority and future exits need qualification; net EV and performance
remain unavailable. Both recorded YES point estimates were below their executable asks before costs.

## Operations and verification

The bounded observation lasted 420.42 seconds: 21/22 samples fully healthy. One
subscription expansion briefly degraded the collector and recovered by the next sample. All
archive, paper-only and financial-state checks remained healthy; the interruption is retained.
Only the collector restarted; experimental service and its journals stayed running.
Latest coverage: **206 markets, 412 tokens, 290 fresh books**, WebSocket connected.
Budgets remain **200/100 GiB**, global floor **100 GiB**, free space **468.04 GiB**.
No historical originals were deleted and no AWS resources changed. Short-soak retained growth was
116,547 / 44,642 bytes/s, implying conditional 20.2 / 26.7-day service runway. These are not
24-hour representative rates or months-long retention guarantees.

**Verification:** local final comprehensive run 1,266 passed; five late timestamp cases passed.
Final GitHub backend **1,271 passed**, dashboard **five passed**, build/Ruff/dependency audits passed.
Source CI [42350903159](https://github.com/Neraium/Neraium-Poly/actions/runs/42350903159) and
main CI [42351149963](https://github.com/Neraium/Neraium-Poly/actions/runs/42351149963) passed.
All 1,547 baseline immutable files, three forecast chains/prefixes, account records and old/new
checkpoint restoration passed. Only the three forecast-discovery configuration fields changed.
Peak development used three agents, two isolated writing worktrees and two integrated pytest jobs.

## Remaining work

Accumulate independently verified outcomes and reviewed event groups; calibrate and compare frozen
models against contemporaneous market baselines. Review source independence and execution costs
before any admission change. Preserve research-only status and existing 100/100 certified gates.
Plan approved evidence retention and verified incremental index recovery; no deletion or spending
is authorized by this phase. Detailed hashes and raw evidence references are under `.planning/evidence/phase19`.
