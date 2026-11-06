# Live-market paper integration delivery

Observed 2026-11-06T00:37:01.138320+00:00. Application checkpoint 4af0cb522e2672514008e78df0f5df8297734b8e on main, /home/ubuntu/Neraium-Poly.

The integrated real-market coordinator is running as enabled systemd unit neraium-poly-paper.service, PID2891294, at http://127.0.0.1:18742. Its observed flags are PAPER_TRADING=true and LIVE_TRADING_ENABLED=false. The earlier collector and archive dashboard remain running. The new service is separate from the synthetic reference scenario and rejects that route.

| Actual operation | Observed value |
|---|---|
| Current market batch / outcome tokens | 50 / 100 |
| Distinct real markets archived cumulatively | 250 |
| Books received / evaluation-gate attempts | 1600 / 1600 |
| Current research relationship candidates | 200 |
| Archived relationship evidence / suppression records | 800 |
| Qualified opportunities / simulated orders / fills | 0 / 0 / 0 |
| Positions / simulated settlements | 0 / 0 |
| Bankroll / cash / simulated P&L | $500.00 / $500.00 / $0.00 |
| Fresh / observed books at this instant | 0 / 100 |
| Validation reports / approved real models | 0 / 0 |
| Trading status | validation_blocked |

## Validation blocker

No authentic, reviewed real-market training/heldout dataset exists in the operational registry, and no actual candidate has a passing out-of-sample report. This is absence of validation evidence, not a claim that a real strategy was evaluated and failed. Activation requires at least100 independent training and100 heldout events with contemporaneous executable books, external point-in-time context and independently verified final labels; at least30 examples per used bin; heldout calibration and confidence-bounded improvement over raw prices; cost-adjusted heldout support; and explicit named provenance and activation reviews. Thresholds and schema are in docs/real-strategy-validation.md. No synthetic model or fabricated estimate, opportunity or profit was installed to force activity.

The service continues public REST collection and relationship evaluation. Recent findings also remain suppressed for observed data quality and context reasons: {'missing_market_data': 100, 'incomplete_context': 100, 'wide_spread_context': 100, 'illiquid_context': 4}. Exchange source time is distinct from receipt time; quiet/one-sided/stale books do not become executable merely because HTTP polling succeeds. Gamma metadata caching is not independently validated probability evidence. There is no connected WebSocket in this service.

## Verification and recovery

Final backend regression:212 passed. Browser suite:4 passed against an isolated production-build server on18940, preserving live services. Ruff, strict frontend build and dependency audits passed; known upstream Starlette TestClient deprecation remains. Controlled positive integration tests cover validation injection→evidence→risk→paper fills, partial/latency behavior, capital accounting, restart, revocation/expiry, stale/missing/misrouted data, disk budget, and settlement identity/rules. Those test inputs are explicitly synthetic and are not real-market strategy research.

An actual service restart changed the process ID while preserving $500 bankroll/cash, counters, strategy blockade and empty positions. Persistent risk/broker reconciliation is consistent. Data ledgers are durable and ownership-locked; the emergency stop persists. The service is limited to1GiB memory and one CPU, with a512MiB event-archive budget and2GiB free-disk floor; exhaustion visibly pauses collection/evaluation rather than deleting unrelated data. Export/rotation remains an explicit operator task. Automatic simulated settlement remains off until separate token-level rule and payout review is configured. No actual financial settlement or order submission exists.

## Evidence

- observed-summary.json and observed-operation.json: actual API state and source timestamps after the availability-clock fix.
- before-restart.json and after-restart.json: actual persistent restart check.
- backend-tests-final.txt/backend-junit-final.xml, browser-tests.txt, frontend-build.txt, ruff.txt, python-audit.txt and npm-audit.json: executed verification.
- Earlier first-real-cycle/service-first-state files are retained observations from before the discovery timing fix, not current readiness evidence.
- Verified release817496a was pushed to main. GitHub Actions run42138216856 passed backend and dashboard; delivery.json records the remote result and final observed state. User authorization covers this paper-only startup, commits and push. No funded wallets, real orders, deposits, AWS changes or unrelated-service stops occurred.
