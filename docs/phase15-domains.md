# Phase 15 domain evidence and calibration research

This work extends Phase 14 without changing sports models, model registries,
strategy authorization, forecast journals, or either paper account. No new model
has demonstrated independent forecasting skill. No new market forecast, order,
fill, or performance result is claimed.

## Implemented boundaries

`research.phase15.domains.collect_nws_precipitation` collects an official NWS
point lookup and follows its official hourly-product link. Both responses are
bounded to 512 KiB, preserve original UTF-8 and SHA-256, use explicit retrieval
and product timestamps, and refuse redirects, untrusted hosts, future product
issuance, malformed units, and unbounded periods. The collector makes at most
two GETs and never retries rate limits in a tight loop. A scheduled caller must
respect Cache-Control/Retry-After and apply backoff; no new persistent network
loop has been enabled by this module.

Provider precipitation percentages are probabilistic research inputs, with
explicit point/period semantics. They are **not** a station daily-temperature
distribution, arbitrary rain-threshold probability, mapped market forecast, or
independently calibrated model. The returned `DomainEvidence` declares these
missing prerequisites.

`qualify_domain_inputs` verifies content and raw-response hashes and time/domain
binding. It withholds numerical forecasts and exposes precise reasons: expired
weather windows, station/window missingness, unreviewed crypto candle conventions,
and absent first-release economic vintages/calibration. It does not grant
experimental or certified authority.

`calibration_report` supports independent raw replay through an explicit verifier.
Without a verifier every observation fails closed. A verifier must replay the
immutable forecast, external feature inputs, contemporaneous baseline, official
outcome, and dependency grouping; a caller-supplied boolean cannot itself prove
source authenticity. Inputs are bounded to 10,000 rows and content hashed. Each
accepted dependency group counts once across train and held-out cohorts. Future
inputs/resolutions, hidden market features, mixed domain/model/feature/contract
semantics, and training outcomes available after held-out forecasting are
rejected or block scoring. Market baseline must precede the forecast by at most
60 seconds. Original certification minimums remain 100 independent training and
100 independent held-out events. Sufficient counts never grant certification.

Replay-qualified held-out cohorts expose Brier score, log loss, reliability bins,
and a conservative distribution-free 95% interval for paired Brier differences.
Small cohorts retain insufficiency warnings; empty/invalid cohorts return null
scores. Execution-adjusted performance remains null: forecasting accuracy cannot
establish executable profit, queue priority, exit liquidity, or risk approval.
No calibration cohort is currently supplied from authentic independent resolved
forecasts, so real calibration metrics remain unavailable.

## Actual bounded observations

All timestamps below are UTC, 2026-11-06. Local evidence remains in the root
checkout's ignored `data/phase15/domains/`; raw payloads are not committed.

| Observation | Result |
|---|---|
| Read-only collector market frame at 20:27:42.143299 | 200 distinct markets: other 146, sports 21, esports 15, crypto 11, economics 7, weather 0 |
| Market-frame hash | `f8acaf395bc7c447c6592c772c334d994357eecd63ae088ca3b71fa25d7c7280` (1,961,020 bytes) |
| Mapping audit at approximately 20:33 | All 11 crypto contracts rejected as unsupported barrier/path/non-terminal contracts; all 7 economics contracts require settlement/vintage review and an independently validated model |
| NWS point lookup | Requested 40.7789,-73.9692; official response selected grid OKX/34,45; this is not a verified settlement-station match |
| NWS hourly retrieval at 20:31:04.143010 | Product issued 18:27:04; 155 strictly future hourly precipitation periods retained |
| NWS raw product hash | `15cdb66a0739938146109fc0e9e0fdfab94f30ddef4cd2820758892932fe17d0` |
| NWS serialized evidence hash | `4346d0ef7049f03015068671d0556567ad826c2882d364884d2d90a9759b1d45` (205,313 bytes) |
| Official FOMC calendar retrieval at 20:33:01.082230 | Raw hash `f45b5ee97566e8b19081acd78f594de4095f8dacccc64957982eb15185d7fa91`; publication timestamp unknown, earliest verified availability is retrieval |
| Binance BTCUSDT one-minute candles at 20:33:01.970661 | 1,000 completed rows; first open 1793937180000 ms, last close 1793997179999 ms; 169,740 bytes |
| Binance raw hash | `40ef1b9c9f1cb36102f111d19c415b337bac6841d4dc64f536feb4a38c2940d9` |

The Binance capture uses `/api/v3/klines`, interval 1m, limit 1000, explicit
endTime 1793997179999. It is not historical depth, a pre-retrieval available
feature dataset, or evidence of a profitable barrier model. Examples of monitored
contracts are BTC reach $81,000 November 6 (market 6739553) and BTC dip $66,000
November 2–8 (6563876). Their final candle high/low path rules cannot be replaced
with terminal-close threshold probabilities. The noon candle-label versus
close-time convention remains unreviewed; this work does not guess it.

Economics examples are December FOMC +25 bps (3215008), unchanged (3215007), and
another 2026 hike (4620900). Shared event groups, e.g. parent 770450, cannot count
as independent observations. A calendar and the current effective funds rate do
not estimate a future target-upper-bound decision probability.

The existing exact weather mapper supports RKSI's November 6 local-day high
only. That observation window ended at 15:00 UTC before this research capture;
recording a new prospective forecast for that window would be invalid. Current
monitored weather coverage is zero. Existing NFL models and forecasts are
preserved; no sports retraining or source replacement occurs here.

## Primary-source inventory and qualification

| Source | Accessible evidence / constraints | Qualification confidence |
|---|---|---|
| [NWS API documentation](https://www.weather.gov/documentation/services-web-api) | Public point/grid products; descriptive User-Agent required; rate limit is unpublished; obey rate responses and caching. One point lookup and one product GET performed. | High for retrieved provider product; no claim of historical archive coverage or station mapping |
| [NWS precipitation definition](https://www.weather.gov/ppg/forecast_terms) | Probability of at least 0.01 inch liquid-equivalent precipitation at a point during the specified period. Do not sum hourly probabilities to create daily-event probability. | High for semantics; market compatibility unverified |
| [NWS disclaimer](https://www.weather.gov/disclaimer) | NWS information generally public domain unless noted; retain attribution, avoid implied endorsement or presenting modified data as official. | High for public NWS product; check exceptional third-party attribution before reuse |
| [Aviation Weather API](https://www.connect.aviationweather.gov/data/api/) | METAR observations, recent 30-day query horizon, commonly 400-row response cap, 100 requests/minute documented. Existing RKSI collector preserved. Observations alone do not provide a future maximum-temperature distribution. | High for observations; incomplete final-day/corrections/calibration remain blockers |
| [Open-Meteo ensembles](https://open-meteo.com/en/docs/ensemble-api), [pricing](https://open-meteo.com/en/pricing) | Ensemble inputs could support temperature uncertainty. Free endpoint is noncommercial, up to 10,000 requests/day; data CC BY 4.0 does not remove service-use terms. Commercial/ensemble plan eligibility and charges are not authorized here; no request/subscription made. | Source evaluated, acquisition withheld pending license/use qualification |
| [Binance public API](https://developers.binance.com/en/docs/products/spot/rest-api) | Official data-only base `data-api.binance.vision`; millisecond open/close timestamps. Public access requires no wallet/key. Respect endpoint/IP request-weight limits; one bounded request performed. Public API access alone does not establish unrestricted redistribution rights or market eligibility. | High for retrieved prices/reference; settlement path model and independent calibration absent |
| [Federal Reserve calendar](https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm) | Authentic current calendar, one GET, no invented publication time. No vintage or independent probability supplied. | High for current context; unqualified as historic release-time feature |
| [FRED real-time periods](https://fred.stlouisfed.org/docs/api/fred/realtime_period.html), [vintage dates](https://fred.stlouisfed.org/docs/api/fred/series_vintagedates.html) | API key needed for this route. Date-level vintages do not establish exact intraday release/availability. Revised latest values cannot substitute for initial release values; series-specific source rights must be checked. No credentials searched or paid acquisition performed. | Evaluated; exact release-time historical evidence absent |

Politics, technology, science, geopolitics and general events retain existing
review-required evidence contracts. No news summary is converted into an
unsupported scalar probability. Cross-domain numerical models, observed
forecast superiority, and execution-certified historical cohorts are not claimed.

## Tests and next research conditions

Controlled unit fixtures test timestamp leakage, baseline timing, dependency
deduplication, split leakage, model/semantics binding, metrics/null behavior,
no-promotion authority, NWS raw integrity, host/size/rate-limit handling, and expired
weather admission. Fixtures do not count as genuine data or successful forecasts.

Next steps: identify live weather contracts with exact official station/window
rules; accumulate timestamped predictive distributions and independently verified
observations; resolve crypto path-versus-terminal conventions and acquire matched
historical paths without counting today's retrieval as old availability; acquire
first-release economic vintages and exact publication evidence. Only then build
separate chronological calibrated models and compare against contemporaneous
market baselines. Preserve research-only status pending explicit admission review.
