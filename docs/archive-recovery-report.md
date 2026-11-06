# Post-expansion archive recovery report

Verified application `1f37342`; final verification commit `e9ff6d2`. Operating snapshot: **2026-11-06T15:59:25.117358+00:00**.

The live collector and experimental research service now use a lossless, bounded segmented archive. This restores collection without clearing the experimental emergency stop, granting strategy approval, or enabling real-money execution.

## Measured operating state

| Service | Total service usage | Budget | Segment target | Completed raw / gzip |
|---|---:|---:|---:|---:|
| Collector | 4,758,287,025 bytes (4.432 GiB) | 68,719,476,736 bytes (64 GiB) | 16 MiB | 15 / 15 |
| Experimental | 1,244,884,083 bytes (1.159 GiB) | 17,179,869,184 bytes (16 GiB) | 8 MiB | 16 / 16 |

The root filesystem has **516,593,922,048 bytes (481.12 GiB) free**. The operational free-space threshold is64GiB, including the unchanged8GiB global floor. Budgets are ceilings, not preallocated space. Both service trees count originals, consistent backups, catalogs, active/closed segments, gzip copies, account databases and forecast journals.

Both services are healthy. WebSocket connected; **292 fresh books**,400subscribed outcome tokens,200monitored markets. Full exact source timestamps, market/token IDs and executable bid/ask/depth samples are preserved in `final-state.json`. These are actual public observations, not fixture or replay output.

## Sustained live acceptance

Final observation window: **2026-11-06T15:36:47.696788+00:00 to 2026-11-06T15:51:49.044817+00:00**,901.348seconds. All44post-readiness samples were healthy, with248–316fresh books. Two initial connection-refused samples occurred during deliberate startup and are preserved outside the accepted window. The sampler used the lightweight archive endpoint and actual public market frame.

The window completed **33 collector cycles** and **141 experimental cycles**. Each service sealed **six additional real segments**. Collector added29,358immutable event records and experimental added8,602. All recorded counts were monotonic and every measured service usage stayed below its budget. At window end one newly sealed collector segment awaited compression; subsequent verification/snapshot shows that queue drained.

| Service | Measured net growth over window | Approximate remaining time at that rate |
|---|---:|---:|
| Collector | 120435.71 bytes/s (117.61 KiB/s) | 6.15 days |
| Experimental | 47927.42 bytes/s (46.80 KiB/s) | 3.85 days |

Rates include retained raw files, compressed copies, catalog/WAL activity and other service state. They are observations, not guarantees. With the retain-originals policy, gzip does not reclaim local raw-file space. Finite storage eventually reaches a budget or global threshold; then collection fails closed. Longer operation needs an explicitly approved retention/migration policy. No automatic purge or original deletion is implemented.

## Historical integrity and restart recovery

Original collector and experimental archives contain **838,222** and **164,111**records respectively. Before adoption, consistent SQLite backups were created within each service budget, verified against the original ordered record-identity digests, and retained. Shutdown left committed WAL data, so SQLite performed a FULL checkpoint; identical record identities were verified before and after. No WAL file was manually removed. Both original database files stayed at their existing paths and are opened read-only as legacy sources.

New records go to uniquely named permanent SQLite segments. Segment commit precedes catalog commit; recovery rescans active/orphan tails and enforces global ID/digest consistency. Closed segments receive fsynced immutable manifests and verified gzip copies. Every decompressed copy must reproduce the original raw-file SHA256 and length. Only regenerable publication temporaries may be cleaned; event rows, original archives and completed evidence are never purged.

A production restart after real rotation preserved **32,014**new collector records and **8,239**new experimental records captured before shutdown, in addition to all legacy history. The read-only integrity run verified catalog consistency, unchanged original/backup file hashes, per-record payload digests, sealed manifests and gzip roundtrips. Exact verified segment sets and timestamps are in `production-integrity.json`; later rotations remain covered by the same live seal protocol.

Both paper accounts remain **$500**, with **$0 simulated P/L**, zero orders/fills/positions. Account/positions/reservations/order table hashes match the pre-cutover baseline. The original forecast-journal prefix and the two NFL prospective forecasts remain intact; all three forecast journals pass chained-hash verification. The baseline journal has204records; new legitimate records were appended rather than replacing existing history.

The experimental emergency stop remains **latched**. Certified strategy status remains **validation_blocked**. Both process environments retain `PAPER_TRADING=true` and `LIVE_TRADING_ENABLED=false`. No model or strategy was promoted. No AWS resource, IAM identity, volume size, unrelated service or repository was modified by this task. All previously running service units remain running.

## Implementation, tests and resource evidence

The former2GiB/512MiB caps were configurable budgets enforced as hard stops without a retention lifecycle. They were originally selected for the smaller-root research deployment: collector cap introduced by53c0371, changed to2GiB with200market streaming in0d1ac6b; experimental512MiB introduced in d3b0c70. They were operational storage bounds, not strategy qualification requirements. Managed production mode now uses separate64GiB/16GiB budgets; legacy standalone mode retains its old behavior.

All operational event consumers now use all-history get/latest/count/replay rather than querying only the active segment. Quote references and fee/relationship definitions resolve across legacy and closed segments. `iter_replay` supports streaming; old raw-SQL Phase10/11 extractors and public archive viewers still read only the selected SQLite file and must explicitly use the managed stream for new segmented history. Full-list replay is for small cohorts, not loading64GiB into RAM.

The archive monitor uses `/api/archive-state` so historical list retrieval does not block current storage/capital health. The expensive full-state API remains available separately. Startup deliberately revalidates historical sources and may keep the API unavailable while indexing; first collector migration took several minutes. No repeated restart was used to bypass that validation. A64MiB soft catalog cache remains within existing1CPU/1GiB collector and0.5CPU/768MiB experimental unit limits.

**834backend tests passed**, including contract/integration/replay, account isolation, quote references, immutability, disk floor/budget exhaustion, corrupt original/copy/index detection, interrupted seal/publication, constructor cleanup, narrow terminal layouts and a real controlled child-process exit between segment/catalog commits. The hard-crash fixture recovered exactly one event and rejected duplicate insertion. Fixture results are not genuine market observations.

**Five browser tests, dashboard build, Ruff, deterministic controlled scenario, runtime dependency audit and npm audit passed.** No known vulnerabilities were reported. [Final GitHub Actions](https://github.com/Neraium/Neraium-Poly/actions/runs/42246335101) passed backend and dashboard jobs on`e9ff6d2`. Its application/config/frontend trees are identical to the running`1f37342` application; the difference adds the hard-crash regression.

Actual concurrency: three writing agents in separate native Citadel worktrees plus the coordinator; two migration worker processes overlapped; two pytest processes overlapped, with one numerical thread each and bounded nested research-test workers. A single browser worker ran five tests. Compression is one bounded segment per maintenance call in each service. No32agent or32CPU utilization claim is made.

## Remaining limitations and next actions

1. Approve a retention/migration policy before the finite64GiB/16GiB budgets fill. Originals are retained and the current measured horizon is roughly6/4days; neither compression success nor exhaustion authorizes deletion.
2. Keep startup validation cost visible; larger retained histories increase restart verification time. Future optimization should preserve original-byte and record-digest guarantees.
3. Use the managed streaming interface for new research exports. Legacy single-file SQL consumers do not automatically merge later segments.
4. Independent forecasting/calibration and certified approval requirements remain unchanged. Archive health is not evidence of profitable strategies.

Evidence directory: `.planning/evidence/archive-recovery/`. Raw operational data, consistent database backups and full helper snapshots remain under ignored `data/`; no database or credential file is committed.
