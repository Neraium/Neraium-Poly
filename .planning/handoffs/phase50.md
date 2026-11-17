# Phase 50 cold recovery measured and rollout withheld

Base `96763b1a86278983d85a0604528ca6af64cea236` on isolated branch `citadel/phase50-recovery`, worktree `/home/ubuntu/.local/share/neraium-citadel/worktrees/3e041d43987e0512/phase50-recovery`. Candidate `8d9756ff8a514ad87947646ffc330f0c3e10efc8`, CI 44187256997 green with 2,449 backend tests, Ruff, and dashboard checks. Focused recovery, cold storage and research tests passed 52. No live service restart, migration, or activation occurred.

## Recovery evidence

A/B are `8d8c115` and `f7903e1`. C is the Phase 50 candidate. Each archive run started with an independently copied inode set from the same 512-segment, 2,966,662,718-byte verified warm-layout sample. A/B ordering was A1, B1, B2, A2. fsync followed by per-file DONTNEED on the copies preceded the timer, with no host-wide cache eviction. Physical read counters show the starts were not fully cache-resident. An observed cgroup limited each worker to one CPU and 2 GiB with swap off. Host disk and metadata cache conditions still varied.

| Source | Archive-ready runs | Isolated first HTTP runs |
|---|---:|---:|
| Phase 48 A1/A2 | 40.71 / 42.50 s | 69.41 / 45.94 s |
| Phase 49 B1/B2 | 41.47 / 40.40 s | 44.98 / 61.24 s |
| Phase 50 C1/C2 | 41.95 / 49.48 s | 66.47 / 42.61 s |

A/B agree within observed run variation. A 128-segment comparison took 15.93 s on A and 9.63 s on C, versus roughly 40–49 s for 512. The sample supports recovery work growing with archive size and varying with physical I/O. It does not establish a Phase 49 source regression. Phase 49 spent its failed 900-second window in the same archive indexing and verification path.

The archive profiler found 1,536 standalone hash passes over the 512 segments, about 14 s inclusive. The repair hashes sealed raw bytes once and verifies the same device, inode, length, mtime and ctime across record replay. Compressed and decoded hashes are computed together from one input descriptor with decoded length checked. Per-record hashes, SQLite integrity, catalog identity and archive budgets remain enforced. No checkpoint introduced. Regressions catch a compressed-header mutation with the same decoded bytes and a raw mutation during replay with mtime restored. All six archive results recovered the same catalog fingerprints. Standalone hash calls fell from 1,536 to 512 and logical reads from 9.77 to 6.80 GB. Physical reads remained in the 3.06–3.48 GB range, and the candidate's indexing stage varied from 6.26 to 17.46 s. This did not provide repeatable wall-time headroom.

The first reduced HTTP fixture correctly withheld startup because the quote checkpoint referenced canonical quotes outside the sample. The revised fixture imports the exact archived dependency bytes into a private segment, including the 14 frozen trials. The six reported runs used the production runtime and HTTP health route without ingestion workers. Both account copies matched before and after each run, and all 14 trial payloads and hashes matched after recovery. HTTP reachability is distinct from full-size operational readiness. The pre-existing child qualification policy mismatch remains withheld in the logs. Live read-only checks separately verified both account states, journal chains, 1,098 original native files, 15 original proofs and Phase 48 backup hash. No whole-archive comparison or validated cold margin under 900 s was established. Before scratch allocation, the 100 GiB reserve left 59.79 GiB available and the live archive occupied about 74.8 GiB. Per-run copies were regenerated as needed and removed after measurements. Input fixtures remain local.

## Ledger disposition and freshness

The 64 MiB guards count database, WAL, SHM and the next serialized payload. The legacy ledger totals 67,198,600 bytes and the domain ledger 70,288,832 bytes. The DB files alone remain below the caps. The WAL allocations account for the current excess. The admission calculation does not predict exact SQLite page/index growth at the final historical append. The 11 recorded rejections came from the legacy evidence append path, which first tries order-book evidence for the market-baseline record. Rejected IDs, payload bytes and exact prospective forecasts were not retained and cannot be reconstructed exactly from the logs. No rejected append restoration attempted.

On private byte-verified copies, SQLite WAL truncation preserved every committed record and chain head, giving 4,059,136 and 1,286,144 bytes of initial headroom. Both stores recovered from a killed uncommitted write, accepted one controlled retry, and rejected its duplicate after reopen. This is temporary headroom and the WAL can grow again. No live checkpoint or rewrite was applied.

Phase 49 route regressions verified repeat polls preserve the frame trace without a new read, each poll reevaluates staleness and producer health, and the desk projection skips decoding the unchanged batch. A read-only producer probe identified an actual WebSocket invalidation boundary: generation 487 had 488 exported books, the transport closed with ConnectionClosedError and generation 488 published zero books with 806 gap-withheld tokens, and generation 489 backfilled. Eight earlier reads timed out without any producer frame to attach to them. Their server-side cause remains unresolved. No reference modifications.

The restored experimental source is `8d8c115d20fc86604cffc4af64657f967b499b63`, PID 660816. Reference PID 555731 at `1342482fd9431f4e2e69d8788d864cb32fd1d4e9` remains untouched. Paper-only flags, the experimental stop, and resource limits verified. Shadow research remains quiesced and the live endpoint explicitly withholds reports. The three earlier windows were 26/60, 32/59 and 28/59. No new live windows were possible. Before collecting them, establish full-size repeatable cold readiness under the existing gate and obtain the separate decision to resume experimental shadow research.

The exact measurements, sample manifest, copy fingerprints, test source, CI record and safety checks are in `.planning/evidence/phase50/`. The closing revision is the commit containing this handoff.
