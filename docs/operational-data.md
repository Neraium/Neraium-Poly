# Operational public-data adapter

`OperationalPolymarketAdapter` extends the existing rate-limited, bounded-retry public adapter. Every request is GET. It has no order, signing or wallet transport.

`await discover_bounded(max_markets=50, page_size=50, max_pages=4)` returns a `DiscoveryBatch` with normalized `markets` (one record per outcome), unique raw `scanned_count`, `truncated`, `errors`, and `next_offset`. Bounds are checked. Offset advances across calls and returns to zero when an incomplete final page proves the end; a bounded batch does not claim exhaustive exchange coverage. The coordinator should persist the offset and retain its separately bounded monitoring universe rather than silently treating each batch as the whole exchange. Invalid or inactive rows never become active market observations.

`await fee_model(token_id)` resolves a public token to its parent condition, verifies token membership in CLOB market details, then reads the current `fd` fee curve. Existing `ProtocolFeeModel` supports decimal `fd.r`, exponent `fd.e=1`, and taker-only `fd.to=true`; unknown or unsupported curves return `None`. The coordinator must use a bounded freshness TTL for fee observations and suppress decisions when fees are unavailable. The old `/fee-rate` `base_fee` is documented in basis points but is **not** silently interpreted as the current curve coefficient. A real probe returned legacy base fee 1000 while market details supplied curve coefficient0.04. Reserve modeling remains globally conservative as documented in `strategy.md`.

`await settlement(market)` returns a `SettlementObservation` only after checking a fresh Gamma market record, exact market/event/token/outcome and unchanged settlement rules/source, matching CLOB parent condition, and exactly one final Data API `/v2/resolutions` row. It requires undisputed, nonarbitrated, nonrevised, reported BINARY resolution with a transaction hash and a unique terminal payout `[1000000,0]` or `[0,1000000]` in micro-USDC. It rejects provisional/closed-only/price-implied resolution, fractional payouts, derived negative-risk settlements and changed metadata. Source timestamps cannot be in the future. The payout array is matched to Gamma's aligned outcome/token ordering. The observation keeps `rules_reviewed=False`: the coordinator must bind an independent explicit review of the settlement semantics and outcome ordering before settling the paper ledger. This conservative implementation can withhold a legitimately resolved market when the API omits necessary finality evidence; it must not guess.

`build_statistical_relationships(markets, now, max_pairs=200)` proposes bounded same-event YES pairs. These are statistical research hypotheses from observed event membership, never logical exclusivity/exhaustiveness assertions. Confidence0.7 is a declared candidate-relevance policy prior, not an empirically measured relationship confidence or outcome probability. No candidate alone authorizes a trade. The temporal engine must establish its baseline, context and persistence; an independently validated model and risk engine still gate every order. Related market prices must come from fresh observed CLOB books, not cached Gamma metadata. IDs are structurally stable; the coordinator must retain the first edge definition and availability time across scans instead of appending newly timed redefinitions under the same ID.

## Primary documentation

Inspected2026-11-06 UTC:

- [Public discovery](https://docs.polymarket.com/market-data/discover-markets)
- [CLOB OpenAPI](https://docs.polymarket.com/api-spec/clob-openapi.yaml), including `/markets-by-token`, `/clob-markets`, current fee details and legacy fee-rate units
- [Fee curves](https://docs.polymarket.com/trading/fees)
- [Data API V2 OpenAPI](https://data-api.polymarket.com/v2/openapi.json), including `/v2/resolutions` finality, provenance and payout units

## Verification

34 operational module tests cover bounded pagination beyond10markets, rotation,429 retries, invalid rows, current versus legacy fee units, unsupported fee curves, settlement identity/rules/finality, future resolutions and hypothesis boundaries. On2026-11-06 at00:22:16 UTC a bounded public smoke fetched50 distinct actual markets (IDs559651–559700),100 outcome records, with zero normalization errors. It generated200 bounded association hypotheses and verified market559651's curve coefficient0.04. This is actual public connectivity evidence, not out-of-sample strategy validation or trading activity. The full smoke record is retained in this worktree's `.planning/evidence/operational-data-smoke.json`.
