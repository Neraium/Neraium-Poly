# Phase 57 historical basket replay

**35 markets scanned, 1.295 priceable market-hours across 26 markets, zero positive after-fee episodes, and $0.00 modeled P&L versus cash. No candidate earned a fresh forward test.** There were also zero gross episodes, attempts, partial baskets and unwind losses. Thus no single episode contributed dollars. Prices bound the observed sample before fees, while nine markets had zero priceable coverage and no market had more than 6.46 priceable minutes.

## Coverage and exclusions

- Nov 18, 03:07–04:07 UTC, experimental archive. First and last retained book receipts were 03:19:51–04:05:13. Reconstructed 1,894 observations against original full-book records and content hashes. Verified 300-second fee proofs, exact binary condition membership, decision-time settlement terms, minimum quantity, and exchange/receipt freshness. Thirty contracts passed identity and fee checks; 25 supplied 1.188 priceable market-hours. This partition tests buying both legs. The normalized archive does not establish split support, so reverse execution is excluded here. Pair-update exclusions included 1,049 stale/skewed observations, 67 without both legs, and 57 without a decision-time fee.
- Nov 18, 05:05:02–05:10:00 UTC, separate Phase 56 BTC Up/Down WebSocket tape. Reconstructed both sides from four full seeds and 1,908 price changes, preserving atomic packet availability and checking reported best quotes. The 1,911 reconstructed decision frames covered 0.083 priceable hours on one market. The same books sampled every five seconds yielded 60 polls and 0.082 priceable hours. Both views found zero discrepancies, including zero between polls. The capture has no exchange sequence proving completeness beyond received messages.
- Nov 18, 05:27:49–05:29:18 UTC, Phase 56 REST tape. Five markets, 90 batches, and 0.025 priceable market-hours, all from BTC Up/Down. The four threshold markets lacked compatible depth; some observations also failed freshness. Both directions were tested on the native standard CLOB binary condition. Conversion is unverified. The ledger records break-even conversion allowances only when there is positive after-fee edge.
- Nov 6, 21:24–23:04 UTC, prepared Phase 16 core, 900 frames. Each of its eight markets retained one outcome token. Excluded for missing complements. This search was bounded to the indexed Nov 18 archive hour and the two retained Phase 56 tapes; it does not estimate archive-wide frequency.

The scorecard retains all six same-date BTC threshold relationships, their actual terms, ordinary payoff vectors and the differential exception. Each was rejected because separate conditions lack a shared exceptional-adjudication guarantee. The admissible floor is zero. No cross-market fill was modeled.

## Forward decision

November WTI thresholds had the deepest family coverage at 0.303 market-hours, followed by December FOMC at 0.200 and the Taipei mayoral election at 0.193. All had zero gross discrepancies. BTC Up/Down was the best-covered individual market at 0.108 hours. That coverage supports a future measurement comparison if desired; no market showed an economic reason to advance.

## Reproduce

Run the four scripts in `.planning/evidence/phase57-historical/`: `check.py`, `replay.py`, `archive_scan.py` with repository `backend` on PYTHONPATH and its existing Python environment, then `rank.py`. The indexed archive reader is read-only and bounded to 6,000 catalog rows per kind. The replay uses Phase 56 depth and fee arithmetic, 500 USD paper capital, serial attempts, a 500 ms minimum between sequential leg observations, and an executable bid for an unwind. Fill times are subsequent captured observations, which can be coarser than the latency floor. Conversion costs are unresolved, so modeled attempt dollars are conditional on zero additional conversion charges. No attempt arrived in either capture or the archive partition.

Focused checks passed for a discrepancy missed by sampling, partial-fill unwind, liquidity reuse, stale input, exceptional payouts and insufficient depth. Phase 55 holdout files and the separate Phase 57 capture and publication timer were preserved. No orders were sent and neither running service was reconfigured.
