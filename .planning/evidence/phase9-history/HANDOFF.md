# Phase9 historical qualification handoff

Branch citadel/poly-phase9-history; isolated worktree
/home/ubuntu/.local/share/neraium-citadel/worktrees/3e041d43987e0512/poly-phase9-history.
Baseline ac4407f. Scope: qualification.py, settlement_evidence.py,
test_phase9_qualification.py and phase9-historical-qualification.md only.

20 focused /329 full backend tests passed; one existing Starlette warning.
One pytest coordinator per run; final full coordinator PID in full-tests.txt.
Actual historic qualification uses TWO CPU workers (2953139/2953142), overlap
recorded; coordinator2953118/manager2953134/resource_tracker2953133 =5jobprocesses.
Numerical threads1 per worker. No claim of performance speedup or independent
statistical events from repeated runs.

Actual data (excluded from Git): data/phase9qualification/chain, qualified-v2.
Root should copy chain and qualified-v2 together to same relative project paths;
original source bundle remains /home/ubuntu/Neraium-Poly/data/phase8-history-events.
47 exact finalized CTF resolution proofs matched to original selected outcomes.
95 archived read-only RPC calls,1,296,482bytes. Rawresponseproofs replay verified.
4 remainingAPIlabels not corroborated within budget.250metadata groups /51API
verifiedlabels;0PIT/depth/independence/train/heldoutqualified. No promotions.

qualify_history(source_dir, output_dir, rpc_evidence_dir=None, workers=2) writes
versioned rows/manifest/report and refuses output reuse/source mutation.
ReadOnlySettlementClient(new_directory,max_requests<=100) acquires only explicit
read methods from PolygonpublicRPC. Calling acquire(condition_ids,start,end)
requires explicit bounded knowncondition IDs /blockrange. No transactionmethods.

No sharedcontracts, certifiedvalidation, operationalledgers, services, CLI or CI
changed. No fundedwallet/keys/liveorder. Next: rootreview/cherry-pick,copylocaldata,
expose report in runtime/monitor as independent certification progress. Exact
commit ID will be sent to root after commit; no further historicalnetwork calls.
