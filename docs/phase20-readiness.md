# Phase 20 readiness

Verified executable source: `ead418f` (forecasting integration `17aba1c`). Observation ended 2026-11-07T18:53:07.598045+00:00.

Implemented exact crypto outcome replay against the original forecast, full final Binance minute
window and finalized native CTF proof. Scores are recomputed; prices cannot supply outcome labels.
Added a predeclared, hash-bound SII A/B protocol in the existing managed archive: same events,
cutoffs, books and execution assumptions; frozen challenger and causal persistent-feature replay
required. Paired scoring selects events before labels, deduplicates dependency groups and reports
Brier/log-loss, reliability and conservative paired uncertainty. SII has no trading authority.

Fixed forecast-to-enrollment crash recovery, empty-pending baseline recovery and malformed-context
report failures. Added read-only `forecast-evaluate` and compact `monitor --view edge` SII status.
A missing frozen challenger remains withheld; no SII probability or performance is invented.

The first observation exposed full catalog scans for segment lookups. Added one derived covering
index without changing originals or integrity checks. Actual identical segment counts now use
`records_segment`: sampled queries fell from 0.418/0.090s to 0.000257/0.000040s. These are individual
query observations, not a controlled whole-system benchmark. Both archive owners were restarted;
resource quotas, stops, financial settings and the original probability/strategy hashes were preserved.

## Genuine research results

- **24 existing crypto forecasts**, two unreviewed parent events, plus **three preserved NFL forecasts**.
  No new forecasts during this phase; zero matured crypto forecasts or independently verified new
  outcomes. Crypto windows close November 8. Calibration, Brier/log-loss comparisons and confidence
  intervals remain unsupported; **qualified training/held-out: 0/100 and 0/100**.
- SII: zero qualified persistent findings and no frozen trained challenger; **zero paired event groups**.
  Incremental value is unmeasured. SII stays outside the new critical trading decision path.
- 12/24 crypto point estimates exceeded recorded asks, but all uncertainty bounds remain [0,1].
  Calibration, independent support, rules, fees and admission proofs are missing. Both throughput and
  conviction assessments remain unqualified. Missing account-context proof in a research proposal
  is not an actual latched stop or a risk-engine trade rejection.
- **Zero new qualified opportunities, orders, fills or positions; phase P/L $0.** Experimental equity
  **$496.11522060**, cumulative realized simulated P/L **$-3.88477940**; current drawdown
  **0.777%** from recorded $500 peak (maximum not reconstructed).
  Certified equity **$500.00**, P/L $0; admission blocked. Existing 13 orders/10 fill events preserved.
- Hypothetical $500/$1k/$10k/$100k/$1M capital: median displayed-liquidity principal
  $50/$100/$297.89/$297.89/$297.89 at 10% participation across the original 24 books; largest observed
  principal $2,767.68. Some books fail minimum wager requirements. This is neither edge-supported
  capacity nor aggregate deployable capital; related contracts cannot be summed. No capital increased.

Weather lacks a calibrated station/window distribution; economics lacks qualified release vintages
and a validated model; other domains retain interpretation/evidence gates. No unsupported new model
is claimed operational. Historical 250 groups/51 official/47 corroborated outcomes remain research-only:
historical executable depth, availability, rule versions and independent group review are missing.

## Operations and verification

Initial observation: **14/19 fully healthy**, four collector status timeouts and one experimental
feed timeout. Preserved in evidence. After the index fix: **18/19 fully healthy over 361.5s**;
one collector status timeout remains, while experimental ingestion stayed fresh. This is a bounded
observation, not proof of indefinite reliability. Full archive rebuilding still delays startup.

Final snapshot: **212 markets, 264 fresh books**, WebSocket connected, both services healthy.
Archive usage **14.612/5.968 GiB** against **200/100 GiB**;
free **460.63 GiB**, protected floor **100 GiB**. Short-soak net retained growth
**105.8/42.9 KiB/s**, conditional budget runway
**21.3/26.6 days**. Original retention remains unchanged.
Both services rotated three segments; compression advanced and lossless restoration was independently
verified. All **2,682 baseline immutable files**, journal prefixes and account histories passed preservation checks.

Local final backend 1,332 passed; five browser tests/build/lint/audits passed. The later index repair
passed 31 focused archive regressions. Final CI **1,333 backend tests**, dashboard/browser/build and
dependency/security checks passed: [42402411197](https://github.com/Neraium/Neraium-Poly/actions/runs/42402411197).
Three agents including coordinator, two isolated writing worktrees; one local final pytest process.
No original deletion, AWS change, risk increase, stop reset, automatic promotion or real-money trading.

Phase 21: verify genuinely matured native/reference outcomes; review parent dependencies; obtain
frozen event-disjoint calibration evidence before training an SII challenger. Profile remaining status
API stalls/full rebuild costs. Keep research scores separate from executable advantage and retain
100/100 certification gates. No credible independent profitable edge has been established.
