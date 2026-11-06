# Initial research build certification

Local certification date: 2026-11-06 UTC. Application subject: `a2de88e6c10200a046bfebac5499b481f809160a`; subsequent documentation/evidence commits do not change application behavior.

All six isolated workstreams were reviewed and integrated. The reusable `PaperWorkflow` requires an explicitly approved model and externally configured relationships; no worker, network connection or model promotion starts implicitly. The synthetic reference session and read-only public archive are separate modes.

| Check | Actual result | Scope |
|---|---|---|
| Backend pytest | 140 passed | Contracts, unit/integration, replay, calibration, walk-forward, risk boundaries, concurrency/idempotency, recovery, workflow and API |
| Ruff | Passed | backend, tests and benchmark script |
| React/TypeScript production build | Passed | Strict TypeScript and Vite production assets |
| Playwright | 3 passed | Connected backend paper workflow, navigation, mobile rendering, emergency stop and API failure |
| Python dependency audit | No known vulnerabilities found | Locked runtime dependencies; local project omitted from vulnerability database lookup |
| npm audit | Zero vulnerabilities | Frontend dependency tree |
| Public collection | 20 outcome snapshots, 20 books, zero reported errors | One bounded current REST collection, no execution |
| SQLite benchmark | 2,000 records; 4.378 s append; 0.0116 s replay; ~457 appends/s | Single process, local temporary file, FULL synchronous writes; not complete trading throughput |
| Visual inspection | Desktop/mobile passed | No page errors; no horizontal page overflow at 390 px |

Evidence: [backend output](../.planning/evidence/backend-tests.txt), [JUnit](../.planning/evidence/backend-junit.xml), [scenario](../.planning/evidence/scenario.json), [benchmark](../.planning/evidence/benchmark.json), [Python audit](../.planning/evidence/python-audit.txt), [npm audit](../.planning/evidence/npm-audit.json), [desktop](../.planning/evidence/dashboard-desktop.png), [mobile](../.planning/evidence/dashboard-mobile.png).

## Boundary coverage

- Contract validation: nonfinite inputs, invalid intervals, crossed books, timezone awareness, schema round trips.
- Data/replay: missing/stale/future data, availability ordering, changed duplicate IDs, persistence, reconnect and resnapshot, bounded retries and lifecycle distinctions.
- Intelligence/strategy: baseline sample requirements, persistence, context, settlement rules, statistical versus logical relationships, calibration uncertainty, unavailable labels, event purging, explicit model approval and global conservative fee bounds.
- Risk: market/event/correlation exposure, aggregate limits, daily losses, drawdown, settled-win high-water mark, all-loss stress, sizing, exceptional rejection, reservations, fees, duplicate approvals, causal provenance and kill switch.
- Execution: partial fills, shared depth, disappearing liquidity, obsolete snapshots across restarts, spreads, latency, cancellation, expiration, unknown risk, concurrent duplicates, lost acknowledgements, pending states and orphan-ledger reconciliation.
- Integration/browser: archived evidence-to-order pipeline, risk approval, positions and simulated P/L, restart idempotency, archive failure, live-flag rejection, public archive isolation, API cross-origin mutation rejection and emergency-stop latch.

The deterministic fixture currently buys ten synthetic shares at $0.40, models $0.08 conservative fees, and marks at $0.41: $495.92 cash, $4.08 cost exposure and $500.02 simulated equity. These numbers are verification fixtures, not a performance forecast. Repeated independent sessions reproduce economic results and model performance. Operational record IDs may be unique per session; replaying an existing ledger preserves its records and deterministic availability order.

## Known limitations

No real-market profitability is established. Calibration labels and walk-forward quotes in certification are synthetic. Real labeled datasets, independent relationship review, fee metadata, regime robustness and event-level out-of-sample research are required before interpreting actual opportunities.

Execution is BUY-only paper simulation. Maker fills approximate participation and omit queue position, adverse selection and rebates. Conservative fee bounds can exceed the exact protocol fee curve. Historical full-depth books are not assumed available. Recent trade collection is bounded to one page; public polling is bounded per round. Sustained public WebSocket operation and production-scale throughput have not been certified.

SQLite supports portable research and serialized reservations; PostgreSQL migration and multi-process deployment require separate validation. Keep risk and broker ledgers together. `PaperWorkflow` restores final decision idempotency from the archive, but temporal relationship baselines require explicit input replay after restart. The default reference scenario is intentionally in-memory. The local API is unauthenticated and binds to loopback; it is not a public production deployment.

One upstream Starlette TestClient deprecation warning recommends httpx2. Tests pass using the locked httpx version. Dependency audits report known database advisories, not absence of every security defect.

Live execution remains disabled and unimplemented. No funded wallets, transactions or production infrastructure changes occurred. Native Citadel hook trust was not established by this build; explicit checkpoints, policy review, isolated worktrees and verification evidence were used.

Remote delivery status is recorded in `.planning/evidence/delivery.json` after push and CI inspection.
