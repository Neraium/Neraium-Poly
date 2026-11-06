---
status: active
---
# Live-market paper operation

Direction: connect real public books to persistent evidence/risk/paper workflow. No live orders, wallets, synthetic activation or forced trades. Preserve existing collector/dashboard and unrelated services while developing.

Checkpoint: main fb433ac96c9848a3b461d488b80382319dcde6ce, /home/ubuntu/Neraium-Poly. Existing untracked .planning/evidence/live-inspection-20261106 preserved. Initial collector2884107 and dashboard2884136 remain active in named tmux sessions. Host low CPU load,238GiB available memory,46GiB free disk. At most two implementation workers plus integration.

## Phase End Conditions
| Phase | Condition | Status | validator_retries_remaining |
|---|---|---|---|
| 1 inspection/contracts | existing source and process state inspected; module interfaces declared | passed | 3 |
| 2 build | real-strategy validator, public adapter and persistent coordinator tests pass | passed | 3 |
| 3 integration | restart-safe real-feed workflow and dashboard tests pass | passed | 3 |
| 4 operation | gated paper-only service runs; actual observed counters reported | passed | 3 |
| 5 delivery | reviewed changes committed/pushed; CI recorded | pending | 3 |

## Exit Evidence
Application subject4af0cb522e2672514008e78df0f5df8297734b8e, main, /home/ubuntu/Neraium-Poly. Evidence generated2026-11-06; source behavior and strategy validation are separate claims.

| Target | ID | Type | Required | Evidence | Status | Retries Remaining | Next Action |
|---|---|---|---|---|---|---|---|
| phase:1 | interfaces | file_diff | yes | backend/neraium_poly/ops/live.py | passed | 3 | none |
| phase:2 | backend | test_result | yes | .planning/evidence/live-activation/backend-tests-final.txt | passed | 3 | none |
| phase:3 | browser | test_result | yes | .planning/evidence/live-activation/browser-tests.txt | passed | 3 | none |
| phase:3 | recovery | command_result | yes | .planning/evidence/live-activation/after-restart.json | passed | 3 | none |
| phase:4 | operation | command_result | yes | .planning/evidence/live-activation/observed-summary.json | passed | 3 | none |
| phase:4 | visual | screenshot | yes | .planning/evidence/live-activation/dashboard-real-desktop.png | passed | 3 | none |
| phase:5 | delivery | command_result | yes | .planning/evidence/live-activation/delivery.json | pending | 3 | push reviewed work and inspect remoteCI |

## Decision Log
- No existing real out-of-sample dataset or approved production model exists. Build validation/approval tooling; do not label market prices independent probability evidence or promote synthetic fixture models.
- Own persistent service will use separate SQLite risk, broker, approval and event ledgers. Existing public archive remains intact. Reuse existing API only through explicit live-runtime injection.

## Continuation State
Phase5 delivery. Software and scoped systemd service implemented;212backend/4browser tests passed. Actual enabled service on18742 has persistent500bankroll and real public polling,200candidate relationships and archived evidence. Strategy activation deliberately withheld:0actual validationreports/approvals; no independently supported real-market dataset. Quiet/one-sided/stale books also suppress findings. Actual restart retained account/counters. Remaining: evidence commit/push/remoteCI, then preserve final handoff. Existing untracked previous-inspection evidence and priorservices preserved. Nativehooktrust unknown; explicit checks used.
