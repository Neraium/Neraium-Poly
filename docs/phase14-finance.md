# Finance, crypto, economic and general-event research

Phase14 adds domain-neutral adapters; neither an adapter nor an external price
series grants trading authority. Sports remains a separate supported category.

## Implemented interfaces

- `map_financial(market, now=...)` checks an exact audited Binance BTC/USDT or
  ETH/USDT noon-close threshold template, side, strict comparison and ET/UTC time.
- `collect_financial(contract, client=..., clock=...)` reads one bounded official
  public market-data endpoint; no credentials or account/order endpoint exists.
- `forecast_financial(contract,evidence,cutoff=...)` is a reproducible terminal
  close-price log-diffusion research baseline, enabled only for a separately
  reviewed exact candle-time convention. `FinancialResearchModel` implements the
  common domain model interface. No Polymarket probability is a predictive input.
- `map_economic`, `collect_economic` and `forecast_economic` separate official
  context acquisition from release-vintage qualification and numerical forecasting.
- `qualify_economic_vintages` requires exact aware initial-release, retrieval and
  vintage times, source/series/units/hash, and withholds revised or unavailable facts.
- `map_general`, `qualify_general_evidence` and `forecast_general` provide explicit
  provenance/manual-review contracts for politics, technology, science, geopolitics,
  esports and entertainment. Timestamped prose does not become a numerical model.

## Exact financial settlement and model limitations

The implemented terminal model is **not** a crossing/barrier probability model.
The observed universe contains monthly and annual high/low touch contracts. They
are withheld: incomplete history cannot establish whether the event has already
happened, nor can current terminal probability stand in for pathwise probability.
Other exchanges, pairs, prices and settlement timestamps are never substituted.

Even an exact match to the observed noon-close template remains `review_required`.
The market says "closing at12:00ET", while Binance candles expose opening labels
and close timestamps. The candidate minute-ending interpretation has open=end-60s
and close=end-1ms. It is not silently promoted into an approved settlement rule.
An explicit reviewed rule convention is required before a market forecast can issue.

Under a controlled reviewed convention, the simple model estimates measured
one-minute log-return volatility from at least720 contiguous completed candles;
its zero-log-drift terminal threshold probability uses the exact horizon and
threshold. Only1minute–24hour horizons are supported. No forming candle enters
features; gaps, duplicates, contradictory OHLC, stale final observations, wrong
symbols/origins and unavailable/future evidence reject. The model's0–1 uncertainty
range is uncalibrated and prevents a research probability from implying confidence,
execution edge or trading admission. Jumps, changing regimes, tails and held-out
calibration are missing. Statistical volatility is not implied volatility.

The official [Binance market-data-only documentation](https://github.com/binance/binance-spot-api-docs/blob/master/faqs/market_data_only.md)
identifies the unauthenticated source. The [REST kline documentation](https://github.com/binance/binance-spot-api-docs/blob/master/rest-api.md#klinecandlestick-data)
defines timestamp/interval fields. HTTP403/451/429 errors fail closed; the adapter
never retries through another origin to evade restrictions. Public API access is
not represented as an unrestricted redistribution license. Raw provider payloads
are preserved as evidence, not committed as a public dataset.

## Authentic observed ingestion

At **2026-11-06T08:40:54.802416Z**, the actual public Binance endpoint returned
**1000 completed BTCUSDT one-minute candles**, **170,120 bytes**. At
**08:40:54.862774Z**, the [official Federal Reserve FOMC calendar](https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm)
returned **166,350 bytes**. These were real unauthenticated GETs, not fixtures.
Their source URLs, hashes, retrieval times, closed-candle bounds and measured
volatility are in `.planning/evidence/phase14-finance/actual-ingestion.json`.

At this workstream's capture, root disk was below the existing8GiB safety floor.
The raw replay artifacts therefore resided in bounded volatile memory at
`/dev/shm/neraium-poly-phase14/finance/crypto-evidence-v1.json` and
`economics-evidence-v1.json`. That is **not durable storage or continuous service
operation**. No disk floor was weakened. The coordinator may copy and verify raw
artifacts into approved durable storage after capacity is restored. A checksum
without surviving raw evidence is insufficient for durable forecast qualification.

**Zero independent market forecasts were issued by this workstream.** Crypto
withheld for candle-convention review, economics for missing qualified model and
release vintages, and general events for unsupported numerical forecasting.
The genuine ingestion supports research-adapter readiness, not model validation.

## Economics and less structured events

The Fed calendar is current official context with actual retrieval availability,
not a historical publication vintage, numerical consensus, or a probability for
an upcoming vote. Target federal-funds upper bound is explicitly distinguished
from the effective federal-funds rate. A calendar or latest rate does not supply
an independent FOMC decision model. FRED/BLS/BEA source contracts exist, but no API
key, licensed consensus or historically qualified vintage collection is assumed.

The vintage qualifier is structural only: raw hashes still require independent
replay. Date-only vintages, post-cutoff retrievals, unknown/revised release status,
non-official source origins and missing series/units/provenance withhold. It never
backdates current/revised data to its observation month.

General evidence passes no automatic reviewer. Interpretation review is required
for event identities, authoritative sources, outcome conditions and timing. There
is no numerical fallback from a news summary, election title or technology rumor.

## Validation

31 focused controlled tests pass, covering exact mapping, source identity,
GET-only access, geographic refusal, original bytes/hashes, future/open candles,
gaps, duplicates, bad OHLC, stale data, reproducibility, complementary outcomes,
vintage leakage/revisions and default-deny general evidence review. Fixture
probabilities and facts are never counted as authentic observations or performance.
Brier/log loss/calibration/superiority/cost-adjusted performance remain null.
No account, risk engine, certified approval or strategy registration was changed.
