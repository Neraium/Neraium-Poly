# Phase 46 checkpoint

Worktree: `/home/ubuntu/.local/share/neraium-citadel/worktrees/3e041d43987e0512/phase46-outcomes`; branch `citadel/phase46-outcomes`; starting HEAD6657de1.

Implemented outcome-blind higher-information source selection; frozen prospective market/trivial/causal-frequency comparisons with conservative date blocks; exact native byte admission within unchanged64MiB guard; cached-proof replay pruning; held-token fee refresh; explicit dashboard evidence counts. No scientific thresholds or risk limits changed.

Evidence: phase46 baseline; public FOMC fee curve .05 exponent1 (current, not historical); authentic13:32UTC bid exit hypothesis -$0.21, no exit/order. Original18.90shares/$0.72 unchanged. Tests109passing + four repaired boundary regressions passing; final new tests and CI pending.

No live changes yet. Experimental202da2f PID542117; reference Phase38 PID555731/NRestarts2 (pre-existing automatic restart since Phase45). Reference must not be restarted. Experimental stop latched. Native archive62.15MiB,1.846MiB headroom; exact admission fix does not raise cap or delete evidence.

Next: finish bounded controller rehearsal (fresh reference intermittent); commit source and run CI. Refresh exact source/account/journal/storage gates, verify source-only rollback202da2f with shadow research quiesced; deploy experimental only after CI. Capture bounded live comparison and close with exact results.

## Activation checkpoint
Source c81d5b1d3ae449ccd362a2383f02abc7eaa2328c pushed; CI44096984056 successful (2422 backend cases, dashboard/build/audits). Source-only rollback202da2f reconstructed and hash-verified, shadow research disabled on rollback; no financial restore. All immediate gates passed: journal integrity, DB checks, paper-only, kill1, unchanged accounts/resources,176GiB free. Experimental-only restart13:58:15UTC, PID577442. Reference555731 preserved. Recovery and bounded post-ready observation running. Pre-change window319s/63samples,6fresh. No profitability claim. Next: evaluate startup/observation; postflight; compact closing evidence and push.

Live validation found a transient pre-existing source inventory accounting mismatch: raw compact originals fit16MiB while controller expanded JSON exceeded it, withholding research after recovery. Reproduced deterministically with compact UTF8 records. Fixed exact expanded accounting including brackets/separators; excess records deferred with originals unchanged. Two focused source-boundary tests pass. New CI/source repair deployment required; original live safety unchanged. First candidate subsequently collected4prospective trials but remains susceptible without this repair.
