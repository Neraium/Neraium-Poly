# Phase 18 verification

Initial implementation source commit: `d08a82579accbbf9fc38820ee1ba39917d225f9f` (final repair below).
Baseline: `beca2ade40a29d116203b61c710d6d58a60c9f8e`.

Local complete backend run: **1,213 passed** across96 test files in two genuinely overlapping
pytest processes (one numerical thread each),589+624 tests. This includes historical replay,
archive integrity/crash/disk-full, storage guard, causality, immutability, calibration,
execution economics, risk, account isolation and recovery regression coverage. New tests
exercise frozen event separation, source/market binding, failed final capacity inspection,
ambiguous commit recovery, deduplication and delayed exact-window resolution acquisition.
Synthetic fixtures are engineering evidence only and never genuine strategy observations.

Ruff check and gitdiff whitespacechecks passed. Frontend TypeScript/Vitebuild passed;
Playwright **5 passed**, one configured worker. Tests run against their disposable server,
not production services. Narrow terminal fixtures cover30 x12,40 x24 and80 x40 rendering;
operations/edge prioritize account equity, stop state, live flags and unsupported metrics.
Python all-extras pinned dependency audit: no known vulnerabilities. npm audit:0 vulnerabilities.
The controlled scenario command completed; its synthetic fills/P&L are not market evidence.

GitHub source branch CI [42338115867](https://github.com/Neraium/Neraium-Poly/actions/runs/42338115867)
passed backend and dashboard checks. Only then was main fast-forwarded and pushed.
Main CI [42338220632](https://github.com/Neraium/Neraium-Poly/actions/runs/42338220632)
also passed. Documentation/evidence-only commits are ignored by the existing CI path filter;
the implementation SHA above identifies the initial executable source; final repaired source is listed below.

Actual development concurrency peaked at **4 agents**: integration coordinator plus3 writers
in3 distinct Citadel worktrees. Each writer had an explicit nonoverlapping file scope and
reported a commit; root reviewed/cherry-picked. Host measured32 logical CPUs and~236 GiB
available RAM before allocation. Host test concurrency used2 pytest worker processes, plus
one Playwright worker for the independent browser suite; numerical-library threads were
bounded to1 per pytest worker. This does not imply32 agents or 32 CPU workers. Existing collector1 CPU
and experimental 0.5 CPU quotas were preserved. Independent memory/source reviews found and
corrected failclosed durability, model-freeze and identity defects before source CI/deploy.

Operational account, original-evidence, raw/gzip/restore and journal-prefix checks are
separate from fixtures. See phase18-readiness and storage reports for measured live soak,
service restart durations, actual forecasts, archive growth and unresolved approval blockers.

## Final reviewed source repair

The final source is `bea5c235a94723f506c3c1a084d974828c305edd`, repairing official
WebSocket provenance and preserving known checkpoint history through an audited transition.
The full backend suite was rerun for this change: **1,217 passed** (593+624) with two
concurrent pytest jobs. New controls cover official WebSocket acceptance, preserved pending
forecasts/counters/original records, no duplicate transition, refused storage/model changes
and rejected unknown policies. Earlier1,213-test evidence is retained separately.

Repair branch CI [42339622961](https://github.com/Neraium/Neraium-Poly/actions/runs/42339622961)
and final main CI [42339722981](https://github.com/Neraium/Neraium-Poly/actions/runs/42339722981)
passed backend, browser, build, scenario and audits. Only experimental required a second
restart; collector retained its existing process and continuous WebSocket stream.
The first ten-minute soak is preserved; final delivery uses a separate post-repair soak.

The worker manifest records two `uv run pytest` launcher PIDs and overlapping job intervals.
This is two concurrent pytest worker jobs, with one numerical thread each; it is not a count
of every OS process spawned by runners or browsers. Playwright used one configured worker;
Chromium helper-process totals were not sampled. Peak AI-agent concurrency was four,
separate from the host's32logical CPUs.
