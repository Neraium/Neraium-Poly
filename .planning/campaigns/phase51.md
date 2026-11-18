# Phase 51 isolated full-archive readiness

Worktree phase51-full-recovery and branch citadel/phase51-full-recovery start at c67d7f9699ac0783f791a9e95b69ec9373147105. Compare Phase 48 source 8d8c115d20fc86604cffc4af64657f967b499b63 and Phase 50 source 8d9756ff8a514ad87947646ffc330f0c3e10efc8. Keep both live services unchanged with experimental shadow research quiesced and stop latched.

Exit conditions are verified full archive, four sequential runs in order A1 B1 B2 A2, actual paper readiness measured against 900 seconds, state checks, physical I/O and cache conditions, closing evidence committed and pushed. Preserve all original proof, journal and backup bytes. No activation or paid volume.

The private full snapshot is recorded in evidence/phase51/snapshot.json. Its root is in scratch-path.local. Source files referenced by the frozen catalog are read-only sealed inodes, with private mutable database copies and an exact active record prefix. Each run uses its own writable overlay and mount/PID namespace. Synthetic no-write-through probe passed. The active unit sequence phase51-full-a1, b1, b2, a2 is launched by the tracked-named source code and wrapper. The driver captures progress, first HTTP, phase times and gate result after each unit. Resource watcher retains samples and stops an isolated unit if free space drops below 108 GiB or its upper layer exceeds 12 GiB. Live services are outside every test namespace and remain intact.

Current checkpoint at 00:55 UTC. A1 started. Baseline has two accounts, 14 trial hashes and 22 native proofs. Cache sampling is nondestructive. If resuming, read unit state and per-run output paths before starting any process.

Pilot result and correction. Initial A1 reached normal paper readiness at 931.40 s, but its alternate path triggered the existing projection identity veto, so it is excluded from the comparison. Canonical data is now overlaid at /home/ubuntu/Neraium-Poly/data only inside the test namespace, with the checkout read-only and seed masked. Independent mount attestation is retained. The corrected run-sequence.sh is active in order a1r, b1r, b2r, a2r; cache and I/O are logged without eviction. As of 01:20 UTC a1r had validated 7,500 segments. No live restart or deployment.

Checkpoint 01:33 UTC. Canonical A1 has completed with full state equivalence and a 973.45 s paper gate (73.45 s late). Archive construction was 951.42 s and 861 filesystem size scans took 263.70 s inclusive. B1 is in progress with 4,500 segments replayed. Continue B1, B2, A2 without changing benchmark conditions, then run the live preservation attestation and commit the comparison.

Checkpoint 01:43 UTC. B1 passed at 837.36 s, 62.64 s inside the gate. Standalone SHA bytes fell from 125.40 GB on A1 to 50.77 GB on B1. Stage and account attestation data are exported. B2 is active, followed by A2. Actual experimental remains on 8d8c115 with the stop latched and shadow disabled.

Checkpoint 01:57 UTC. B2 passed at 804.48 s with 95.52 s headroom. Both candidate startups matched the verified frozen state. A2 is active as the final reversed-order comparison. The deployment remains outside the scope of this phase.

Closed at 02:13 UTC. ABBA gates 973.45, 837.36, 804.48 and 881.91 s. Candidate passed twice, slowest margin 62.64 s. State and append-only prefix attestation passed on all runs. Live state unchanged, scratch removed, 100 GiB reserve maintained. Evidence is under .planning/evidence/phase51 and handoff under .planning/handoffs/phase51.md. Next decision is whether to authorize experimental rollout and the three live freshness windows.
