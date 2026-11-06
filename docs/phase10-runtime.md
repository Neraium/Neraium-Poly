# Decision tracing and paper-only recovery

The runtime publishes `decision_trace` alongside legacy totals. Every engine evaluation
records pre-dedup token evaluations for each enabled strategy, then actual
admission results and durable execution audit events. A considered "market" is
one selected outcome-token evaluation, not an independent event. The latest evaluation
is replaced (later cycle stages can fail; inspect service health); the explicit Phase10 epoch accumulates across restarts. Earlier
Phase9 totals remain unchanged and must not be presented as reconstructed funnel
counts. Rejection reasons are nonexclusive. Strategy rejections precede risk;
qualified opportunities may still be withheld before an intent is constructed.

Order attempts include an intent sent to an unavailable risk engine. Such failures
now preserve the intent and count as risk rejections, with zero submitted orders.
Broker failures preserve their intent and decision too. Fills come from durable
risk audit records, not quotes or repeated cumulative broker reports. Entry and
exit fill events are separate; fill counts are not share volume. Expirations and
cancellations are read from durable audits. Emergency cancellation of exit orders
now creates an idempotent cancellation audit. Per-source sequence cursors and
trace counters checkpoint together; events preceding the trace epoch are excluded.
Each cycle processes at most 5,000 audit rows per source. Samples are bounded to
three per reason/scope, 128 reasons and 16 strategies. Cycles archive counts and
categories without repeatedly duplicating samples; actual sample IDs and cost
inputs remain in checkpoints and representative signal records. Existing storage
budgets continue to suspend entry when exhausted.

## Reviewed research-code migration

Startup continues to refuse a changed strategy/intelligence source hash. An
explicit offline operation now supports a reviewed compatible instrumentation or
research change without deleting causal histories or resetting capital:

```
uv run neraium-poly experimental-migrate \
  --expected-previous-hash PREVIOUS_SHA256 \
  --reason 'Reviewed change and compatibility evidence, described precisely'
```

Use the same `--config` as the experimental service when customized. Stop only
that service first. The exclusive owner lock rejects migration against a running
coordinator. The exact previous hash and a compatible existing engine checkpoint
are mandatory. Previous code hash/checkpoint/reason/time are archived in a single
SQLite transaction before updating the code guard. Histories, legacy counters,
experimental risk/broker databases, certified storage and bank balances are not
changed. At most 32 migration records are allowed; exhaustion rejects. This is
neither strategy certification nor approval to trade live.

## Controlled verification

`tests/test_phase10_runtime.py` exercises admitted intents through partial fills,
expiry, bid-side exit fills, emergency exit cancellation, restart recovery,
unavailable-risk accounting and offline migration. Fixtures are explicitly
controlled test inputs; their orders and P/L are never copied to operational
accounts or counted as real-market opportunities. Operational accounts may
legitimately remain at zero trades.

Monitor examples:

```
uv run neraium-poly monitor --view strategies --scope cycle
uv run neraium-poly monitor --view rejections --scope epoch
```

Source documentation checked 2026-11-06: [public market stream](https://docs.polymarket.com/market-data/realtime-data),
[price history](https://docs.polymarket.com/api-reference/markets/get-prices-history),
[fees](https://docs.polymarket.com/trading/fees). Public price history is not
historical executable depth. The strategy and paper broker deliberately retain
the same conservative notional fee bound; an exact-curve counterfactual is a
research diagnostic and cannot override admission or broker fees.
