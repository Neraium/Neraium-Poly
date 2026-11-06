# Domain-neutral market discovery and measured coverage

`research/phase14/discovery.py` implements bounded public Gamma metadata discovery
and classification. It changes no existing market snapshots, account, strategy,
WebSocket subscription, risk gate or live-order path.

## Public interfaces and interpretation

- `classify_market(raw, received_at) -> DomainMarket` retains actual structured
  categories/tags, event/market/outcome-token IDs, rules/source, status, provider
  liquidity/volume and source-update metadata. Timestamp/availability represent
  the actual metadata observation, not an invented historical quote timestamp.
- `classify_snapshot(market, now) -> DomainMarket` projects legacy normalized
  metadata without inventing missing tags, companion tokens, liquidity or depth.
  It retains the original source/availability timestamps and marks stale records.
- `DomainDiscovery(...).discover(max_markets=200)` returns bounded domain markets,
  an explicit coverage report, and raw response objects for evidence persistence.
  `close()` closes only an internally owned HTTP client.

The classifier uses exact structured categories and tag slugs first, a boundary-
checked explicit resolution-source host next, and only provisional keyword
suggestions otherwise. Ambiguous keywords remain`other` with review required.
Conflicting structured domains also quarantine as`other`; contextual people names
are not silently treated as domain taxonomy. Generic sports/esports and finance/
crypto tags retain the more specific type. Classification does not qualify a
contract's settlement rules or independent forecasting evidence.

The loader queries actual provider tag IDs. It does not invent IDs from examples
or keyword guesses. Its sorted tag catalog, top-volume event bootstrap and
category-specific event queries address weather, crypto, finance, economics,
politics, sports, esports, technology, science, geopolitics and entertainment.
Selection round-robins categories and prioritizes actual reported liquidity within
categories. No category quota establishes liquidity or forecast quality.

Bounds: at most16 publicGETs, at most2 request starts/second,16MiB retained complete
response data,4MiB per complete response, at most2,000 candidate metadata markets
and200 selected markets. Requests are serialized/rate-limited and discovery calls
are mutually exclusive. 429/503, oversized data or malformed metadata withhold;
there is no retry loop to force data. Canonical-tag404s are explicit unavailable
categories, not fabricated IDs. Request/byte counts and raw-body SHA256 plus
receipt times are retained. Exact response UTF8 bytes permit hash replay.

Spread, depth and executable quote verification remain unknown/false unless a
separate actual order-book observation qualifies. Gamma metadata liquidity is not
executable depth. There is no probability model hidden in discovery and no market
price feature is used for domain classification.

## Actual coverage evidence

The existing200-market collector orders candidates by reported24h volume and
stops at its configured200-market budget, with rotation disabled. It does not
explicitly restrict discovery to sports, but high-volume selection and discarded
structured tags limit category representation and classification. Its current
producer is budget-degraded; cached snapshots are not live executable data.

At09:00:18UTC on2026-11-06, a bounded fresh public capture performed15GETs at the
2/s cap and retained3,251,766 response bytes. Actual tags were received from the
provider, including sports1, politics2, crypto21, technology22, entertainment53,
esports64, science74, weather84, economics159, finance120 and geopolitics100265.
The source returned339 eligible active metadata candidates;200 were selected.
There were no API errors in this final capture.

| Category | Fresh candidates | Fresh selected | Legacy cached200 projection |
|---|---:|---:|---:|
|Weather|22|21|1|
|Crypto|30|21|34|
|Finance|20|20|0|
|Economics|18|18|9|
|Politics|99|20|6|
|Sports|36|20|6|
|Esports|19|19|13|
|Technology|1|1|0|
|Science|0|0|0|
|Geopolitics|31|20|0|
|Entertainment|40|20|0|
|Other/review|23|20|131|

Science was queried successfully; its two sampled events were alien-confirmation
and largest-IPO questions carrying conflicting politics/pop-culture/science or
business/science tags. They remain under review rather than being forced into
science to inflate coverage. Zero here means none classified in this bounded
sample, not absence of science markets globally.

Of the200 fresh selections,169 were absent from the cached monitored200. This
supports broader metadata research sampling, not immediate subscription expansion:
raw tags improve classification, and the fresh sample was deliberately stratified
rather than a like-for-like estimate of total market prevalence.131 cached markets
require stronger structured metadata. The legacy cached frame was exported at
08:25:51UTC while the producer was already degraded; no cached book or metadata
was represented as a new live observation.

The first capture rejected an oversized20-event page under the unchanged4MiB
response guard. The final capture used smaller two-event pages and a sorted tag
catalog; thresholds were not loosened. The failed report remains preserved as
`observed-distribution.json`; the final report is`observed-distribution-v2.json`.

Raw complete final response proof is temporarily retained at
`/dev/shm/neraium-poly-phase14/discovery/fresh-metadata-v2.json`:
7,409,908bytes, SHA256
`0654f93061ce9e2e804b54833da819497e0a50a2448468b3e6bdac4b4e44dfef`.
That RAM capture is **not a durable archive**. No forecast, order, fill, independent
model, subscribed market or execution-certified depth was created by discovery.
Root storage remains below8GiB, so durable collection and any expanded execution
universe must remain gated. Coverage reports explicitly say the universe is not
complete. Broad discovery cannot guarantee a profitable strategy.

## Validation and sources

17 controlled tests cover structured precedence/conflicts, exact host matching,
unknown metrics, old snapshot timestamps, missing identities, category round robin,
provider IDs, rate failures, byte limits, source hash replay, price independence
and configuration bounds. Fixtures are not actual coverage observations.

Primary API references:
[Polymarket market-data skill](https://github.com/Polymarket/agent-skills/blob/main/market-data.md),
[Gamma API](https://gamma-api.polymarket.com/docs), and
[official Python SDK public client](https://github.com/Polymarket/py-sdk/blob/main/src/polymarket/clients/public.py).
Actual API calls verified the accepted`order=volume24hr` event query and sorted
`/tags?order=id&ascending=true`. No wallet or account credentials are used.
