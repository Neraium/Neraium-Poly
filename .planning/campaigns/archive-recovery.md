# Post-expansion archive lifecycle
Status: completed. Base1449909,main,/home/ubuntu/Neraium-Poly.
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
|inspect/contracts|completed|audit counts, budgets, consumers, shared contract|3|
|implement|completed|segmented lifecycle, integration, monitoring, fault tests|3|
|verify|completed|834backend,5browser,build,audits,CI42246335101passone9ff6d2|3|
|observe|completed|901.348s,44healthysamples,33collector/141experimentalcycles,6newsealseach,248–316freshbooks|3|
|deliver|completed|verifiedsourceandboundedproofscommitted/pushed;retainoriginalsfinitehorizonreported|3|

## Exit Evidence
|Target|ID|Type|Required|Evidence|Status|Subject|
|phase:implement|faults|command_passes|yes|tests/test_archive_failures.py|passed|e9ff6d2|
|phase:observe|rotations|file_exists|yes|.planning/evidence/archive-recovery/soak.json|passed|actual1f37342application;sameapptreease9ff6d2|

## Current checkpoint
Verifiedsourcec4f545b,pushedmain. Bootstrapworkers3164611/3164612overlapped;
838222collector/164111experimentaloriginalidentitiesandpayloadhashesverified.
ConsistentSQLitebackupcopiesretainedinsideeachservicebudget. SQLite-managedFULL
checkpointcompletedwithidenticallogicalrecorddigest;noWALmanuallydeleted.
Originallegacyfilesandnewpermanentsegmentsretained. Services3165463/3165464started
15:19UTC;bothhealthyafterstartup. Firsthealthysoakpair15:22:48UTC;sampleevery20secs,
minimum900secsand>=3newsealedsegmentsperaccount. Experimentalstopstilllatched,
noapprovedcertifiedstrategy,liveflagsfalse. Do not confusestartupAPIwaitwithfailure.
Final:application1f37342,verificatione9ff6d2,pushedmain;runningPIDs3167124/3167125.
Postrotationrestartpreserved32014/8239newrecordsplusall1002333legacyrecords.
Allclosedsegment/raw/gzip/manifestandcatalogproofspass;both500cash/PnL0,
0orders/fills/positions,stoplatched,certifiedvalidationblocked,liveflagsfalse.
At15:59:25UTCcollector4758287025bytes/68719476736budget,experimental1244884083/
17179869184budget;rootfree516593922048bytes. Netsoakgrowth120435.71/47927.42B/s,
roughly6/4dayremaininghorizon. Monitoringfastendpointfixverifiedbyrealsoak.
Nooriginalpurgepolicy. Nextaction:approvefutureverifiedretention/migrationbefore
finitebudgetfull;usemanagedstreamfornewresearch;preservetradingapprovalgates.
