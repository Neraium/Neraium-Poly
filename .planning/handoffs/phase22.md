# Phase 22 handoff

Checkout: /home/ubuntu/Neraium-Poly; branch main; baseline 4256b96; source delivery 1c8332d987d4b833ec7dea8d48434bd6b14d4e8b.

Archive latency: strict status held the shared archive lock through filesystem measurement; recovery/cold verification and append contend on that lock. SQL profiling did not identify query latency as the bottleneck. Operations now read an explicitly historical, timestamped snapshot under a separate lock, with fresh filesystem-floor and fault overlays. Stale/future/missing samples cannot report healthy or grant admission. Strict write admission, integrity verification and recovery remain unchanged. Busy experimental history counters report unavailable. Monitor labels sample age.

Before: Phase 21 observed 9–12 seconds/timeouts; current Phase 22 three-request warm sample 0.135–3.497 seconds. After: 19 collector requests over 360.5 seconds, median 0.01888 seconds, maximum 1.07846 seconds; experimental median 0.50499 seconds, maximum 1.98617 seconds. No timeout. This is bounded live evidence, not a tail-latency or indefinite-operation guarantee. Maximum archive sample ages: collector 30.07 seconds, experimental 5.51 seconds; expiration threshold 60 seconds.

All 19 live samples healthy and paper-only. 212 markets, 290 fresh books at final sample. Collector rotated/compressed two segments; experimental three. Both services active, no automatic restart, unchanged CPU and memory quotas. Latest sealed gzip restored bytes match original/catalog SHA-256 for both services. 2,888 preexisting immutable source/copy files preserved and hash-verified; all three forecast-journal chains/prefixes and both account histories verified. No originals removed.

24 crypto forecasts across two parent events plus three NFL forecasts across three games remain pending. Crypto windows end 2026-11-08T05:00Z; latest reference checks did not meet early-resolution conditions. NFL starts are November 8/10. Native source/model replay passed; no labels manufactured. Qualified training/held-out events remain 0/100 and 0/100. Calibration, Brier/log loss and SII incremental value remain unavailable: no verified labels, reviewed independent cohorts or frozen qualified SII challenger/pairs. Existing near-term selection and outcome scheduler preserved; no new forecasting framework or strategy authority.

Zero new qualified experimental opportunities, orders, fills, positions or P/L during Phase 22. Cumulative experimental cash/equity $496.11522059829053, realized P/L -$3.8847794017094013, 13 orders and 10 fill events; certified $500, P/L $0. Stops unchanged (false as found), certified admission blocked. No stop reset, risk change, capital increase, AWS change or real-money path enabled.

Four authentic book capacity scenarios at 20:31Z: hypothetical capitals $500/$1k/$10k/$100k/$1m yield median displayed-depth participation $50/$100/$1,000/$4,915.63/$4,915.63. These are nonadditive 10%-participation entry-liquidity estimates, not qualified edge, fills or profitable deployable capital.

Storage final: collector 15.292 GiB/200 GiB; experimental 6.312 GiB/100 GiB; filesystem 457.770 GiB free, protected reserve 100 GiB. Retained growth 100.54/57.94 KiB/s measured using archive measurement timestamps; conditional budget runway 22.30/19.62 days. Retain-all-originals remains finite; deletion requires separate owner approval. All cold verification errors null. No spending or retention changes.

Verification: 1,402 backend tests passed (one warning), focused 29 tests, five browser tests, frontend build, Ruff and both dependency audits passed. GitHub run 42412970444 passed backend/dashboard on the exact source commit. Three agents including coordinator, two isolated native worktrees; final three local jobs, one pytest process, numerical threads bounded to one. Read-only final review allowed integration/deployment.

Phase 23: collect authoritative settlements as events mature; explicitly review parent dependency groups before calibration; accumulate chronological event-disjoint labels; preregister a frozen SII challenger only when qualified features exist. Continue measuring operations tail latency and archive growth. Retention approval is still required for any original removal. No evidence of independently superior forecasting or positive executable edge.

Evidence: .planning/evidence/phase22 and .planning/evidence/phase22-evidence; raw bounded observation and manifests under data/phase22. Do not commit raw databases or local credentials.
