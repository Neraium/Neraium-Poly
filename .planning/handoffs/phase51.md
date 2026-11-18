# Phase 51 full-archive paper recovery

Base c67d7f9699ac0783f791a9e95b69ec9373147105 on citadel/phase51-full-recovery. Source A is the running Phase 48 revision 8d8c115d20fc86604cffc4af64657f967b499b63. Source B is Phase 50 candidate 8d9756ff8a514ad87947646ffc330f0c3e10efc8, CI 44187256997. This phase is an isolated recovery benchmark.

## Fixture and conditions

The local ext4 volume had 164,701,884,416 free bytes before scratch setup. That left 57,327,702,016 bytes above the 100 GiB reserve, less than the full archive. Same-volume reflinks returned EOPNOTSUPP. The native proof backup is not a full recovery image. The consistent snapshot uses zero extra infrastructure and contains 12,766 segments, of which 12,764 are sealed, with 3,927,996 cataloged records. The catalog and state databases use private SQLite backups. The active segment retains exactly the catalog's record prefix. Its record hashes and metadata were checked against that catalog. Sealed raw and gzip files use isolated, read-only references to immutable originals. Legacy, proof, and mutable files are independent copies. The manifest identifies the frozen inputs.

The namespace exposes the overlay at the production canonical data path and the source checkout is read-only. A probe verified EROFS on the underlying source and an independent copy-up inode when writing to the overlay. Each run has its own PID/mount namespace, writable overlay upper, loopback port, and one CPU, 2 GiB, and 32-task cgroup. The per-run safety monitor bounds upper growth at 12 GiB and interrupts an isolated run below 108 GiB free. The application independently enforces the existing 100 GiB reserve.

Order A1 B1 B2 A2 gives one comparison in each direction. Every run starts a new process with the same frozen state. The backing page cache is shared, sampled before each launch using mincore, and never evicted intentionally. These are cold process starts with mixed page residency. Readiness is the real quiesced paper gate using an isolated copy of the experimental account and the live reference HTTP feed. The clock starts just before the isolated process executes. First HTTP includes pre-bind state attestation, whose duration is tracked separately. Stage timers are inclusive. The diagnostic deadline is 1,180 seconds so a missed 900-second gate can still be measured.

The pilot at a different data path hit the path-bound research projection veto. Its 931.40-second result is retained as diagnostic evidence and excluded from the comparison. The benchmark uses the original canonical path through a private overlay outside the production service namespaces.

The reference feed is live and its timing varies between launches. Host I/O pressure and physical reads are recorded for that reason. Isolated overlay metadata costs can differ from those of the live ext4 directory. Mixed cache residency prevents claiming a fully uncached storage worst case. These runs establish recovery readiness under the measured conditions only. They do not measure live freshness after rollout.

## Results

| Run | Source | Cache resident | Archive init, s | First HTTP, s | Paper readiness, s | Margin, s | Physical read to init, GB |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| A1 | 8d8c115 | 65.46% | 951.42 | 963.98 | 973.45 | -73.45 | 30.36 |
| B1 | 8d9756f | 63.80% | 815.74 | 827.88 | 837.36 | +62.64 | 27.24 |
| B2 | 8d9756f | 65.06% | 785.02 | 797.66 | 804.48 | +95.52 | 26.67 |
| A2 | 8d8c115 | 65.85% | 858.89 | 870.83 | 881.91 | +18.09 | 26.70 |

The candidate passed 2/2. Its slowest was 837.36 s with 62.64 s margin. A1 missed and A2 passed. Every run verified 12,766 segments and 12,764 compressed copies. Standalone hash passes read 125.40 GB on A and 50.77 GB on B. Reusing the sealed hash across replay and hashing gzip bytes during authenticated decompression reduced redundant reads. Recovery stayed dominated by archive verification and catalog replay. Exact capacity accounting did 728–861 archive tree walks taking 212.68–263.70 s inclusive. Physical reads varied with I/O pressure and cache. Per-run limits held with no OOM kills, with charged memory peaking at the 2 GiB cgroup cap. The largest sampled writable upper was 2.40 GiB. Disk free space stayed at or above 130.87 GiB. Cleanup released 19.35 GiB from generated scratch and source exports.

Both accounts, the latched experimental stop, three forecast journal heads, 14 frozen trials, 22 independently replayed native proofs, 1,098 original file identities, and the backup hash matched at recovery. The quiesced runtime verifies the underlying market-data path and still runs ordinary forecasts. Every post-readiness isolated journal preserved the full frozen prefix and appended only verified records. Both financial accounts stayed equal through shutdown. Live attestation found the original three journal heads, proofs, backup and account state unchanged. Live paper PID 555731 and experimental PID 660816 were unchanged. The experimental source remains 8d8c115 with shadow research quiesced.

The result supports a separate experimental rollout decision. Recheck the disk reserve and live archive size, preserve the source-only rollback, and reapply the 900-second gate. Resuming shadow research and collecting three live freshness windows requires the separate decision identified in the Phase 50 handoff. Phase 51 establishes recovery readiness and has no live freshness observations.
