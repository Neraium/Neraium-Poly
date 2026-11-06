# Weather research adapter

This is an operationally tested **public observation research adapter**, not an
independent probability forecasting model. It maps one audited real contract and
retrieves real NOAA/NWS Aviation Weather Center METAR observations. No weather
probability, settled outcome, trading opportunity or performance is invented.

## Supported contract and exact mapping

The cached Phase14 market frame contains Polymarket market **6667068**, parent
**1312086**: “Will the highest temperature in Seoul (Incheon) be 12°C on November 6?”
Its full settlement text is bound to SHA256
`ee971bac629c2bcdd0f492014b5bf6d3908357c3739f0a8ac3314bab91924051`.
Unknown rule versions, stations, questions, outcomes, sources and periods reject.
The classifier must not treat a keyword match as an approved weather mapping.

Exact configured semantics:

- Station **RKSI**, Incheon Intl Airport; AWC station-info response confirms
  Seoul/Incheon Intl, KR, latitude37.469/longitude126.451. Timezone **Asia/Seoul**.
- Variable: maximum routine METAR temperature over **2026-11-06 local time**,
  equivalent to **2026-11-05 15:00 UTC through 2026-11-06 15:00 UTC**, end-exclusive.
- Units: Celsius. This exact 12°C bin means an unrounded maximum in **[11.5,12.5)**.
- An exact eight-digit `T` temperature/dewpoint remark supplies tenths. Otherwise
  the original METAR body supplies whole-degree temperature. JSON's derived
  `temp` field is not substituted for the governing raw text.
- Rounding is nearest whole degree with exact halves toward positive infinity;
  **−8.5→−8**, rather than a negative-away-from-zero rounding shortcut.
- Reports beginning `SPECI` are excluded. Unlabeled and off-hour routine reports
  are eligible if their station and source observation timestamp agree.
- Original correction/fallback/error-review rules remain governing. Conflicting
  same-time revisions quarantine; no arbitrary selection supplies a final result.

The market's UTC `end_time` metadata is12:00UTC, which is **not** the station-local
observation-day end15:00UTC. Both are retained and never silently equated. Mapping
compatibility concerns contract interpretation; the cached frame does not prove
that its market prices or trading status are currently fresh or executable.

## Source access, provenance and bounds

The [official AWC data API](https://aviationweather.gov/data/api/) explicitly
supports machine-to-machine queries and worldwide METARs. It documents limited
request frequency, custom user agents, a100requests/minute cap and typically a
400-entry response maximum. The adapter sends one bounded HTTPS GET per call,
with custom User-Agent, no credentials, redirects or order endpoint. Response
limits are512KiB and400rows. A429/5xx fails without a tight retry loop; production
callers must cache and schedule polling conservatively, such as at least five
minutes between calls for the same station. Most METARs are not subsecond products.

[NOAA/NWS usage guidance](https://www.weather.gov/disclaimer) permits lawful use
of government material with attribution and without implying endorsement. Its
third-party-data caveat is retained: this adapter does not assert blanket
commercial redistribution rights over every international originating report.
The research capture uses the official public API and preserves provider/raw
provenance; commercial redistribution needs its own rights review.

`DomainEvidence.content_sha256` hashes the canonical evidence payload. That payload
also retains the exact raw response and a separate `raw_sha256`. Replaying bytes
must reproduce the normalized rows. Observation timestamp, provider-receipt time,
actual retrieval and earliest verified availability remain separate. Only actual
retrieval establishes availability for this research; old METAR dates are not
backdated into training evidence. Station, raw timestamp, future receipt/data,
duplicates, conflicting corrections and local-day mismatches are checked.

## Authentic observed capture

The actual adapter request at **2026-11-06T08:39:34.083581UTC** returned **42 rows**
(**17,491 bytes**). **36** routine reports matched the exact station-local day;
six belonged outside it. Latest source observation was **08:30UTC**, with provider
receipt **08:34:30.931UTC**. The highest as-published included observation was
**13.0°C**, beginning with the00:00local report. This is an observed partial-day
maximum, **not** a final verified market outcome or a probability.

Raw response SHA256:
`adae2726d0f15ccf0e3ab6d3105f5f2c785959d5c2b3850dc6c1424cb9007c84`.
Canonical evidence payload SHA256:
`3addffaa7f762f49ba63e5b50e0369d0eba11a3e94b5cf7abeb9b672ce413309`.

At acquisition, root disk was below the existing8GiB safety floor. The full raw
capture therefore remained in bounded **temporary RAM-backed** storage:
`/dev/shm/neraium-poly-phase14/weather/actual-adapter-evidence.json`.
It is not a durable journal or restart-safe evidence archive. The committed small
summary records that limitation. No root storage floor was changed or bypassed.
After approved capacity recovery, the coordinator may preserve and revalidate the
same bytes in durable bounded research storage before any ledger use.

## Probability and settlement status

`forecast_weather` always withholds numerical probabilities in this implementation.
Official METAR observations are independent inputs, but a partial observed day is
not a calibrated predictive distribution for the remaining daily maximum. A
current maximum above a proposed bin is not promoted to probability zero because
correction, fallback and error-review provisions remain unresolved.

NWS's [forecast API](https://www.weather.gov/documentation/services-web-API)
provides forecast products, but US gridpoint forecasts are not station-matched
RKSI probabilities. No licensed/calibrated RKSI ensemble distribution, training
error vintages, held-out calibration or verified independent outcomes have been
qualified. A deterministic temperature or TAF is not converted to probability by
adding an unsupported Gaussian error. Weather probabilities/forecasts recorded:
**zero**. Brier/log-loss/calibration/market superiority/trading metrics: **null**.

Other variables—rainfall, snowfall, wind, hurricanes—and other stations are explicit
unsupported mappings until their exact sources, units, periods, uncertainty and
settlement rules are reviewed. No domain-wide forecasting capability is claimed.

## Interfaces and controlled tests

- `map_weather(market, now=...) -> DomainContract`.
- `await collect_weather(contract, client=None, clock=None) -> tuple[DomainEvidence,...]`.
- `forecast_weather(contract, evidence, cutoff=...) -> dict` with qualification
  reasons, observed row count and `probability=None`.
- `WeatherObservationModel` implements the shared domain-model interface and
  advertises only `metar_daily_high_celsius_bin`.

Controlled tests cover exact mapping, mismatched rules/station/window, timestamp
leakage, raw precision, negative half rounding, off-hour/unlabeled routine reports,
SPECI exclusion, corrections, bounded responses, unavailable/rate-limited/redirected
sources, raw integrity, spoofed origins, original mapping replay and repeated
observations. Their values are fixtures and never counted as real research rows.
