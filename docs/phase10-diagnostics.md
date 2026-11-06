# Phase 10 bounded real-data diagnostics

Observed snapshot: **2026-11-06 04:17:06 UTC**. These are historical observations, not promises about present liquidity or service health. No account, service, market archive, strategy threshold or approval gate was changed by this workstream.

`neraium_poly.research.phase10_diagnostics` reads an immutable captured public frame, the experimental account's read-only checkpoint/fee cache, a fixed SQLite high-water cycle window, and the independently archived settlement evidence. It never creates an opportunity, risk approval, order, fill or strategy certification.

## Reproduce

Capture `frame.json` from the loopback public service `/api/market-frame`, `experimental.json` from the experimental service `/api/state`, and `strategy_engine.json`, `observed_fees.json`, `selected_tokens.json` from the experimental `service.sqlite` opened using `mode=ro`. Capture checkpoint/cache first and account time last; replay uses that captured time. These are separate read-only observations rather than an atomic service snapshot. Preserve the input hashes.

```bash
PYTHONPATH=backend uv run python -m neraium_poly.research.phase10_diagnostics \
  --inputs data/phase10 \
  --database /home/ubuntu/Neraium-Poly/data/experimental-paper/events.sqlite \
  --dataset /home/ubuntu/Neraium-Poly/data/phase9qualification/qualified-main-v1 \
  --chain /home/ubuntu/Neraium-Poly/data/phase9qualification/chain \
  --output data/phase10/new-audit-version --high-water 61171
```

Use a new output directory. Collection bounds are 250 cycles by default, at most 2,000 through the library interface. Exactly two spawned CPU workers perform quality/cycle analysis and historical integrity replay independently; they do not submit transactions. The report records PIDs, execution intervals, observed overlap, resource-tracker PID, input hashes and exact source row IDs. Numerical threads are limited to one per worker. Regression tests use synthetic fixtures explicitly marked as such.

The actual v3 run used CPU worker PIDs **3011950** and **3011954** with overlapping execution intervals, coordinator PID recorded in the report, resource tracker **3011949**, and **four job processes** including coordinator/control processes. This is two CPU workers, not four. Tests ran in one pytest process.

## Live-universe quality

| Measure, token scope | Source | Selected experimental |
| --- | ---: | ---: |
| Tokens | 400 | 64 |
| Distinct source markets | 200 | 33 account-reported markets |
| Active metadata status | 400 | 64 |
| Rules + resolution source present | 226 | 64 |
| Active, rules present, end > now + 120s (or absent) | 148 | 64 |
| End time already passed | 110 | 0 |
| Source timestamp within 15 seconds | 309 | 56 |
| Receipt timestamp within 15 seconds | 325 | 58 |
| Healthy book, including spread <= $0.05 | 272 | 54 |
| Known fresh local fee observation | 59 | 59 |
| Matured local forecast context | 57 | 57 |
| Same-event YES peer on a distinct market | 124 | 25 |
| Static operational eligibility | 38 | 38 |

Static eligibility includes metadata, healthy official-source identity-matched book, fresh fee evidence, minimum lot <= $5, and best-ask liquidity at 10% participation sufficient for at least max($2, minimum-lot notional). It does not imply forecast support, independently qualified relationship evidence, risk approval or a fill. Current normalized frames omit volume, so volume statistics remain null. The source frame's empty fee map does not mean zero exchange fees; the experimental collector maintains a separate observed cache. Outside-cache fees remain unknown.

Observed executable quote examples:

| Market ID | Source timestamp UTC | Receipt timestamp UTC | Bid | Ask |
| --- | --- | --- | ---: | ---: |
| 3215008, token ending 15890 | 04:17:06.275000 | 04:17:06.469138 | .640 | .650 |
| 3215008, token ending 48687 | 04:17:06.275000 | 04:17:06.469138 | .350 | .360 |
| 3215007, token ending 08601 | 04:17:06.698000 | 04:17:06.737863 | .350 | .360 |

Full token IDs, book IDs, source/receipt times, modeled lower values and depth appear in the audit artifact. These are observed quotes, not simulated executions. Receipt freshness alone overstates source freshness. All tokens marked active by metadata are not necessarily within their scheduled trading period.

Coverage was left unchanged. Of the 336 unselected tokens, 84 pass the metadata predicate and 218 have healthy books, but they have no matured local contexts and no locally captured fresh fee evidence in this snapshot. Additional discovery alone cannot establish a positive edge. Same-event peer counts describe graph candidates; they do not establish exhaustive outcomes, independence or logical arbitrage.

## Actual decision window

Fixed high-water **61171**, **250 cycles**, **03:53:19.700369–04:17:06.283724 UTC**:

- **72,510 new deduplicated signal records; zero qualified opportunities.** These are not 72,510 independent markets/events or all strategy checks.
- 19,800 cost-edge rejections; 12,085 missing persistent relationship-evidence rejections.
- 5,406 stale-book, 3,546 missing-book, 636 missing-liquidity, 6,180 unknown-fee, 1,486 insufficient-history and 120 insufficient-matured-error rejections.
- Each of the four guarded candidate families has 12,085 occurrences of its principal evidence/capability rejection. Both the spread and consistency families also produce a second reason per rejection. Reasons are nonexclusive.
- Each of the two executable candidates has 250 stored representative samples, 246 numeric: sampled net edge minimum **−.0936**, maximum **−.0433**, mean **−.06230996** dollars/share. The stored representative selection is biased; it cannot estimate the full valuation distribution or opportunity frequency.

The captured service's legacy cumulative counter is **51,745 emitted deduplicated signals per strategy**, all six registered/enabled. This scope differs from per-cycle evaluations and current relationship findings. Zero qualified opportunities arise before portfolio risk/order admission in this window; the evidence does not show risk rejecting qualified trades. Account capture: cash/equity $500, P/L $0, attempts/submissions/fills/positions zero. Risk-path verification belongs to the separate integration workstream.

Existing conservative valuation remains `lower*(1-fee) - ask*(1+fee) - .02`, threshold `.03`. `lower` is an unvalidated horizon bid-mark envelope, not a calibrated terminal probability. No cost threshold was reduced. Four registered approaches remain limited by payoff review/multi-leg execution, two-sided inventory/queue modeling, external event context, or calibrated independent-outcome evidence. Missing SII evidence is distinct from a statistical relationship change and from proof of mispricing.

False-positive rate, executable strategy return, Brier score and log loss remain null where outcomes or qualified strategies are unavailable. A zero trade count is not evidence of profitability or zero false positives.

## Historical follow-up

Source dataset: 250 groups, 51 API-verified outcome groups, 47 independently replayed exact finalized CTF resolution groups. Raw manifest hashes and every RPC response binding were rechecked by the second CPU worker. Deficiency counts:

| Deficiency | Groups |
| --- | ---: |
| Historical executable depth unqualified | 250 |
| Predecision availability unverified | 250 |
| Historical rule version unverified | 250 |
| Independent external context unqualified | 250 |
| Cross-event dependency review required | 250 |
| Official outcome unavailable | 199 |
| Exact finalized settlement unavailable | 203 |
| Pre-resolution history absent | 200 |

Remaining API-labelled groups: **1306224, 1306300, 1316595, 1316597**. New follow-up used **14 read-only RPC requests**, **510,394 response bytes**, well below 100 requests/50 MiB; the existing >=8 GiB disk floor was enforced. It yielded **zero additional resolution proofs**.

The two sports locator receipts contain CTF **ConditionPreparation**, at blocks 96751517/96751525, rather than ConditionResolution. Weather locator receipts contain no condition-indexed CTF resolution event. The preceding 20,001-block bounded scan (96783040–96803040) and succeeding 5,001-block scan (96814883–96819883) returned no requested resolution logs. A later range exceeded the observed finalized height and the node rejected it; the unsuccessful response remains archived. A failed search is not proof that settlement never occurred. No preparation timestamp, API `closed_at`, or lifecycle `last_update_timestamp` was substituted for an exact settlement time.

`data/phase10/historical-audit-v1` preserves the source 250-row dataset unchanged with a new audit manifest and the three new acquisition manifest hashes. Events SHA-256: `a4c2adfed62287a033a665a44ce33b4cbbfd05574bc46c4092b33277776f65f5`. All acquisition availability stays collected-now. **0/100 training events and 0/100 held-out events qualify**; all activation thresholds and owner approval gates remain unchanged. Publisher L2 archives remain unlinked to independently reviewed execution/outcome context and are not promoted to execution-certified evidence.

## Verification and artifacts

- 52 focused tests passed: diagnostics, experimental strategies, Phase 9 qualification and quote archive.
- Scoped Ruff checks passed. Full integration/backend/browser/security validation is coordinated separately.
- Committable summary: `.planning/evidence/phase10/diagnostics-summary.json`.
- Full captured inputs, replay output, dataset and raw RPC archives remain in this worktree's ignored `data/phase10/`; no raw historical archive, database or account file is committed.
- Full v3 report SHA-256: `3164620470269379101f8ef71dae6f1bcaf3ab39f2d901aa74f03718d80098d9`.
