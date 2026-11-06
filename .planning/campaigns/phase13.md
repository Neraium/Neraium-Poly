# Phase13 independent prospective sports forecasting
Status: in-progress
Direction: genuine external outcome forecasts and fair prospective scoring, never forced trading.
Baseline: 02e3cde6205d2a52d1cbf249aa9d88fce471b613, main, /home/ubuntu/Neraium-Poly.
Existing untracked live-inspection-20261106 evidence preserved. No stash/reset.
Checkpoint: committed baseline; new implementation separate logical commits, retained worktrees.

## Phase End Conditions
| Phase | Status | Condition | validator_retries_remaining |
|---|---|---|---|
| 1 baseline/contracts | in-progress | resource and service evidence; versioned contracts | 3 |
| 2 parallel sources/mapping/models | pending | bounded authentic sources and focused tests | 3 |
| 3 operations/outcomes/monitor | pending | prospective ledger integration and restart tests | 3 |
| 4 verification | pending | full backend/frontend/audit/CI and actual service capture | 3 |
| 5 delivery | pending | readiness/handoff committed and pushed | 3 |

## Shared integration contracts
backend/neraium_poly/research/phase13/contracts.py is coordinator-owned.
Sources: SourceArtifact + SportsGame; no provider availability before actual retrieval.
Mapping: exact aliases+schedule+rules, quarantine ambiguity. SportsMapping token maps one game.
Models: pure external SportsGame->SportsPrediction, never market prices. Unvalidated research-only.
Ops: independently replay model+external artifacts through Phase12 ledger callback; default deny.
No changes to risk, broker, strategy approval or existing ledger records.

## Active Context
Measured 32 CPUs,238GiB available RAM,19GiB disk,load0.79 at05:56UTC. Collector PID2981665,experimental3057206 bothactive.
Allocate3 writing agents and coordinator; max2 CPU research/test workers with numeric threads1. No host cleanup/new infrastructure.
Baseline frame200 markets400tokens;24 pending marketbaselines across13parents,independent0,resolved0.
Sports universe NBA11mostlyspreads/totalplus2winners;NFL3(one spread);ATP2;esports mixed. Source acquisition must prioritize supported actual universe.

## Exit Evidence
| Target | ID | Type | Required | Evidence |
|---|---|---|---|---|
| phase:1 | contracts | file_diff | true | backend/neraium_poly/research/phase13/contracts.py |
| phase:1 | baseline | command_result | true | .planning/evidence/phase13/baseline.json |
