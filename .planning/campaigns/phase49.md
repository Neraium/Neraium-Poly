# Phase 49 freshness campaign

Base 17fd09264bb86bbde71aeca3417ee485f465d409. Branch citadel/phase49-freshness. Isolated Citadel worktree phase49-freshness. Candidate f7903e13f4c30bdf644d86d0d301fd4834041caf, exact CI 44176463839 successful.

Exit conditions
- Three consecutive five-minute windows on Phase 48 source and three on the candidate after readiness.
- Frame trace with producer timestamps, timeout and degradation evidence, explicit report publication time, and all poll outcomes.
- Verify paper accounts, emergency stop, sequence journals, original manifest, native backup, frozen trials, reference identity, and rollback.
- Push final artifact and handoff with the measured result. No deployment outside experimental.

Baseline is collecting. Activation helper waits for complete baseline, checks current health, source, accounts, journal and evidence, restarts experimental only, and starts the bounded readiness and observation. Phase 48 archive migration is complete and is not repeated.

Final checkpoint. Candidate f7903e1 passed CI 44176463839. All baseline windows retained. Its experimental startup exceeded the existing 900-second gate while scanning archive segments, with 181 connection-error polls and no post-readiness windows. Verified source-only rollback to 8d8c115 PID 660816 with shadow research quiesced. Reference PID 555731 and both account states preserved. Closing outcome and exact next blocker are in handoff phase49.md and evidence/phase49/closing.json.
