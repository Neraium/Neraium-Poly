# Phase 15 delivery and readiness

Observed 2026-11-06T21:04:33.231642+00:00. Source commit `8e1c68e`; baseline `3b41ee5`.

Safe archive recovery, bounded capacity reporting, independent domain evidence acquisition and continuous relationship research are implemented and operating. **No credible trading advantage is established. Experimental order admission remains stopped pending owner review. Current storage budgets cannot promise months of operation.**

## Actual operation

The two Neraium-Poly services alone restarted at 20:52 UTC. Archive startup verification took about 80 seconds before public ingestion resumed. The subsequent observation covered 600.50 seconds, 31 samples, 31 healthy. This is a bounded soak, not indefinite certification.

Markets monitored: 200; subscribed tokens: 400; fresh books at final sample: 296. WebSocket connected: True. Latest message: 2026-11-06T21:03:36.118027+00:00. Process-local message count: 492180; counters reset naturally with the new connection process, while persisted decision/history counters remain retained.

Observed public book examples (different markets; prices USD/share, depth shares):

| Market | Source timestamp UTC | Receipt timestamp UTC | Best bid × shares | Best ask × shares |
|---|---|---|---:|---:|
| 666660 | 2026-11-06T21:03:35.516000Z | 2026-11-06T21:03:35.835825Z | 0.85 × 6232.72 | 0.86 × 5946.5 |
| 666661 | 2026-11-06T21:03:35.901000Z | 2026-11-06T21:03:36.031977Z | 0.09 × 181.31 | 0.102 × 30.0 |

Exact token IDs and raw depth remain in `data/phase15/soak/frame-30.json`, SHA-256 `3e848fd5d1bd9a5795206c87999c9dfd82f0d4a97018c840861ba289a0d6e500`. These observations are not fills.

Endpoints: public Gamma `https://gamma-api.polymarket.com`, CLOB `https://clob.polymarket.com`, market stream `wss://ws-subscriptions-clob.polymarket.com/ws/market`. Archive records are sampled observations and research/audit events; they are not a complete exchange tick log.

| Account | Cash | Simulated P/L | Orders/fills/positions | Gate |
|---|---:|---:|---|---|
| Experimental paper | $500 | $0 | 0 / 0 / 0 | Original stop remains latched |
| Certified paper | $500 | $0 | 0 / 0 / 0 | Validation and owner approval blocked |

Filesystem capacity 1038993555456bytes (967.64GiB); available 513073233920bytes (477.84GiB). No AWS changes or additional resource charges.

## Archival lifecycle and capacity

Active SQLite segments remain append-only. Rotation closes/checkpoints before immutable manifest publication. Completed gzip copies undergo exact-byte verification. Independent cold proofs restore SQLite, run quick_check, verify every payload/identity/timestamp and match the global catalog. Maintenance performs at most one proof per service per 60 seconds. Derived caches have a 64 MiB bound and pinned readers; only reproducible cache/publication temporaries may be evicted.

Managed historical get/latest/replay and startup recovery now support verified cold-only representations for a future authorized retention batch. Production originals remain present. Corruption, interruption, disk-floor and ambiguous segment/catalog commits fail closed and are tested. Searchable catalogs and all provenance remain retained.

| Service | Usage/budget GiB | Observed growth KiB/s | Non-cache growth KiB/s | Final rolling horizon days | New sealed/gzip/proofs |
|---|---:|---:|---:|---:|
| collector | 6.499 / 64 | 195.61 | 110.64 | 3.27 | 3 / 4 / 7 |
| experimental | 1.944 / 16 | 116.82 | 46.34 | 1.41 | 4 / 4 / 10 |

Whole-window rates include bounded cache creation; non-cache rates subtract its measured net change. WAL allocation/checkpointing, rotation and variable traffic remain important. Rolling endpoint horizons use a different, shorter window. Neither rate is a multi-month prediction. Keep 64GiB/16GiB hard service-tree budgets and 64GiB filesystem reserves unchanged, above the global 8GiB minimum.75%/90% usage,7day/48hour horizons and soft tier saturation warn early; exhausted budget/floor denies further archival admission.

Soft tier plans(active/warm/cold/catalog-state/protected) are 0.5/16/32/7.5/8GiB collector and 0.25/4/6/3.75/2GiB experimental. All copies, journals, caches and metadata count against hard totals. The residual catalog_state category also includes prior protected archive-baseline backups; it is not a pure index-size measurement. Those backups remain protected from retention. Separate catalog-specific measurements are in historical-capacity.json.

At 20:45–20:46UTC the separate 64.87second sample observed 109,809.86B/s collector and 55,804.05B/s experimental retained growth, with catalogs 17,870.09/4,230.73B/s. These noisy short-window extrapolations implied 6.53/3.15days to budgets. Catalog growth alone can exceed current budgets over 90days; gzip/raw ratios about 0.265/0.334 cannot resolve that. No budget increase is justified from a short sample. Obtain 24hour and 7 day component measurements before choosing exact higher limits or a compacted catalog design. No off-host disaster-recovery archive is claimed.

## Exact retention proposal — no cleanup authorization

Proposed warm periods: collector 24hours, experimental 12hours. Current exact proposals list **zero eligible original files, zero bytes**. No original deletion function exists. Future eligibility requires a verified lossless compressed copy, complete manifest/catalog hashes, tested recovery, sufficient capacity, no active process references, permitted retention class and explicit owner authorization of the exact batch hash. A policy discussion is not exact-file deletion approval. Preserve legacy archives, baseline backups, accounts, forecasts, external evidence, catalogs, manifests, gzip and proofs. See phase15-retention.md and machine-readable service proposals.

Independent operational re-verification restored four real segments:35,045,376bytes and13,030records. 510 pre-existing immutable raw/gzip files matched their original hashes after restart; all forecast journal prefixes and complete hash chains verified. No original was deleted, truncated, replaced or moved.

## Multi-domain research and SII

The authentic 200-market frame at 20:27 UTC classified 146 other, 21 sports, 15 esports, 11 crypto,7 economics and 0 weather; conservative other labels expose metadata limitations rather than invented category coverage. Existing NFL models and two independent ternary research forecasts remain preserved, unresolved and unapproved for orders. Parent game groups remain unreviewed for formal certification.

New official NWS research acquisition retained155 future hourly provider precipitation probabilities, with exact source/retrieval hashes. They are not a mapped settlement-station temperature distribution or independently calibrated market forecasts. All 11 monitored crypto contracts require unsupported barrier/path/non-terminal semantics; Binance 1,000 closed candles do not repair that. All 7 economics contracts require settlement/vintage review and a validated model; an official FOMC calendar is context only. Politics, technology, science, geopolitics and other domains retain evidence contracts without invented numerical forecasts. No new independent market forecast was qualified. Source IDs/times/hashes and missingness are in phase15-domains.md.

The independent 8-minute SII replay captured 150 real books across 3 parent pairs: 75 evaluations, 30 warmup, 30insufficient joint variation, 15 observing relationship, 0 persistent findings. Maximum source age11.750061seconds. No reviewed cross-domain causal/logical link or executable opportunity was established. The new continuous service appends bounded source records/results/hashed checkpoints every 20 seconds; ambiguous writes reconcile idempotently before advancing. The statistical graph is bounded to 3 pairs and does not authorize trades or promote models.

At final soak: continuous SII 69 pair evaluations and 0 persistent findings. Cumulative since this study/checkpoint, not independent event samples.

Calibration and cost-adjusted superiority remain null: no authentic independent resolved held-out cohort is available. Certification still requires 100 independent training plus 100 held-out events; no thresholds changed.

## Historical qualification and strategy readiness

Verified all 3 canonical dataset files, source bundle,17 raw original references and settlement proof-source hashes. Funnel: 250 propositions/parent groups,51 API outcome groups,47 corroborated finalized groups,616 historical price rows,0actual historical depth rows,95 context rows,0verified predecision price-availability events,0reviewed independent groups,0training/0held-out events. All250lack historical rule-version, predecision availability, depth, independent grouping and qualified context;203 lack corroborated final settlement. Hash verification is not execution certification.

Strategy trace captured 2026-11-06T21:04:33.374231+00:00. Counters below are persisted epoch totals, not independent events; rejection categories overlap. Current net-edge, forecasting superiority and realized-advantage metrics remain null.

| Strategy | Markets / valid | Candidates | Qualified | Risk attempts/rejections | Submitted/fills |
|---|---:|---:|---:|---:|---:|
| cross_market_consistency | 296512 / 216865 | 0 | 0 | 0 / 0 | 0 / 0 |
| persistent_relationship | 296512 / 216865 | 16115 | 0 | 0 / 0 | 0 / 0 |
| liquidity_spread | 296512 / 216865 | 0 | 0 | 0 / 0 | 0 / 0 |
| event_driven | 296512 / 216865 | 0 | 0 | 0 / 0 | 0 / 0 |
| short_horizon | 296512 / 216865 | 185774 | 5 | 5 / 5 | 0 / 0 |
| calibrated_forecast | 296512 / 216865 | 0 | 0 | 0 / 0 | 0 / 0 |

Only short_horizon and persistent_relationship currently support experimental order admission. Both target an unvalidated60second executable bid mark, not an independent terminal outcome probability. Other strategies lack reviewed exhaustive multi-leg settlement/execution, queue/adverse-selection support, independent event context, or calibrated outcome evidence. Six remain registered; none has certified approval. Full rejection categories/counts and prerequisites are in strategy-readiness.json.

Two genuine earlier short_horizon signals (markets6722815 and6736347, ask$0.18, $2notional, conditional estimated edge$0.038/$0.03325per share) reached risk and were rejected solely kill_switch. They expired and must never be replayed. During the completed soak, three additional genuine short_horizon candidates for market 6736347 reached risk at 20:54:39.163427Z,20:54:47.862275Z and20:54:54.361254Z. Observed asks were$0.52/$0.50/$0.51, quantity 5 shares ($2.60/$2.50/$2.55), conditional estimated edges$0.1655/$0.1865/$0.176 per share, fee rate 0.05. All were rejected solely kill_switch, with no reservation or broker submission. These unvalidated estimates target a future bid mark and can be wrong during repricing. Lifetime attempts are 5; all expired and must not be replayed. No trades or profitable result is invented. Controlled execution-path fixtures verify risk/reservation/fill/restart and certified-account isolation; fixture results are not real market performance.

## Stop recovery and required owner action

Original stop audit seq 5249,2026-11-06T06:49:37.230323Z, contains only active:true. Storage auto-stop is strongly corroborated by surrounding ingestion and storage-budget evidence; actor/manual intent cannot be proven. Current storage cause has been remediated and both accounts remain intact. Future stops now atomically record bounded actor/reason/evidence hashes; malformed context cannot prevent activation or release a stop.

Technical recovery conditions pass: True; blockers: []. Assessment `09451a2fca2d30e3e628019cea944cf1d163cabed9efdaa74332b9c4d6d845bb` expires 2026-11-06T21:09:33.375712+00:00; fresh revalidation is mandatory before any future action. reset_authorized=false, automatic_reset_authority=false, certified_strategy_authority=false.

Approve one operator-reviewed reset of experimental-paper stop audit seq 5249 under assessment 09451a2fca2d30e3e628019cea944cf1d163cabed9efdaa74332b9c4d6d845bb, exclusively paper-only, with unchanged risk/strategy gates. Acknowledge that the original audit does not identify the actor. Do not replay expired signals.

Owner must also confirm no manual stop intention remains. A reset would allow only the two existing admitted experimental paths to evaluate future fresh signals under unchanged risk checks; it would not approve new models, clear certified approval or permit real-money trading. No reset occurred.

## Verification, services and actual concurrency

921 backend tests passed in2 concurrent jobs (launchers3185012/3185013, one numerical thread each);5 Playwright tests passed using1 browser worker. Ruff, TypeScript/Vite build, controlled scenario, frozen Python production/dev/research audits and npm audit passed. GitHub run42291947924 passed backend and dashboard for source8e1c68e: https://github.com/Neraium/Neraium-Poly/actions/runs/42291947924 . Final documentation/evidence commits do not change tested application source. Starlette test-client deprecation warning remains nonfatal.

Maximum4 agents including coordinator, with3 separate native Citadel worktrees. Two real ProcessPool workers3183147/3183150 ran historical/capacity analysis concurrently; measured overlap0.0416seconds because historical hashing finished quickly, not2 saturated CPUs. Their CPU times were0.0416/0.0675seconds. One8minute network sampler overlapped development; tests ran2jobs concurrently; browser used1worker. These are tracked job/worker counts, not an exhaustive count of short-lived fault-injection or Chromium child processes. No claim that all32 hostCPUs were used. Original host inspection showed about236GiB available RAM and load0.76; service quotas remain1CPU/1GiB collector and0.5CPU/768MiB experimental.

Services at final inspection:

- neraium-poly-paper: active, PID3185204, restarts0, memory412844032bytes.
- neraium-poly-experimental: active, PID3185205, restarts0, memory351711232bytes.
- docker: active, PID1349, restarts0, memory429527040bytes.
- postgresql@16-main: active, PID1026336, restarts0, memory33312768bytes.

Docker PID1349 and PostgreSQL PID1026336 remain running from their pre-existing start dates. No unrelated service or project was modified. PAPER_TRADING=true; LIVE_TRADING_ENABLED=false in both actual service processes. Histories and journals remain isolated. The original unrelated/untracked EBS inspection evidence remains untouched.

Final native forecast inventory:233 market-baseline records spanning34 dependency groups,2 independent ternary sports forecasts for2 unreviewedgamegroups,0 resolved forecasts,0 new non-sports forecast records. Repeated forecasts do not create independent validation events.

## Phase 16 recommendations

1. Owner-review the stop assessment; revalidate immediately before any separately authorized operator reset. Do not resubmit expired signals.
2. Accumulate24hour/7day component growth and operational evidence; review24h/12h warm policy and later exact-file batches. Address catalog/index growth before any multi-month capacity claim. Keep all originals until explicit authorization.
3. Await and independently verify prospective NFL outcomes; build exact station/window weather mappings and calibrated distributions, settlement-compatible crypto path models, and first-release economic vintages.
4. Preserve stronger structured category metadata, then justify category-balanced coverage with measured freshness and liquidity. Do not inflate market counts.
5. Add versioned graph retirement/selection and independently reviewed cross-domain drivers; test forecast improvement separately from executable trading advantage.

Detailed evidence: .planning/evidence/phase15/; raw public observations/source payloads and bounded research captures: ignored data/phase15/. No secrets, databases or raw historical evidence are committed.
