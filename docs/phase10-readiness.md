# Phase 10 observed readiness and zero-trade diagnosis

Observed **2026-11-06 04:24:51 UTC**, with the latest experimental evaluation at
04:24:43.297623 UTC. This is a bounded observation, not a guarantee of later
market freshness. Source revision `66509cadf0af7cfe80cb19c87c334c5548c1b55f` is
pushed to `Neraium/Neraium-Poly:main`. No strategy was certified or promoted.

Both systemd services are active. The unchanged collector/certified process is
PID **2981665**; experimental paper is PID **3014868** after a verified restart.
Both running environments contain `PAPER_TRADING=true` and
`LIVE_TRADING_ENABLED=false`. The live broker still rejects construction, and no
wallet, signer or real order transport was connected.

## Live workflow and accounts

- Actual public Polymarket coverage: **200 markets / 400 outcome tokens**;
  **219 fresh books** at experimental state capture, selected **64 tokens / 33
  markets**, **33 fresh selected books**. Freshness varies between API calls.
- The public WebSocket was connected; its process counter was **4,840,959
  messages**. This count is neither independent evidence nor completed trades.
- Both public source and experimental health were `ok`. A separate earlier
  capture at 04:23:11 showed a brief disconnected subscription-generation
  transition and degraded source health; it is retained, not hidden. The
  consumer rejects degraded/stale frames instead of inventing prices.
- Experimental cash/equity **$500**, realized/unrealized simulated P/L **$0**,
  exposure/reservation **$0**, attempts/submissions/fills/open positions **0**.
- Certified cash/equity **$500**, simulated P/L **$0**, orders/positions **0**;
  certification and explicit owner approval remain blocked.
- Operational orders were not manufactured. Controlled integration tests prove
  a genuinely admissible input can reach risk, reserve capital, submit paper
  orders, partially fill from post-latency depth, expire, exit and reconcile.
  Those fixtures and their P/L are never operational activity.

Connected sources remain Gamma `https://gamma-api.polymarket.com`, public CLOB
`https://clob.polymarket.com`, and
`wss://ws-subscriptions-clob.polymarket.com/ws/market`. The experimental service
reuses the collector's read-only loopback `/api/market-frame`; it does not open a
second market stream. A separate bounded public fee reader supplies fee evidence.

Fresh selected quote evidence at capture, USD/share and displayed shares:

| Market | Source timestamp UTC | Receipt timestamp UTC | Best bid / size | Best ask / size |
|---|---|---|---|---|
| 3580932 | 04:24:47.926000 | 04:24:48.876727 | .32 / 58.69 | .33 / 4,425.87 |
| 3215007 | 04:24:49.765000 | 04:24:50.812796 | .35 / 11,575.20 | .36 / 18,895.24 |
| 6675981 | 04:24:49.549000 | 04:24:50.731295 | .71 / 8,597.08 | .72 / 104,440.74 |

Full token IDs, immutable book IDs and raw file SHA-256 bindings are in
`.planning/evidence/phase10/observed-state.json`. Quotes are observations, not
opportunities or fills. Simulated entry still requires risk approval, fresh
identity-matched executable depth after latency, actual fee evidence and hard
capital/concentration limits. Exceptional unvalidated signals remain rejected.

## Actual per-strategy funnel

New counters began **04:22:19.671107 UTC** and survived restart. The following
counts end at the captured evaluation, covering **26 engine evaluations**.
"Considered" counts token evaluations, not independent markets/events. Valid
means common data gates passed before fee, forecast, strategy and risk gates.
Candidates require strategy prerequisites and numerical valuation before costs.
Rejections below are strategy-level; order-stage decisions have separate counters.

| Strategy | Considered | Valid | Candidates | Rejected | Qualified | Attempts / orders / fills |
|---|---:|---:|---:|---:|---:|---|
| Short horizon | 1,664 | 1,253 | 1,136 | 1,664 | 0 | 0 / 0 / 0 |
| Persistent relationship | 1,664 | 1,253 | 0 | 1,664 | 0 | 0 / 0 / 0 |
| Cross-market consistency | 1,664 | 1,253 | 0 | 1,664 | 0 | 0 / 0 / 0 |
| Liquidity spread | 1,664 | 1,253 | 0 | 1,664 | 0 | 0 / 0 / 0 |
| Event driven | 1,664 | 1,253 | 0 | 1,664 | 0 | 0 / 0 / 0 |
| Calibrated forecast | 1,664 | 1,253 | 0 | 1,664 | 0 | 0 / 0 / 0 |

All six are registered/enabled research candidates; only short horizon and
persistent relationship have implemented experimental order-admission capabilities.
Registration does not make the other four executable or certified.

Rejection reasons are **nonexclusive**; a token may fail more than one gate:

| Reason | Count / scope | Classification |
|---|---|---|
| Conservative round-trip edge insufficient | 1,382 each for short horizon and relationship | MARKET CONDITION / STRATEGY LIMITATION |
| Qualified persistent contextual relationship absent | 1,664 relationship | MISSING EVIDENCE |
| Reviewed exhaustive payoff scope absent | 1,664 consistency | MISSING EVIDENCE |
| Multi-leg execution/hedging unsupported | 1,664 consistency | STRATEGY LIMITATION |
| Two-sided inventory execution unsupported | 1,664 spread | STRATEGY LIMITATION |
| Queue/adverse-selection model absent | 1,664 spread | MISSING EVIDENCE |
| Independent predecision event context/model absent | 1,664 event driven | MISSING EVIDENCE |
| Independent context, verified labels and calibration absent | 1,664 forecast | CERTIFICATION DEPENDENCY |
| Stale book | 302 each strategy | MISSING EVIDENCE |
| Unknown fresh fee schedule | 130 each strategy | MISSING EVIDENCE |
| Missing book / missing liquidity | 57 / 52 each strategy | MISSING EVIDENCE |
| Insufficient causal history / matured horizon errors | 52 / 52 each executable strategy | MISSING EVIDENCE |
| Portfolio risk rejection | 0 | RISK REJECTION |

The zero trade count arises **before risk/order admission**, rather than evidence
of a blocked broker or excessively tight portfolio exposure in this observation.
No fee, edge, freshness, evidence, calibration or capital threshold was reduced.
The valuation is a future bid-mark forecast, not market price treated as an
independently calibrated terminal probability.

## Research findings and repairs

The fixed pre-change audit covers **250 cycles**, 03:53:19–04:17:06 UTC, and
**72,510 newly emitted deduplicated signals**, with **zero qualified**. It records
19,800 edge failures and 12,085 missing persistent-evidence reasons. Stored
representative samples are biased and do not establish full-universe frequency.
A separate longer archive review found negative pre-cost edges as well; exact fee
curve diagnostics also yielded no passing sampled edge. The intentionally
conservative notional fee bound remains consistent between valuation, risk
reservation and simulated charges. See `phase10-strategy-trace.md` and
`phase10-diagnostics.md` for windows, source hashes and limitations.

Causal baseline comparison: **2,083 already-observed 60-second labels**, 57 tokens,
17 reported event IDs, **zero independently reviewed events**. Model MAE was
**.00139234 USD/share** versus **.00074652** for unchanged bid, about **86.5% worse**.
Overlapping labels and cross-event dependencies prevent a defensible independent
confidence interval here. False-positive rate, Brier/log loss, execution returns,
backdated fees and profit remain **null**, not zero or claimed successes. The
empirical interval coverage statistic is descriptive, not calibration proof.

Genuine defects repaired:

1. **BUG:** transient missing books deleted SII temporal baselines. Membership now
   follows eligible metadata, while only actual complete fresh pairs produce new
   observations. Bounded retention, universe eviction and the existing 120-second
   persistence-gap reset remain enforced. This repairs evidence continuity; it
   does not establish profitable repricing.
2. **BUG:** unchanged-input deduplication hid attempted evaluations. The new
   pre-dedup funnel distinguishes consideration, validity, candidates, rejections,
   emitted signals and duplicates without changing signal mathematics.
3. **BUG:** unavailable-risk/broker error results omitted constructed intents;
   actual attempt telemetry now preserves them and records fail-closed outcomes.
4. **BUG:** emergency exit cancellation lacked durable audit events, and shutdown
   cancellation counters lagged until another cycle. Audit consumption and
   checkpoints now cover shutdown, emergency stop and failure cancellation.

The reviewed code-hash migration archived the previous hash/checkpoint and
retained the causal engine checkpoint. Before/after account tables were identical;
no bankroll, position, reservation, limit or legacy counter was reset. A second
real service restart preserved the new trace epoch and cumulative counts.

Market breadth remains 200 deliberately. The measured 04:17 universe had 148/400
metadata-eligible tokens, 272 healthy books and 38 statically operationally
eligible selected tokens. Unselected tokens lacked matured local contexts and
local fee observations; expanding discovery alone provides no demonstrated edge.
Volume is absent from the exported normalized schema, so volume statistics stay
null. Archives remain bounded and retained: budget exhaustion suspends trading;
this phase does not add indefinite archive rotation or delete prior evidence.

## Counter meanings and monitoring

```
uv run neraium-poly monitor
uv run neraium-poly monitor --view strategies --scope epoch
uv run neraium-poly monitor --view rejections --scope cycle
```

Narrow 34–45-column, 24-row rendering is tested. Unknown data stays unknown,
results remain explicitly unvalidated/paper, and Ctrl-C disconnects only the
monitor. Physical iPhone rendering was not independently tested.

- **G/R:** producer-process cumulative gap/invalidation detections and reconnect
  attempts; reset when that producer restarts. Gaps are not lost-packet counts;
  they include missing baselines, source-time/integrity and invalid-delta gates.
- **ExpEval:** number of relationship-evidence evaluations in the latest
  experimental SII observation call, replaced each cycle; not all strategy checks.
- **Legacy signals:** persisted cumulative newly emitted deduplicated signals,
  retained separately from Phase10 consideration counts.
- **Cycle:** latest engine evaluation plus subsequent admission/execution events.
  Later cycle stages can fail; service health/last completed cycle disclose that.
- **Epoch:** cumulative since the explicit timestamp; preserved across restart.
  Fills are durable positive fill events, not shares or repeated broker snapshots.

## Historical qualification and verification

The versioned dataset preserves 250 rows and all original availability times;
**51 API outcome groups / 47 exact finalized on-chain corroborations** remain.
Four unresolved locators were investigated with **14 read-only RPC requests /
510,394 response bytes**, yielding no additional resolution proofs. Preparation
logs, lifecycle timestamps and absent search results were not promoted into
settlements. Historical executable depth, point-in-time rules/context and
independence remain unqualified across all 250 groups; **0/100 training and 0/100
held-out events** qualify. No strategy certification or automatic promotion.

Validation:

- Local full backend: **446 passed**, in two concurrent pytest processes; final
  baseline diagnostic addition: **9 focused tests passed**.
- Final-source GitHub CI: **447 backend tests passed**, including the new test;
  backend and dashboard jobs both succeeded. [Run 42162301617](https://github.com/Neraium/Neraium-Poly/actions/runs/42162301617).
- Local browser: **5 passed**, one Playwright worker; TypeScript/Vite build passed.
- Ruff, replay/scenario, risk/isolation/restart/live-prohibition regressions passed.
  Runtime Python dependency audit and frontend npm audit found no known issues.
- Actual parallelism: **three writing subagents plus root** in separate Citadel
  worktrees; **two concurrent analysis CPU workers per job**, with four analysis
  job processes including coordinator/resource tracker; **two concurrent pytest
  workers**. One browser test worker overlapped backend testing. Analysis jobs
  were separate bounded runs, not all concurrent; helper processes are not CPU
  workers. PIDs/intervals are saved in the JSON evidence. Numerical threads: one
  per analysis/test CPU worker. Host: 32 logical CPUs, about 238 GiB available RAM,
  32 GiB free disk at inspection; no claim to all 32 CPUs and no unrelated cleanup.

Primary evidence: `.planning/evidence/phase10/observed-state.json`, `ci.json`,
`migration.json`, `restart-recovery.json`, `final/parallel-tests.json`,
`diagnostics-summary.json`, `baseline-summary.json`, and monitor text captures.
Full immutable inputs/RPC responses/versioned datasets remain in ignored
`data/phase10/`; operational captures and pre-migration backup are in
`data/phase10-operations/`. Existing unrelated inspection evidence is untouched.
