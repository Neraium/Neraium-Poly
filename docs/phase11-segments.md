# Phase 11 segment and historical evidence research

Current segment snapshot: **2026-11-06 04:41:00.317253 UTC** from the real
collector `/api/market-frame`. This is descriptive data-quality research, not a
strategy return, current guaranteed liquidity or a point-in-time training feature.

The captured universe contains 200 markets / 400 outcome tokens and 83 reported
event IDs. A bounded enrichment fetched **50 official Gamma event records**,
**13,923,029 response bytes**, at no more than four sequential GET requests per
second, with a 25 MiB byte ceiling and an 8 GiB free-disk floor. Every response
is preserved by SHA-256 and actual acquisition time. One earlier exploratory GET
confirmed the documented response shape; it is not included in the 50-record
archived acquisition. There are no wallet or authenticated order requests.

Category assignment requires official event-market membership, the fixed official
Gamma source URL, raw evidence hash and available timestamp, and a documented
mapping of explicit tags. Ambiguous and unavailable categories stay Unknown; no
question-text heuristic invents a category. Financial markets groups explicit
finance and crypto tags. Category enrichment was collected after the quote
snapshot and is **not** backdated into causal features.

| Segment | Markets | Tokens | Fresh valid quotes | Rules present | Static research-suitable tokens |
|---|---:|---:|---:|---:|---:|
| Financial markets | 34 | 68 | 40 | 68 | 40 |
| Politics | 80 | 160 | 136 | 36 | 24 |
| Sports | 35 | 70 | 32 | 66 | 16 |
| Economics | 6 | 12 | 6 | 12 | 6 |
| Unknown | 45 | 90 | 68 | 32 | 16 |

The exact rules counts are bound to the report artifact and may differ from
other snapshots. Static research suitability means active metadata, rules and
resolution source, scheduled end not within 120 seconds, fresh complete identity-
matched official bid/ask, and minimum lot notional <=$5. It does **not** mean
known fees, sufficient size participation, causal forecasting support, independent
context, risk admission or an executable profit. Unknown categories retain their
own quality counts without guessing membership. Weather and Entertainment have
no classified observations in this bounded enrichment; that is not evidence that
those categories are unavailable exchange-wide or cannot have an advantage.

Observed median spreads were $0.005 Financial markets, $0.002 Politics, $0.010
Sports, $0.010 Economics and $0.010 Unknown. Large observed total depth is not
queue position or depth survival through latency. Normalized snapshots omit
market volume, so market-volume metrics stay null; event volume is not duplicated
across tokens. Historical evidence sufficiency, resolution reliability and segment
profitability remain null. A single snapshot cannot establish regime robustness
or independent confidence intervals.

**Measured prioritization:** Financial markets has the most fresh, rule-complete,
small-lot research candidates in this bounded sample; Politics offers many fresh
quotes but substantial rules/eligibility gaps. This prioritizes further data
collection and investigation only. No market expansion or strategy activation
was performed.

## Historical integrity and new finalized-range search

The historical audit verifies the immutable 250-row dataset against its byte count,
SHA-256, report-manifest binding, and unchanged **100 training / 100 held-out**
requirements. All 47 existing finalized CTF proofs are replayed from their raw
RPC records, and Phase 10 follow-up archives are rechecked for checksums,
request-response identity and the read-only RPC method whitelist. Transaction
methods are rejected. No archived label availability is moved to an earlier time.

A new bounded search used **4 read-only RPC requests / 13,276 response bytes**
for the four remaining condition IDs over newly finalized blocks
**96,819,884–96,823,206**. It found **zero** additional ConditionResolution logs.
The unsuccessful search is retained as evidence and does not prove resolution
never happened. No creation/preparation, API lifecycle update, estimated end time
or market price was substituted for exact resolution.

Qualification remains **250 event groups, 51 API outcome groups, 47 corroborated
exact finalized settlement groups, zero qualifying training events and zero
qualifying held-out events**. Point-in-time availability, historical executable
depth, historical rule versions, independent external context and independent
event grouping remain missing/unqualified. No strategy self-certifies or promotes.

The versioned Phase 11 audit records each event's precise remaining deficiencies
and records its source dataset SHA:
`a4c2adfed62287a033a665a44ce33b4cbbfd05574bc46c4092b33277776f65f5`.
The original datasets, banks and databases remain unchanged.

## Interfaces, reproduction and terminal research view

- `run_segments(frame, *, captured_at=None, official_tags=None)` accepts a real
  public frame and optional current official enrichment; it returns the versioned
  ExperimentSpec, category measurements, individual evidence IDs and explicit null
  unsupported metrics.
- `acquire_event_metadata(frame, new_output, max_requests=50)` issues only bounded
  fixed-host public GETs, preserves raw evidence and refuses an existing output.
- `audit_historical(dataset_dir, *, chain_dir=None, acquisition_dirs=())` checks
  source integrity, proof and RPC evidence without any qualification authority.

The monitor accepts `view='research'` and consumes the runtime's read-only
`research` summary. At 34–45 columns and 24 rows it shows six strategy names and
actual scoped E/C/Q% counters from decision_trace, a distinct research baseline,
terminal calibration status, historical sufficiency, supported estimated edge,
confidence and a leading rejection/bottleneck. Missing/stale reports cannot
publish invented values or old edge as current. Root integrates CLI
`uv run neraium-poly monitor --view research` and the summary reader. The baseline
line describes the exploratory model target, not operational account performance.

Controlled regression fixtures verify tag provenance and identity, unknown and
ambiguous classifications, stale/missing/invalid books, static eligibility,
request and byte bounds, SHA binding, immutable historical integrity, forbidden
transaction methods, narrow terminal output, missing/stale metrics and live trace
scope. Focused verification: **62 passed**; scoped Ruff passed. Global Ruff in
this old worktree flags the parent's already-fixed shared-contract FURB162; no
unassigned shared file was modified here.

## Artifact locations and resource use

Committable summary: `.planning/evidence/phase11-segments/summary.json`. Raw
frame, official metadata, new chain responses and versioned full reports remain
under this worktree's ignored `data/phase11/`. The summary binds each full report
by SHA-256. Root may copy verified artifacts without changing old evidence.

One sequential public metadata acquisition process and one sequential read-only
RPC acquisition process were used; no claim of internal CPU parallelism. This
writing agent ran concurrently with the other isolated research agents. Local
focused tests used one pytest process. Existing services and accounts were never
written or restarted by this workstream.
