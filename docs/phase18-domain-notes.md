# Phase 18 independent event forecasting

This module uses external asset data rather than Polymarket prices as predictive
features. New models are research-only. Existing Phase 14 adapters, model versions,
forecast journals, NFL capability and production strategy registration are unchanged.

## Implemented crypto capability

`map_event_contract(market, now=...)` supports one exact daily-low rule template:
BTC/USDT or ETH/USDT Binance final one-minute **Low <= threshold**, with the full
named local New York day, source exchange/pair, question, binary outcome, rules and
closing metadata agreeing. Full rule bytes are retained and hashed. Barrier events
are not terminal-price events. Monthly/weekly windows, different reference sources,
changed wording, unsupported outcomes and future/not-started windows quarantine.

The existing noon terminal-close template remains quarantined. Its wording does
not conclusively select a candle-opening label versus a minute-ending timestamp.
No review flag or one-minute convention was silently changed to create a forecast.

`collect_event_evidence(contract, now=..., client=...)` performs at most two public
Binance market-data GETs. It collects enough closed one-minute data to cover the
entire elapsed settlement window and at least720 recent log returns. Pagination,
minute continuity, OHLC, pair identity, hashes, source URLs and request bounds are
rechecked. Forming/duplicate/gapped/stale candles fail closed. Requests have a
512 KiB response bound and2 MiB total bound. There are no keys, account endpoints,
trade methods, alternate providers, or fallback after geographic/rate/access denial.

Each response records its **actual retrieval timestamp**, independent of the caller's
request-start cutoff. Historical bars retrieved now are available now; their event
timestamps never backdate evidence availability. Raw UTF-8 responses, SHA256, exact
request parameters and provider identity remain in DomainEvidence. Forecast callers
must advance their cutoff after awaiting collection.

`forecast_event(contract, evidence, cutoff=...)` rebinds the original market question,
rules and every derived parameter. It withholds a forecast when any completed candle
already satisfies the barrier; it does not call a known past trigger a new forecast
or verified settlement. The supported research model estimates lower-barrier first
passage under zero-log-drift Brownian diffusion, using720 prior completed log returns.
Its horizon starts at the **last observed candle close**, not forecast creation time,
so the unknown current minute is included. Source age and reference time are explicit.

The resulting number is a conditional model estimate, not demonstrated forecasting
skill. Constant diffusion, continuous-path approximation, jumps, regime changes and
extreme tails are unvalidated. Uncertainty bounds remain **[0,1]**; calibration status
is `unvalidated_research`; Brier/log-loss and executable edge are null. Numerical
complements can round to0/1 and are not empirical certainty. These forecasts cannot
qualify high conviction merely because a model's tail estimate is tiny. Both model
and source implementation hashes, feature version, dataset hash and evidence IDs are
recorded. Selected YES/NO outcomes are complementary, not independent events.

## Authentic acquisition evidence

On2026-11-07T04:00:57 UTC, two public requests returned233,447 bytes and1,380 completed
settlement-window candles, including721 prices for720 return features. Actual market
6739563 ($72,000),6739562 ($73,000),6739561 ($74,000), all parent1323373, mapped to the
exact Bitcoin daily-low template. Six YES/NO token estimates were computed from the
same external evidence and one parent event—not six independent validation events.
Reference last completed price was75,893.66. YES model tails were extremely small;
NO complements near one. All retained uncalibrated[0,1]uncertainty and no trading
or certification authority. Ambiguous noon-close market6475112 stayed withheld.

A fresh04:05:08 UTC audit also succeeded. Original captures and code hashes are
preserved under the worktree's ignored `data/phase18-events/`; subsequent replays
are labeled replays, not retroactively timestamped prospective forecasts. The root
coordinator owns append-only production record admission and current source audits.
No paper account, order, fill, settlement or model approval was modified by this workstream.

## Weather and economics

The source collector supports bounded official NWS gridpoint forecast context and
allowlisted Federal Reserve/BLS/BEA calendar context. These records are explicitly
unqualified for numerical event probabilities. An independent provider-access probe
at04:05:07 UTC fetched actual NWS points and forecast responses (3,917/13,044 bytes)
and the official FOMC calendar (166,350 bytes), preserving raw hashes and retrieval times.
These are **provider-access probes**, with no market ID and no forecast sample count.

A deterministic NWS temperature forecast is not a calibrated probability. Exact
settlement station, units, time zone/window, source compatibility and a qualified
historical forecast-residual or calibrated ensemble distribution are still required.
The selected monitored universe supplied no reviewed matching weather distribution.
`forecast_event` therefore returns an explicit weather withholding reason.

Economic release calendars do not provide first-release vintage values, independently
supported event probabilities or market consensus. Latest revised series cannot be
used as historical initial releases. The existing strict economic-vintage qualifier
is preserved. A qualified independent probability model and causal vintage evidence
remain missing; numerical economic forecasts are withheld. No unsupported probability
was manufactured from news, schedules, observations or provider popularity.

Official source references:
- [Binance market-data API](https://developers.binance.com/en/docs/catalog/core-trading-spot-trading/api/rest-api/market)
- [NWS API documentation](https://www.weather.gov/documentation/services-web-api)
- [Federal Reserve FOMC calendar](https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm)

## Validation

Controlled tests cover exact rule/source/date/outcome matching, threshold monotonicity,
YES/NO complements, Polymarket-feature independence, whole elapsed-window replay,
last-close conditioning time, prior-trigger rejection, candle corruption/gaps/duplicates,
future availability, stale source data, zero volatility, actual receipt stamping,
access-denial no-fallback, year boundaries, unsupported weather/economic probabilities
and preservation of the old noon-convention quarantine. Synthetic fixture scores are
never presented as authentic research performance. No independent resolved outcome,
calibration result, profitability claim or qualified trading edge is established.
