# Phase 49 experimental freshness and verified rollback

The worktree is `/home/ubuntu/.local/share/neraium-citadel/worktrees/3e041d43987e0512/phase49-freshness` on `citadel/phase49-freshness`. It began at `17fd09264bb86bbde71aeca3417ee485f465d409`. The candidate `f7903e13f4c30bdf644d86d0d301fd4834041caf` passed CI 44176463839 with 2,447 backend tests and the dashboard checks.

The candidate ran only in startup as experimental PID 640711. It remained in archive recovery and missed the 900-second readiness gate. All 181 startup polls returned connection errors. No post-readiness windows were available. The source-only rollback restored `8d8c115d20fc86604cffc4af64657f967b499b63`, PID 660816, with shadow research quiesced using the established rollback configuration. The paper API and reference feed passed recovery verification. The reference remained PID 555731. Neither startup incurred an OOM kill or automatic restart. The stop and paper-only mode remained in force. Both accounts, financial journals, limits, 14 frozen trial hashes, 1,098 original files, 15 native proofs, and the Phase 48 native backup verified.

| Baseline window | Fresh polls | Journal-matched processing frames | Cycle p50 / p95 |
| --- | --- | --- | --- |
| 1 | 26/60 | 17 | 11.48 / 21.04 s |
| 2 | 32/59 | 16 | 12.21 / 23.17 s |
| 3 | 28/59 | 17 | 10.95 / 23.30 s |

There were 128 repeat report polls. Across all windows, 34 polls had an observed reference-timeout veto, 28 had a degraded-producer veto, and 30 expired with an unlocated boundary. One baseline publication necessarily exceeded the 20-second dashboard limit after frame selection, based on the measured stage durations. The older samples give exact derived processing IDs via the matching StrategyCycle records. Original producer frame IDs and source age at publication were unavailable on the baseline. The candidate adds those facts as bounded traces, preserves original source ages in freshness assessment, reuses one serialization across the shared decision stages, and avoids reprojecting unchanged archived decision batches. The route regression exercises withholding and recovery.

Outside the comparative windows, the direct reference probe independently observed five three-second timeouts and two explicitly degraded frames with zero exported books despite recent ingestion and no producer error. It confirms the producer withheld usable books. The stage that cleared the book set and the server-side timeout cause remain unproven. No reference deployment was attempted.

The legacy forecast ledger stayed at 67,198,600 bytes, 89,736 over its 64 MiB cap. The domain store stayed at 70,288,832 bytes, 3,179,968 over its separate cap. Both stored-head and byte measurements were unchanged across the baseline and rollback. Logs report 11 legacy evidence-append rejections during the baseline. The append sequence starts with order-book evidence and logs omit the individual rejected IDs. These exceptions are caught locally and the shadow controller continued publishing from the managed event archive. A storage rewrite was unnecessary for this diagnosis.

Closing evidence lives under `.planning/evidence/phase49/`. It includes the prespecified criteria, all three complete baseline windows, original Phase 48 frame joins, per-poll traces, the candidate incident, source and journal gates, rollback observation and verification, checksummed raw sample copies, and the producer probe. Raw uncompressed evidence and source bundles remain local. Cold recovery is the exact activation blocker. End-to-end freshness improvement remains unverified.
