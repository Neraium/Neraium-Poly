# Post-expansion archive lifecycle
Status: in-progress. Base1449909,main,/home/ubuntu/Neraium-Poly.
User authorizes implementation, tests, commits/push, necessary scoped service restarts.
Preserve original untracked evidence, all data, risk stops and account/model authority.
At14:47UTC237GiBRAMavailable,~484GiBrootfree,32logicalCPU,load0.43. Limit3writingagents
pluscoordinator,2testworkers,compression1thread/service. No AWS resources/actions.

## Shared interface and ownership
Storage agent owns data/segmented.py +tests/test_segmented_archive.py only.
Coordinator owns data/store.py helpers, runtime/config/monitor/fee integration.
Verifier owns tests/test_archive_failures.py and .planning/evidence/archive-review/.
Operations agent owns docs/archive-lifecycle.md +tests/test_archive_monitor.py only;
initial work read-only audit/design review until monitor interface finalized.
Separate native worktrees under3e041d43987e0512, branches citadel/poly-archive-*.

ManagedEventStore(path, *, segment_bytes,budget_bytes,min_free_bytes,compress=True,
clock=None) API: append(record)->bool, close(), count(*,kind=None,qualified=None),
get(id)->(kind,payload,digest)|None, latest(kind,limit=100)->list[dict],
replay(until=None,kind=None)->list[{kind,record}], maintain()->dict, status()->dict.
Legacy EventStore receives matching get/latest/count helpers from coordinator.
New managed store has independent exclusive owner lock and RLock. Legacy original
events.sqlite becomes immutable/read-only, never renamed/replaced/deleted; catalog
indexes entire legacy and all segment IDs/digests with crash-recoverable commits.
Each active segment stays at a unique permanent pathname; seal closes/checkpoints
before compression. No open SQLite file moved/compressed/replaced. No purge policy:
retain all originals and verified compressed copies. Finite retention => failclosed
on total archive cap or global free floor; never promise infinite lossless retention.
Catalog queries preserve old history/counts/definitions across rotation. Duplicate
IDs must compare digest across all history; interrupted segment/catalog commits
recover without lost or duplicate records. Compression temp/write/fsync/hashverify/
publishfsync; retain originals. Verify immutable manifest identities on restart.
maintain called before eachcycle under runtime lock; append enforces disk/budget
independently. status: managed,usage_bytes,budget_bytes,active_bytes,segment_bytes,
segments,sealed_segments,compressed_segments,legacy_records,records,free_bytes,
growth_bytes_per_second,remaining_bytes,seconds_to_exhaustion,global_floor_bytes,
retention_policy,health,last_error. Unsupported rates null until real timed samples.
Do not put all-history event payloads in RAM; raw SQLite indexing streams rows.

Proposed operating allocation: collector64GiB, experimental16GiB (all service data
including originals/compressed/index/state counted), segment16MiB/8MiB. Keep global
8GiBfloor and an additional64GiB operating reserve for unrelated projects. No
account/forecast DB rotation; monitored state growth consumes service budget.
Compression1thread, per-cycle bounded maintenance, production originals neverpurged.
Final budgets subject to measured preflight. Do not clear emergency stop.

## Phase End Conditions
|Phase|Status|Condition|validator_retries_remaining|
|inspect/contracts|in-progress|audit counts, budgets, consumers, shared contract|3|
|implement|pending|segmented lifecycle, integration, monitoring, fault tests|3|
|verify|pending|backend/integration/browser/audits/CI pass|3|
|observe|pending|multiple real production rotations, source freshness, histories|3|
|deliver|pending|commit/push verified evidence and exact remaining blockers|3|

## Exit Evidence
|Target|ID|Type|Required|Evidence|Status|Subject|
|phase:implement|faults|command_passes|yes|tests/test_archive_failures.py|pending|storageimplementation|
|phase:observe|rotations|file_exists|yes|.planning/evidence/archive-recovery/soak.json|pending|productionrecords|
