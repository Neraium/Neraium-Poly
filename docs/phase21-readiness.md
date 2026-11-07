# Phase 21 readiness

Verified executable source: `9dc521ed4e3029400d23da00a34652b99aeb8c77`.

**Outcomes:** all 24 crypto forecasts replayed exactly; three NFL forecasts/model/source/journal
chains preserved. No outcome conditions were met: verified completed-minute checks found no crypto
barrier hits, and no NFL game started. Crypto reference windows end November 8 at 05:00 UTC;
NFL starts are November 8 at 14:30/18:00 and November 10 at 01:15 UTC. These scheduled times are
not settlement timestamps. No settlement, label or probability was fabricated or retrospectively changed.

Fixed a real rule/scheduling defect: daily-low contracts can resolve YES immediately, so waiting for
day-end was insufficient. Added bounded reference checks to the existing managed archive: one asset
per five minutes, at most one native proof request; a hit alone never becomes a label. Native finality,
original event/token/rules, completed candles, causal forecast timing and raw provenance must agree.
Early NO remains prohibited. Restart recovery, retry fairness and 16 MiB evidence headroom are tested.
Actual post-deployment checks covered both assets/all 24 forecasts: zero hits, native attempts or outcomes.

**Calibration/SII:** qualified training/held-out remains **0/100 and 0/100**. Brier, log loss, calibration
and superiority are unavailable. Fixed outcome-dependent cohort selection: an earlier unresolved
forecast or training exposure cannot disappear in favor of a later resolved same-event forecast.
SII has zero paired groups and no qualified frozen challenger; it remains outside the new trading path.

**Discovery/capacity:** new collection admissions rank exact supported contracts by causal native
liquidity, near-term horizon and parent diversity. Broad/longer-term discovery, sticky capital protection,
12 priority slots, 800 tokens and three public requests remain bounded. Ranking and rejection evidence
are persisted. Latest ranking found three priority-ready markets/six books across two unreviewed crypto
parents, not three qualified opportunities. Other models remain withheld where evidence is insufficient.
For hypothetical $500/$1k/$10k/$100k/$1M capital, median displayed-liquidity principal was
$50/$100/$1,000/$2,726.19/$2,726.19; maximum $5,678.07. This uses 10% displayed participation, is
not aggregate deployable capital and establishes no positive after-cost EV, fill or proportional return.

**Trading:** zero new qualified opportunities, orders, fill events, positions or P/L change.
Experimental equity **$496.11522060**, cumulative realized simulated P/L **−$3.88477940**;
certified **$500**, P/L $0, admission blocked. Both stops remain clear as found, never reset.
No model/strategy/risk/capital changes, live financial execution, AWS changes or original deletion.

**Latency/operations:** native catalog profiling estimated 4,346/1,202 forced full-tree walks per rebuild.
Safe one-stat/no-follow traversal improved sampled walks about sixfold; cached accounting on
unchanged-row replay preserves every payload/hash/SQLite/manifest check and fresh free-floor checks.
Collector maintenance now runs in a shielded worker, awaited before admission and joined before
SQLite shutdown. Both affected services restarted under unchanged 1/0.5 CPU quotas; recovery to both
healthy took approximately 188 seconds. Full startup verification remains costly.

The 368.4-second observation had **14/19 available full operations snapshots** and
**19/19 healthy experimental ingestion samples**. Five collector status calls timed out. Separate health
and book probes took 0.07–0.43s; archive operations took 9.4s or exceeded 12s. This endpoint remains
an explicit blocker; a short soak is not proof of indefinite reliability. Final snapshot: **212 markets,
270 fresh books**. Both services active; archive usage **15.051/6.187 GiB**,
budgets **200/100 GiB**, floor **100 GiB**, free **459.75 GiB**. Short-soak retained growth
was **63.4/55.3 KiB/s**: conditional budget runway **35.4/20.6 days**,
not a representative multi-day guarantee. Retention unchanged; 2,818 baseline immutable files,
all three forecast journal prefixes and account histories verified; completed compressed segments restored exactly.

**Tests:** final CI **1,382 backend tests**, five browser tests, build/lint/audits passed:
[42409204210](https://github.com/Neraium/Neraium-Poly/actions/runs/42409204210).
Local comprehensive pass found one host-clock-dependent corrupt-gzip fixture after 1,381 passes;
explicit fixture mtime fixed its intended warm-age precondition without changing production policy
or corruption assertions; all 11 storage regressions then passed. No passing full suite was repeated.
Peak four agents including coordinator, three isolated native worktrees, one full local pytest process.

Phase 22: verify native/reference outcomes when conditions actually mature, review dependencies,
freeze genuine calibration/challenger artifacts, and isolate operations-view archive-lock latency
without weakening integrity. No statistically credible profitable edge or SII improvement is established.
