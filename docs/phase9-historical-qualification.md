# Phase9 historical evidence qualification

Phase9 separates an official API outcome label from independently linked on-chain
resolution timing. It does not approve a strategy or relax the 100 independent
training / 100 independent heldout event requirement. No numerical forecasting
performance or profit is established by this work.

## Actual progress

The unchanged Phase8 event-first bundle contains 250 parent groups and 51 strict
API-verified outcome groups. Its manifest remains
`4b2267b34249cb1230b7bc7b3ff69f310e97f148ce181bcdecd0fcc8856644fb`.
The new bounded acquisition corroborated **47** of those groups against Polygon
CTF `ConditionResolution` logs, exact selected-outcome payout, successful
transaction receipt, matching canonical block hash, finalized height and block
timestamp. Four groups remain uncorroborated within this acquisition's budget;
they are not upgraded by inference. The acquisition used 95 archived read-only
RPC requests and 1,296,482 response bytes. A small preceding exploratory probe
checked endpoint availability and the misleading transaction reference; it is
not counted as archived acquisition evidence.

An instructive case is condition
`0x1324039996d7470ac9ff2067a5fc07c7f6bfcd37e16849a3b6b10f47ad35f50f`.
The source API's transaction reference
`0xa64ab911de93402a46fccf51042384a543e4f053c549a002efc4472fae0439b9`
contains market preparation, not condition resolution. The separately discovered
resolution transaction is
`0xe8cbf697f99324106e665d9f24daf129c42b812699d0207dd5c129c0c17f63ba`.
A lifecycle API timestamp, market closing time, end time, or transaction hash by
itself therefore cannot supply exact settlement time.

The original 897,192 publisher L2 rows remain separate. Their publisher capture
times are not original exchange event/receipt times, and their winner columns
remain excluded from features. This qualification step does not turn them into
execution-certified books or resolve their asset/window dependence. Their
original files and the official bundle are read only.

## Verification and provenance

`ReadOnlySettlementClient(directory)` permits only `eth_chainId`,
`eth_getTransactionReceipt`, `eth_getBlockByHash`, `eth_getBlockByNumber` and
reviewed, bounded `eth_getLogs` queries. There is no transaction submission,
wallet, signer or authentication flow. The endpoint is the provider's public
Polygon RPC; the client requires chain ID137. It caps requests at100, response
bytes at100MiB, individual responses at10MiB, and a free-disk floor of8GiB plus
the remaining budget. A versioned output directory must be new and empty.
Every exact JSON request and response hash, retrieval time, URL, method and raw
response is retained. Large block searches, other contracts and other event
signatures reject before network access. The acquisition's broad native-block
hints select search ranges only; they never establish a resolution timestamp.

`corroborate_resolution(...)` checks the reviewed Solidity event signature,
contract address, condition ID, exact binary payout, removal flag, transaction
success, exact log inclusion, receipt/block identity, canonical block header and
finalized height. Unsupported contracts, fractional/ambiguous payouts,
noncanonical blocks and unavailable evidence fail closed. Its result preserves
`settlement_at` as block event-time and `available_at` as current acquisition
time, with `availability_basis="collected_now"`. An HTTPS RPC source and retained
raw evidence make the claim attributable and replayable; this is not independent
node consensus verification or a cryptographic historical availability witness.

`qualify_history(source_dir, output_dir, rpc_evidence_dir=..., workers=2)` verifies
the original bundle's raw/normalized integrity and independently replays every
chain proof from its archived responses. It rejects raw tampering, normalized
proof changes and backdated/future proof availability. It writes immutable
`events.jsonl`, `manifest.json` and `report.json` under a new output directory.
Each row links original record/raw hashes, token/condition/event identity,
selected payout, exact settlement proof, original rule-text hash, availability,
a proposed dependency grouping and explicit outstanding deficiencies. Proposed
groups are never marked reviewed. Current rule text is not asserted to be its
historical version.

## Reproduction and actual parallel work

The acquired evidence is local research data, excluded from Git:

- `data/phase9qualification/chain`: exact RPC responses, manifest and47 proofs.
- `data/phase9qualification/qualified-v2`: final reproducible qualification output.

The source implementation uses exactly two spawned CPU workers with a start
barrier, not a sequential loop advertised as parallel. In the final actual run,
workers **2953139** and **2953142** processed125 authentic event records each;
recorded work intervals overlap. Coordinator2953118, manager2953134 and resource
tracker2953133 were also live, for **five job processes**, of which **two** were
CPU workers. Numerical library thread counts were fixed to1. The preceding v1
run likewise used two CPU workers (2950802/2950805); repeated runs are not
additional independent evidence or a speedup claim. The manifest records these
identities and intervals. Test execution uses one pytest coordinator; its
controlled qualification integration test separately exercises the two-worker
path and does not constitute real-market evidence.

Example library reproduction (call from an importable script with a main guard
because multiprocessing uses spawn):

```python
from neraium_poly.research.qualification import qualify_history

if __name__ == "__main__":
    report = qualify_history(
        "data/phase8-history-events",
        "data/phase9qualification/qualified-new-version",
        rpc_evidence_dir="data/phase9qualification/chain",
        workers=2,
    )
```

The final event rows hash is
`a4c2adfed62287a033a665a44ce33b4cbbfd05574bc46c4092b33277776f65f5`;
the chain proof file hash is
`73a8d8b20618ee5a6bb66c90a57ec0347ee98d78e4375401ecb6c1da846fd12f`.
The final v2 manifest hash is
`f2385debd22d365447c3254a9b4fa5dcab1450c3c60a790a35b7eec42881832a`.

## Remaining certification deficiencies

The 47 newly timed outcomes do not produce qualifying training or heldout rows.
Predecision availability, historical executable depth, independent external
context, historical rule consistency and dependency review remain unqualified.
The qualification report consequently records0 reviewed independent events,
0 certifiable training events and0 certifiable heldout events. It cannot promote
an experimental strategy, generate certified approval, or turn simulated P/L
into independent evidence. Further authentic acquisition/review must assemble
100 independent events on each chronological side, realistic costs/fill
assumptions, calibration and reproducible out-of-sample results before explicit
owner approval is even applicable.

Primary sources inspected2026-11-06:

- [Polymarket official event ABI and resolution mapping](https://github.com/Polymarket/go-market-events/blob/main/README.md)
- [Polymarket deployed contracts and Polygon chain ID](https://docs.polymarket.com/resources/contracts)
- [Official SDK release notes: lifecycle transaction/log locator caveat](https://github.com/Polymarket/py-sdk/releases)
- [Official Data API live schema](https://data-api.polymarket.com/v2/docs)
- [PublicNode Polygon endpoint publication](https://polygon.publicnode.com/)
