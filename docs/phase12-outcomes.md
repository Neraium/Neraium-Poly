# Prospective outcome collection and verification

`acquire_verified_outcome(forecast, market, output_new_dir, client=..., rpc_client=...,
clock=...)` asynchronously attempts one public resolution acquisition. Pass the
original forecast-time `MarketSnapshot`, not later metadata: its receipt must
precede the forecast evidence cutoff and its exact resolution-rule digest must
match. The coordinator controls scheduling/cadence and calls only pending events
after their scheduled close. Scheduled close is a search trigger, never proof.

The native `OperationalPolymarketAdapter.settlement` algorithm still requires
resolved, undisputed, identity-matched binary status and final resolution records.
Three bounded public GETs are archived as exact bytes with request/receipt/hash
bindings. Unsupported protocol variants, negative-risk markets, missing rules,
changed token mappings or disputed/unfinished payouts return no outcome.

The reported transaction supplies only a block locator. A separate read-only
Polygon client scans that block plus/minus one for exact CTF ConditionResolution,
checks receipt inclusion, canonical block and finalized height, then replays all
raw proofs via `_load_proofs`. A preparation transaction is never treated as a
resolution, and no later-window guess substitutes for missing evidence. Payout
orientation must match the original Gamma token array and native payout. A forward-only single-condition
RPC guard rejects multiple/ambiguous logs before generating a proof report.
Transaction/condition hashes and block/log quantities have fixed bounds, so
derived proof metadata cannot expand beyond the reserved byte budget.

Only a forecast preceding both the native resolution time and exact chain block
time may be matched. Evidence availability is the latest actual acquisition time;
settlement time is the authoritative block time. The resulting
`VerifiedEventOutcome` hashes the entire verification dictionary, binding exact
forecast/market content, native source archive, chain proof and evidence directory.
It grants no operational account settlement or strategy certification authority.

`verify_collected_outcome(outcome, market, forecast, rootdirectory)` is a synchronous
offline proof callback. Async coordinators must call it using `asyncio.to_thread`.
It confines evidence to the supplied root, checks hashes, replays the same native
settlement algorithm against archived HTTP responses and independently replays
all raw RPC finality/inclusion proofs. It does not trust declared verified flags.
Tampered records, archives, forecast identity, rule/token mismatch or after-outcome
forecasts fail closed. Calling it directly inside a running event loop declines
rather than nesting event loops.

Per attempt: at most three native GETs, at most 15 strictly whitelisted RPC reads,
2 MiB native raw bytes, 5 MiB RPC raw bytes and bounded metadata within an 8 MiB
attempt reservation. Total proof root is capped at 32 MiB with an 8 GiB free-disk
floor. Existing attempts are never overwritten. Failed attempts remain evidence;
no archive cleanup is automatic. RPC reads run in a thread to preserve collector
responsiveness. There is no order method, funded wallet or transaction submission.

Controlled tests exercise genuine native+chain proof shape, both token orientations,
preparation/dispute/payout/variant rejection, original predecision rule binding,
forecast-before-resolution checks, raw tampering, new-directory guard and proof
root confinement. These tests create no operational resolutions or performance.
No real network acquisition was performed for this adapter during development;
actual automatic acquisitions occur only when eligible pending events later close.
