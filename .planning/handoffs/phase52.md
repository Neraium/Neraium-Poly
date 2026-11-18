# Phase 52 guarded experimental paper rollout

Evidence base d800ae8454f439477ca922b3414c490a0c9bc320. Candidate 8d9756ff8a514ad87947646ffc330f0c3e10efc8 passed exact-source CI 44187256997. Source-only rollback is 8d8c115d20fc86604cffc4af64657f967b499b63 with shadow disabled. Both release inventories had 295 files and matched their verified sources. Preflight had 149.96 GiB free against the 100 GiB minimum, verified both accounts, three journal heads, the native backup and 1,098 original proof file identities, 14 frozen trials, and 22 native proofs.

## Startup and guard

The source rollout restarted only the experimental unit with shadow research quiesced. Paper readiness passed in 742.61 s with 157.39 s margin. The authorized enable restart passed in 869.12 s with 30.88 s margin. Experimental PIDs were 774729 and 778910. Reference PID 555731 stayed in service.

The initial enabled guard checked public_feed, which stays not_observed when ingestion uses the shared ReferenceSampler. The observation guard was replaced at 838.10 s with the mode-appropriate shared sampler check. The process PID, source, startup anchor, and deadline stayed the same. The timestamp reconstruction from the original poll was conservative by 0.02 s. The first HTTP poll was at 711.62 s. The first-HTTP field in shadow-ready.json is scoped to the replacement guard. Shared reference ReadTimeout and producer health failures delayed readiness. The actual gate required both APIs healthy, a fresh sampler, an available shadow report, intact state, and paper-only flags.

## Freshness

Three consecutive five-minute windows began after the enabled readiness and evidence checks. The observer used the Phase 49 five-second cadence, existing API verdict, and baseline summarizer. It retained stale rows and used one cycle duration per distinct report. Archive lookup rejoined journaled processing frame IDs, and admitted decision receipts exposed additional derived frame IDs.

| Window | Phase 49 fresh | Phase 52 fresh | Journal-verified frames, before/after | Phase 52 receipt frame IDs | Cycle p50/p95 before | Cycle p50/p95 after |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 26/60 | 24/60 | 17/17 | 22 | 11.48 / 21.04 s | 5.80 / 22.19 s |
| 2 | 32/59 | 20/58 | 16/15 | 22 | 12.21 / 23.17 s | 5.80 / 19.15 s |
| 3 | 28/59 | 26/59 | 17/17 | 25 | 10.95 / 23.30 s | 10.83 / 27.20 s |

The candidate reported 70/177 fresh versus 86/178 for the baseline. The older age rule applied to the same Phase 52 polls gives 24/60, 20/58, and 31/59. Repeated reports accounted for 42 polls in each window. Read-timeout stale polls were 17/22/15, explicit producer-degraded stale polls were 12/12/3, and expiry observed after publication was 7/4/15. There were zero observed expiries before publication and zero dashboard HTTP failures. Counts are sampled poll classifications. Repeated polls may reflect the same failure, and unobserved attempts are outside these counts.

## Final serving state

The final configuration restart passed at 03:19:56 UTC in 775.77 s with 124.23 s margin. Its external watcher exited with status 143 between polls. The replacement resumed the original 900-second deadline from the durable timestamp pair while PID 788797 continued recovering. No extra service restart occurred. All three gates passed and no rollback was needed.

Candidate 8d9756ff8a514ad87947646ffc330f0c3e10efc8 is serving on experimental PID 788797. The configuration and live environment are paper-only, live execution is disabled, and the shadow endpoint is withheld with no trading authority. Both health checks were OK at final attestation. Reference PID 555731 had unchanged restart count. Reference paper cash was $500.00 and experimental paper cash was $496.11522059829053, each unchanged. Both accounts had zero open positions and unreleased reservations. Order and fill histories were unchanged. The experimental emergency stop stayed latched.

All three original journal heads matched exactly. The 14 frozen trials, 1,098 original proof file identities, the backup hash, and all 22 preflight native proofs were preserved. Final verification independently replayed 25 native proofs, including three additional proofs written during the authorized observation. Available disk was 148.95 GiB. Final cgroup had no OOM kills. Freshness was lower than Phase 49 in each window under the endpoint verdict, with observed upstream timeouts and degraded producer responses dominating stale polls.
