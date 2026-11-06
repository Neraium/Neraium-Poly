# Phase14 readiness and capacity blocker

Software baseline: `f630ac1` (with original-admission recovery hardening).
Phase14 is **blocked on persistent capacity and qualified forecasting evidence**;
it is not a healthy live multi-domain trading deployment. No profitable edge or
new qualified non-sports forecast was established.

## Observed operations

At2026-11-06 09:52:20UTC, the collector and experimental services were active,
PIDs2981665 and3136716 respectively (the committed service evidence contains the
authoritative measured PIDs). The collector last ingested at07:32:49.507749UTC;
WebSocket was disconnected and fresh books were0. Its200markets/400tokens are
cached. Cumulative messages11,472,308 do not imply current ingestion.
Collector error: `archive_or_disk_budget_exhausted`. Experimental storage exceeds
its512MiB cap; the kill switch remains latched. No stop, archive cap or floor was
cleared to create activity.

Both accounts retain$500cash, simulated P/L$0, zero orders/fills/positions.
Account-table hashes and all117Phase12 journal records were unchanged across the
scoped experimental-service restart. Its39market-baseline forecasts remain distinct
from two independent NFL ternary forecasts, both pending with0resolved. The sports
journal's two-record head hash is unchanged. The preserved source dataset has842
publisher game records; these are not842independently verified certification events.
Both process environments have`PAPER_TRADING=true`, `LIVE_TRADING_ENABLED=false`.
No wallet, order submission, new AWS resource or paid capacity was introduced.

## Storage audit

One500GiB root EBS attachment was verified, volume`vol-03c2fd4e26ccd63d3` on
instance`i-0f7f235764cdca32b`. No secondary mounted persistent location was found.
DescribeVolumes was IAM-denied, so unattached account resources remain unknown.
RAM-backed`/dev/shm` is not an approved archive destination.

Four verified disposable cache/build directories reclaimed **452,878,336bytes**
(~432MiB). Cleanup inventory, inactive-reference checks and service/account
verification are recorded in [the storage report](phase14-storage.md). No valuable
archives, database, repository, evidence or other-project files were removed,
compressed or relocated. At09:52:20UTC root had **2,780,045,312bytes free**
(~2.59GiB); other workloads consumed space after cleanup. Neither8GiB safety floor
nor20GiB target was achieved. Durable collection remains blocked. No additional
large, conclusively disposable allocation was identified within authorized scope.

## Discovery and category evidence

Fresh bounded Gamma metadata at09:00:18UTC returned339eligible candidates, selecting
200across categories with15GETs at<=2/s,3,251,766response bytes.169selected IDs were
absent from the old200. These are metadata candidates, not subscribed fresh books.
No WebSocket expansion was performed while storage is exhausted.

| Category | Cached monitored projection | Fresh metadata selection |
|---|---:|---:|
|Weather|1|21|
|Crypto|34|21|
|Finance|0|20|
|Economics|9|18|
|Politics|6|20|
|Sports|6|20|
|Esports|13|19|
|Technology|0|1|
|Science|0|0|
|Geopolitics|0|20|
|Entertainment|0|20|
|Other/review|131|20|

Legacy metadata dropped structured tags, making its classification provisional.
Science was queried but no sampled contract classified unambiguously; this is not
evidence of no science markets globally. New metadata is stratified, not a random
sample or exchange-wide census. Gamma liquidity is not executable order-book depth.

## Domain implementation versus evidence

| Domain | Authentic evidence acquired | Forecast status |
|---|---|---|
|Weather|NOAA/AWC RKSI METAR:42rows,36in exact local day, latest08:30UTC; market6667068/event1312086|Withheld: partial observations, corrections and calibrated predictive distribution unresolved|
|Crypto|Official Binance public1000completed BTCUSDT minute candles,08:40:54UTC retrieval|Withheld: exact noon candle convention ambiguous; volatility research is uncalibrated|
|Economics|Official Federal Reserve FOMC calendar,08:40:54UTC retrieval|Context only; no qualified economic vintages/consensus or numerical model|
|Finance|Exact-reference contract interpreter and uncertainty research|Unsupported references/time conventions withhold; no general independent finance model|
|Politics/technology/science/geopolitics/culture|Evidence and interpretation contracts|Human-review/research interfaces; no news-to-probability fallback|
|Sports|Existing NFL pipeline and original two ternary forecasts retained|No new sports provider enabled; no operational order authority|

Source bytes were captured in bounded volatile RAM because persistent capacity
was unsafe. Hashes and bounded summaries are committed, but raw captures are not a
durable, execution-certified dataset. Real adapter ingestion was verified by source
replay; continuous durable domain-source ingestion remains blocked. Numerical
weather forecasting and generic economic forecasting are not implemented claims.
Source/licensing/rate-limit details and exact rules are in the separate adapter reports.

New domain forecasts0; verified domain outcomes0; reviewed cross-domain relationships0;
new opportunities/orders/fills0. No model was enabled for experimental orders or
certified operation. All Brier/log-loss/calibration/skill/profitability results remain
null for the unsupported new-domain cohort.

## Historical qualification

The existing47corroborated settlement groups remain preserved. No new execution-
certified event was established: independent training0/100, held-out0/100. Exact
historical availability vintages, independently reviewed event grouping, external
result corroboration, executable historical depth and held-out calibration remain
missing. Current candles and partial-day weather observations do not fill those
gaps. Discovery/mapping/outcome/price/depth/evidence stages are explicitly distinct;
fresh339metadata candidates cannot be added to resolved historical group counts.

The preserved canonical dataset's file hashes were reverified. Its funnel is250
propositions/250proposed parent groups,51API outcome groups,47corroborated groups,
616price rows,0historical book rows,95context rows,0resolved events with verified
predecision price availability and0reviewed independent events. All250lack verified
historical rule versions, predecision availability, executable depth, independent
group review and qualified external context;203lack corroborated final settlement.
These are reverified existing artifacts, not new historical acquisition. See
`.planning/evidence/phase14/historical-funnel.json`.

## Verification and actual concurrency

Final source:797backend tests passed (410+387), with two overlapping pytest parent
processes; one existing nested research test additionally spawns two bounded CPU
workers. Ruff passed. Dashboard build and5Playwright browser tests passed with one
browser worker. Runtime dependency audit and npm audit found no known vulnerabilities.
The deterministic scenario passed using controlled fixtures, not real performance.
Temporal, replay, risk, isolation, immutability, source mapping, recovery, narrow
terminal and live-prohibition tests are included in the backend suite.

Three simultaneous writing agents plus coordinator used isolated native Citadel
worktrees. Two independent real-data analysis workers actually overlapped, each
with one numerical thread and~80MiB peak RSS. A second sequential two-worker replay
produced byte-identical reports: four launches total, peak two analysis workers.
The32logical CPUs were not treated as32available agents. Resource inspection showed
ample RAM and low CPU load; filesystem capacity was the binding limit.

GitHub Actions source validation links and exact results are recorded in
`.planning/evidence/phase14/final-tests/ci.json`. Source commits include foundations
`2ae8136`, adapters/discovery/storage/relationships through`bcb8c22`, integrated
journal/runtime/monitor`dd85022`, and degraded diagnostic isolation`df9141f`.
Recovery invariant hardening is`f630ac1`.

Both backend and dashboard jobs passed on final source`f630ac1` in
[GitHub Actions run42198626025](https://github.com/Neraium/Neraium-Poly/actions/runs/42198626025).
The dashboard job spent most of its runtime installing Chromium, then completed
successfully. This does not remove the production storage/evidence blockers.

Defects repaired: destination-filesystem budget checking for missing output parents;
same-event evaluation deduplication; original contract/evidence/model binding;
outcome proof/reviewer recovery; preservation of failed relationship checkpoints;
and diagnostic cached metadata visibility without execution inputs.

The scheduled outcome verifier interface currently has no approved domain sources.
Before enabling it at scale, its full stored-outcome replay should receive a
bounded cursor/batch policy. No such sources or new-domain outcomes are active.

## Phase15 recommendations

1. Establish an owner-approved persistent destination or separately approve paid
   capacity. Verify source integrity, complete copied hashes and destination free
   capacity before any lossless archival migration. Preserve originals until
   explicit deletion authorization; do not use RAM as durable storage.
2. Design archive rotation/restart reconciliation for both independent size caps.
   Do not clear kill switches or raise caps solely to resume trading counters.
3. Review crypto settlement convention or obtain station-matched weather ensembles
   with genuine forecast vintages and calibration outcomes. Register independent
   domain result verifiers and collect prospective evidence before model comparison.
4. Review actual cross-domain relationship definitions and settlement dependencies.
   Keep causal hypotheses, logical constraints and executable opportunities separate.
5. Re-run ingestion, source durability and health checks after storage recovery;
   require explicit experimental admission and independent certified approval.
