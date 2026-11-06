# Phase14 storage audit and bounded cache cleanup

The read-only audit found no approved secondary persistent destination. The
instance has one500GiB NVMe root EBS device and its boot partitions. AWS
DescribeInstances, performed by the coordinator, identifies instance
`i-0f7f235764cdca32b`, AZ`us-east-1f`, with only attached volume
`vol-03c2fd4e26ccd63d3` (`DeleteOnTermination=false`). DescribeVolumes was denied by
IAM, so this is not a claim that no unattached volume exists anywhere in the
account. No AWS resource or paid capacity was created or changed.

`/dev/shm` is RAM-backed tmpfs, not durable archive storage. It cannot establish an
approved historical-data destination. Valuable data migration/compression has not
been proposed as executable because destination approval/capacity and complete
source integrity have not been established. No original historical data was
deleted, moved or compressed.

## Measured allocation

Numbers below are observed allocated bytes from low-priority (`nice19`, idle-I/O)
read-only `du -x` scans; they are not a transactional filesystem snapshot. Files
and other workloads continued changing during the audit. Hardlinked content is
counted once within a traversal, so separate directory totals cannot be summed as
independent reclaimable capacity.

| Path/category | Allocated bytes | Treatment |
|---|---:|---|
| `/home` |337,544,208,384|Mostly repositories, worktrees, research and evidence; preserve|
| `/srv` |85,886,849,024|Neraium migration and issue142 certification trees; preserve|
| `/tmp` |64,329,121,792|Mostly ARI/Neraium certification fixtures; other projects/evidence, preserve|
| `/var` |21,373,837,312|Container layers/volumes, PostgreSQL, system metadata; preserve|
| `/usr` |4,806,737,920|Installed system software; preserve|
| Poly`data/paper-live` |2,031,734,784|Actual live collection archive; preserve|
| Poly`data/experimental-paper` |541,753,344|Account/journal/observations; preserve|
| Poly`data/live-20261106` |512,073,728|Archived market evidence; preserve|
| Poly`data/phase11` +`phase11-adaptive` |301,867,008|Historical research; preserve|

Largest individual files include an approximately6GB gzip frame archive under
Neraium-1.0, a5.63GB historical`dev-shm.tar`, multiple1.7–3GB archived research
JSON/database files, and Poly's approximately1.99GB live`events.sqlite`. Exact
paths and sizes are in`audit-summary.json`. These are not disposable caches.
Other projects contain large security-scanner databases, but their project and
certification provenance prevents treating them as authorized cleanup targets.

`/var/lib/containerd` consumes18,136,383,488bytes; Docker images/volumes belong to
existing services and were untouched. Docker's native builder audit reports
1.932GB nominal reclaimable cache, of which1.677GB is shared with retained image
content and only255.2MB is private. No Docker pruning was performed.

## Reference checks and exclusions

Process CWD/executable/command/mapped-file references, `lsof +D`, Git worktree
status, ignored-file checks and link counts were inspected. Only a661-byte deleted
open npm log was found; there is no large deleted-open-file recovery opportunity.
No process was stopped and no file descriptor was truncated or manipulated.

The3.71GB Playwright cache is pinned by registered clients: all13 installed
browser/cache revisions have references, so every revision was preserved. Most
uv cache files share hardlinks with installed packages;2.94GB displayed cache
size does not equal potential reclaimed space. The unshared-file ceiling was
259,756,032bytes, and uv objects were preserved. Inactive Poly virtual environments
share library inodes mapped by running Poly processes, or have dirty source
worktrees; none was removed. All repositories, branches and worktree directories
were retained. Main Poly dependencies needed by active services/tests were retained.

## Exact authorized cleanup

The user authorized only conclusively disposable, inactive, reproducible caches.
The coordinator explicitly reviewed these four paths before execution. Fresh
`lsof`, process-reference and source-status checks completed for all four before
any mutation; no open/mapped/CWD/command references existed. Npm cache metadata
contained789 public npm-registry and69 public security-advisory entries, with no
local/private artifact keys.

| Removed path | Allocated file bytes before removal | Regeneration |
|---|---:|---|
|`/home/ubuntu/.npm/_cacache`|286,916,608|`npm ci`, public registry cache repopulates|
|`/home/ubuntu/.cache/pip`|2,379,776|Pinned`pip download/install`|
|`/root/.cache/node-gyp`|67,747,840|`node-gyp install --target=<required Node version>`|
|`.../poly-dashboard/frontend/node_modules`|94,687,232|`npm ci` from committed lockfile in that inactive Poly worktree|

The last dependency directory had an83,255,296-byte unshared-file ceiling. Each
path's file inventory hash, entry count, byte counts, regeneration command,
reference checks and deletion timestamp are in`cleanup-manifest.json`. Nothing
outside these four exact paths was removed. No broad cache-clean/prune or recursive
repository cleanup command was used.

Actual observed free space rose from**3,860,529,152** to**4,313,407,488bytes**:
**452,878,336bytes (~432MiB)** net reclaimed. Other host activity consumed capacity
while the audit ran, so its initial approximately4.6GiB free observation was
already lower before cleanup. The result is approximately**4.02GiB free** and
**does not restore the8GiB floor or meet the20GiB target**. Neither threshold was
lowered or bypassed.

Both paper service PIDs and paper-only environment flags remained unchanged.
Account/positions/reservations/orders table hashes matched before and after;
both cash balances remained500, simulated P/L0, with no orders/positions. The two
NFL forecasts were preserved. Services remained active but budget-degraded, as
before cleanup; this is not a claim that market ingestion resumed.

## Remaining blockers

1. No further large, conclusively disposable allocation was found within the
   authorized scope. Reaching20GiB, or even8GiB, would require additional reviewed
   capacity or separately authorized valuable-data handling. Unrelated project
   evidence, certification fixtures and image rollback material were not sacrificed.
2. Experimental storage is independently above its configured512MiB archive cap.
   Filesystem recovery alone would not resume its order-admission archive path.
   The existing safe stop and account isolation remain in force.
3. The collector's approximately1.89GiB archive is also near its configured2GiB
   ceiling. A durable, bounded, lossless archive design must preserve original
   integrity and histories; no source deletion is authorized by this audit.
4. DescribeVolumes access was denied, so an account owner may identify an already
   approved, adequately sized durable destination. New AWS resources, EBS expansion
   or additional charges still require separate approval.

Phase14 development that does not depend on additional persistent capacity can
continue. Large downloads, storage-limit changes, historical relocation or
cleanup of protected project evidence have not been performed.
