# Persistent live-market paper operation

`neraium-poly paper-live` is the integrated real-market coordinator. It never imports or runs the synthetic scenario. The previous `serve` demonstration and `serve --database` public archive remain separate commands. The integrated API/dashboard binds to **127.0.0.1:18742**, preserving the existing port18740 archive service.

```sh
uv sync --frozen --extra dev
npm ci --prefix frontend
npm run build --prefix frontend
uv run neraium-poly paper-live --config config/paper-live.example.json
```

The installed `neraium-poly-paper.service` runs this command as ubuntu, starts at boot and restarts on failure. It has a1GiB memory limit, one CPU quota, no privilege escalation, read-only source files and write access only to this project's data/paper-live directory. Its unit is in deploy/systemd/. Inspect with `systemctl status neraium-poly-paper.service` and `journalctl -u neraium-poly-paper.service`. Updating source does not update an already running process; perform a scoped restart after verification. Other services are preserved.

## Real observations and execution

Discovery defaults to 200 eligible markets ordered by 24-hour volume, using
bounded pages. It excludes markets without enabled books or accepting orders.
Up to 400 binary outcome tokens subscribe to the public market WebSocket;
bounded asynchronous REST fallback shares an 8-request/second limiter and four
in-flight slots. Configuration caps both markets and subscriptions. Native full
book/delta counters are separate from REST bootstrap counters. Scope changes,
disconnects, queue overflow, unknown baselines and inconsistent deltas invalidate
affected cached books and trigger bounded recovery. Freshness is never inferred
from receipt time or a successful socket connection. Quiet books can be stale.
Approved strategy scope and held-position metadata remain pinned independently.

Source CLOB timestamps, receipt time, instrument identity, visible bid/ask levels and depth are preserved. The relationship engine uses **observed book midpoints as market observations**, never as independently validated probability estimates. Re-receiving an unchanged source timestamp cannot inflate the temporal baseline. Same-event associations are research hypotheses; logical settlement constraints are not inferred. Freshness, missing data, sample size, persistence, spread, liquidity and settlement semantics qualify or suppress findings.

The research and approved-strategy relationship engines are separate, with durable, policy-bound checkpoints. Inactive research caches are bounded to the current universe and held positions. A reviewed model is required before ProbabilityEstimate, TradingOpportunity, OrderIntent or risk/execution actions can be generated. Approved outcome-token scope is enforced for both target and peer markets. Revoked or expired approval is checked again after network waits and before pending execution; remaining paper orders cancel.

Market-specific fee curves are read from current CLOB market details with exact token membership. A legacy fee BPS field is not substituted for a protocol curve coefficient. Only supported exponent1 taker curves qualify, with finite global notional fee bounds and a TTL. Unknown fees withhold opportunities. The broker and risk engine enforce conservative fees, slippage, actual observed depth, latency, participation, partial fills, reservations and approval expiry. Books are freshly fetched after simulated latency before a pending fill is advanced.

Position notional and tier are configured independently of quantity: standard$2–$5, high$5–$15 and exceptional$15–$25. The approved manifest must permit the tier. All hard market/event/correlation/aggregate, uncertainty and exceptional independent-evidence controls still apply; no confidence score bypasses risk.

## Validation and explicit approval

```sh
uv run neraium-poly strategy-status --data-dir data/paper-live
uv run neraium-poly strategy-validate --data-dir data/paper-live \
  --dataset reviewed-observations.json --manifest reviewed-manifest.json
uv run neraium-poly strategy-package --data-dir data/paper-live \
  --report-id EXACT_PASSING_REPORT_ID --output request.json
# Only after independent owner review/signature and provisioned public-key trust:
uv run neraium-poly strategy-approve --data-dir data/paper-live \
  --report-id EXACT_PASSING_REPORT_ID --actor OWNER_REVIEWER \
  --owner-public-key /owner/provisioned/public.pem \
  --owner-request-id EXACT_REQUEST_ID --owner-signature /owner/provided/signature.bin
uv run neraium-poly strategy-revoke --data-dir data/paper-live \
  --actor NAMED_RESEARCH_REVIEWER --reason 'Review withdrawn'
```

Validation never calls approval. The service reads the durable approval database and does not bundle a real model or dataset. The report hashes the exact input bytes, scope and policy; reconstruction/revalidation rejects tampering, expiry and incompatible approvals. Full input schema, thresholds and trust limitations are in [real-strategy-validation.md](real-strategy-validation.md).

A mechanically passing file is not proof that its claimed provenance is true. A named review must inspect real point-in-time archives, external context and independently verified final outcomes. Test-only positive activations are never installed in the operational approval database. Market prices alone, currently downloaded histories with unknown availability, and manufactured book depth cannot supply missing validation data.

## Durable capital, settlement and recovery

The default simulated bankroll is$500. Risk, broker, strategy approval, service metadata and append-only event records persist in separate SQLite WAL files under data/paper-live. A process lock permits only one coordinator per directory. Restart reopens existing bankroll/positions/reservations rather than resetting capital; altered risk limits require explicit migration. Broker acknowledgement recovery and bidirectional reconciliation run on startup and each cycle; inconsistency trips the persistent kill switch.

The dashboard emergency stop writes the risk ledger. There is no browser reset and restarting does not clear it. Resolve the cause and use an explicitly reviewed operator action before resuming. The synthetic scenario endpoint rejects requests in integrated mode.

Positions are marked conservatively at fresh observed bids. Stale marks remain identifiable from book timestamps; a current equity snapshot is not proof of fresh prices for every held position. Simulated realized and unrealized P/L are distinct; actual financial realized P/L remains zero. Orders, fill acknowledgements, positions, risk decisions and simulated settlements are audited and exposed in dashboard state.

Automatic simulated settlement defaults **off**. Closed flags, terminal prices and dates are insufficient. The adapter requires a final, undisputed native binary payout and matching identity/rules/source. The coordinator independently verifies that binding and requires a separate token-level rule review actor and hash before posting a simulated settlement. Its hash is `identity(market_id,token_id,outcome,resolution_rules,resolution_source)` from ops.live; relationship IDs cannot authorize payouts. Configure allow_simulated_settlement only together with those explicitly reviewed settlement_rule_hashes and settlement_review_actor fields. No actual redemption occurs.

## Operational limits

Both PAPER_TRADING=true and LIVE_TRADING_ENABLED=false are required. LiveBroker always raises; no wallet, signer or external order submission exists. The API stays on loopback and is not a public multi-user deployment.

The supplied production configuration archive budget2GiB and free-disk floor8GiB stop collection/evaluation with a visible health error before resource exhaustion. No unrelated data is deleted or cleaned. Archive rotation/export is an explicit operator task; the service does not silently discard replay evidence. SQLite remains a single-owner research deployment, not a distributed trading system. Public HTTP responses can be cached; source freshness is enforced independently of receipt time. Strict15-second source-age checks and bounded polling/stream recovery can leave many quiet books stale and suppress all opportunities. No minimum trade count is imposed.


## Phase8 research operation

`research-acquire --research-dir NEW_DIRECTORY --event-first --max-events 250
--max-history-requests 50` creates a bounded, immutable-provenance acquisition.
Never overwrite an evidence directory. `research-evaluate --research-dir DIRECTORY
--output REPORT` reproduces six-candidate evidence and calibration diagnostics.
Use `uv sync --extra research` for optional Parquet archive inspection;
`research-audit --research-dir ARCHIVE --output AUDIT` keeps publisher L2 claims
separate from official executable books. See historical-evidence.md for actual
sources, counts, hashes and unresolved provenance.

The persistent service samples actual current depth states into a bounded replay
archive with exact full states, quote-level deltas and receipt references. This
is sampled live evidence, not a promise to archive every exchange tick. It
refreshes the configured historical research report hourly. Historical API
acquisition remains an explicit bounded CLI operation; it is not an unattended
download loop. Report refresh cannot generate owner approval or certify missing
evidence. Missing exact settlement availability, independent context, dependency
review or historical executable books leaves model metrics and strategy P/L null.
