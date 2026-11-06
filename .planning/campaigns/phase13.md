# Phase13 independent prospective sports forecasting
Status: completed
Direction: genuine external outcome forecasts and fair prospective scoring, never forced trading.
Baseline: 02e3cde6205d2a52d1cbf249aa9d88fce471b613, main, /home/ubuntu/Neraium-Poly.
Existing untracked live-inspection-20261106 evidence preserved. No stash/reset.
Checkpoint: committed baseline; new implementation separate logical commits, retained worktrees.

## Phase End Conditions
| Phase | Status | Condition | validator_retries_remaining |
|---|---|---|---|
| 1 baseline/contracts | complete | resource and service evidence; versioned contracts | 3 |
| 2 parallel sources/mapping/models | complete | bounded authentic sources and focused tests | 3 |
| 3 operations/outcomes/monitor | complete | prospective ledger integration and restart tests | 3 |
| 4 verification | complete | full backend/frontend/audit/CI and actual service capture | 3 |
| 5 delivery | complete | readiness/handoff committed and pushed | 3 |

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
| Target | ID | Type | Required | Evidence | Status | Subject |
|---|---|---|---|---|---|---|
| phase:1 | contracts | file_diff | true | backend/neraium_poly/research/phase13/contracts.py | passed | cdc4db5 verified source and bound artifacts |
| phase:1 | baseline | command_result | true | .planning/evidence/phase13/baseline.json | passed | cdc4db5 verified source and bound artifacts |
| phase:2 | source | command_result | true | .planning/evidence/phase13-sources/source-capture.json | passed | cdc4db5 verified source and bound artifacts |
| phase:2 | research | command_result | true | .planning/evidence/phase13/reproducibility.json | passed | cdc4db5 verified source and bound artifacts |
| phase:3 | independent | command_result | true | .planning/evidence/phase13/prospective-observed.json | passed | cdc4db5 verified source and bound artifacts |
| phase:3 | review | command_result | true | .planning/evidence/phase13/integration-review.json | passed | cdc4db5 verified source and bound artifacts |
| phase:3 | recovery | command_result | true | .planning/evidence/phase13/restart.json | passed | cdc4db5 verified source and bound artifacts |
| phase:4 | backend | test_result | true | .planning/evidence/phase13/final-tests/parallel-tests.json | passed | cdc4db5 verified source and bound artifacts |
| phase:4 | safety | test_result | true | .planning/evidence/phase13/verification.json | passed | cdc4db5 verified source and bound artifacts |
| phase:4 | ci | test_result | true | .planning/evidence/phase13/ci.json | passed | cdc4db5 verified source and bound artifacts |
| phase:5 | report | doc_update | true | docs/phase13-readiness.md | passed | cdc4db5 verified source and bound artifacts |
| phase:5 | handoff | doc_update | true | .planning/handoffs/phase13.md | passed | cdc4db5 verified source and bound artifacts |


## Verification and delivery context
Source HEADcdc4db51b1aee801f94decff992dcd36d9f734cb reviewed/tested/pushed.
660backendtests,5browser,builds/Ruff/scenario/replay/risk/auditspassed; CI42174347695
bothjobssuccess. Actual2genuineindependentternaryforecasts outsidebinaryledger,
34marketbaselines,0resolved,0reviewedgroups;both500/PnL0/orders/fills/positions0.
Actualtwoexperimentalrestarts preservedforecastIDs/baseprefix/accounttablehashes;
collector2981665unchanged,experimental3073639,papertrue/livefalse. No modeltrading
admission, ownercertgateunchanged, nofundedwallet/liveexecution. Allownsource/test/
docs/evidenceexplicitstaging; preserveoriginaluntrackedinspection.

Actualparallel3writingagents+coordinator, isolatednativeworktrees;2CPUworkers/study
job across2sequentialruns,2backendworkers and1browserworker(initialrunoverlap).
CanonicalNFL842games/691olderreportedresults/1embargoed/150scheduled,553causal
trainingrowsforprospectivemodelonly; historicalcert0train/0heldout,47corroborated.
Rawproofs/dataignored. Source12hrefresh+5minfailureretry64MiBcap8GiBfloor;
originalpaper512MiBstopretained,separateresearchmaycontinuewithoutorderadmission.

Post-soak discovery: pre-existing maturehorizon+askonlybook IndexError blocked
cyclesbeforeeventrefresh. cdc4db5 requiresbothsidesbeforeindexing, preservesdata
rejectionandvalidmath.4regressions+full660backend+5browserCIpassed. Explicit
existingoffline guardedmigrationpreservedenginecheckpoint/account/forecasts and
recordedold/newcodehash+reason; no uncertifiedmodelpromotion. Finalexp3073639,
source/cert2981665 unchanged. Currentmonitorhistorical47/0train/0heldout restored.
