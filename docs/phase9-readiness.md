# Phase 9 experimental paper research

The certified and experimental accounts are separate persistent accounts. Both
start with $500 simulated capital; the existing certified ledger was preserved.
The experimental service consumes actual full-depth observations from the
certified collector's read-only `/api/market-frame` endpoint. It does not create
another exchange WebSocket collector or reconstruct books from dashboard prices.
The frame export does not access certified risk/account methods. Invalid sources,
changed scope, future receipts and unhealthy producer frames are withheld.

```sh
uv run neraium-poly monitor
uv run neraium-poly monitor --once --width 38 --no-color
systemctl status neraium-poly-paper neraium-poly-experimental
```

The monitor fits phone SSH viewports, refreshes automatically, and distinguishes
REAL MARKET DATA, EXPERIMENTAL PAPER TRADING and CERTIFIED PAPER TRADING. Missing
services display unknown values. Stale valuations show `P/L(last)`; they are not
presented as fresh liquidation proceeds. Ctrl-C stops only the monitor. The
experimental API is loopback port 18743 and API-only; the certified browser dashboard
continues on port 18742. No public dashboard was deployed.

## Strategy scope and actual results

Six candidates are explicitly registered and enabled for research evaluation:
cross-market consistency, persistent relationship changes, liquidity spread,
event-driven repricing, short-horizon behavior and calibrated forecasting.
Currently supported experimental entry paths are the short-horizon monetary
forecast and that forecast additionally conditioned on persistent relationship
evidence. Neither is a calibrated terminal probability. The remaining candidates
are non-trading guards while logical payoff review/multi-leg execution, queue
and two-sided maker support, independent context or calibration are unavailable.
They must not be described as complete executable strategies or profitable.

The horizon forecast uses actual trailing bid observations and matured historical
forecast errors; uncertainty is an explicitly unvalidated empirical envelope.
Relationship findings are descriptive and cannot establish profit by themselves.
The system records setup rejection counts/digests/input IDs and representative
rejections per cycle. Every eligible signal, risk decision, order, fill and exit
has individual durable account evidence. Books used for execution are stored in
full with immutable identities before capital changes, including held tokens
outside the research subset. Input metadata, fee evidence and model source hash
are retained. Research checkpoints cannot silently adopt changed model code.

The actual limited archive diagnostic ran forecasts at horizons of 60 and 120 seconds forecasts in two
concurrent CPU workers. At 60 seconds, forecast MAE was 0.00149479 USD/share versus
0.00063542 for an unchanged-bid baseline; at 120 seconds, 0.00115190 versus0.00089873.
The model was worse in this sample. Each worker checked the same 24,000-record
archive window, selecting 280 observations for four densely sampled tokens.
These are quote diagnostics, not independent events or executable backtests.
Historical orders/fills/P&L remain null because historical fee/rule/capture
requirements are unmet. No profitability or certification claim is supported.

Live results are timestamped in `.planning/evidence/phase9/operation.json`.
At 03:14:54 UTC on 2026-11-06, the shared source monitored 200 markets / 400 tokens with
292 fresh books. Experimental research selected 64 tokens across 33 markets,
48 fresh at its latest frame, and recorded 122,640 strategy evaluation attempts.
Qualified opportunities, attempted/submitted orders, fills and open positions
were all 0. Both accounts had $500 cash and $0 simulated P/L. These are observations,
not guarantees of future market counts or trading activity. No trade is forced.

## Risk, execution and recovery

Experimental registration never invokes certified approval. Certified model,
calibration, evidence, causal-provenance, expected-value and owner-signature gates
remain mandatory and unchanged. The experimental subclass shares operational
identity, freshness, liquidity, spread, minimum-size, tick, tier, capital,
reservation, correlation/event exposure, daily-loss and drawdown checks. Initial
aggregate exposure is 20%; unclassified correlations share a stricter bucket.
Default standard positions are $2–$5, including exchange minimum lots. High and
exceptional hard ranges remain $5–$15 / $15–$25; current unvalidated exceptional
signals always reject. No leverage, loss chasing or minimum trade count exists.

Simulated entries require actual post-latency source AND receipt timestamps,
known current official fee observations, real ask depth and bounded participation.
A repeated old quote cannot fill an order after latency. Horizon exits use actual
post-latency bid depth, partial fills, known fees and documented conservative
slippage. Fees use the official supported exponent 1 curve's global notional bound;
that conservative bound can exceed the exact protocol fee. Fee evidence preserves
canonical parsed JSON hashes, not a claim of byte-identical HTTP archives.

Positions use fresh bid marks when available; stale held marks block new entries
and remain visibly stale. They are not fabricated exits. Verified settlement is
available only with authentic final payout proof, exact identity and separate
matching rule review; dates, closed flags or terminal prices cannot create payout.
Without current exit liquidity or reviewed settlement proof, holdings remain open.

Strategy-level realized/unrealized results, drawdowns and cash baselines are
tracked. Loss, drawdown and losing-streak controls suspend experimental strategies;
restart does not clear suspension or emergency stop. Simulated results cannot
become independent forecasting labels or certified approval. An actual service
restart preserved capital, counters and model history and reconciled inventory.

## Historical qualification

The versioned main dataset is `data/phase9qualification/qualified-main-v1` with
locally retained raw chain evidence.47 of 51 source/API outcome groups now have
exact finalized CTF resolution timestamps, payout, receipt/log/block identity and
canonical inclusion corroboration. One source transaction locator referred to
condition preparation, demonstrating why lifecycle hints alone are insufficient.
The remaining four source groups are unlinked within the bounded acquisition.
95 read-only RPC requests downloaded about 1.3 MB; no transaction methods or wallets
were used. Event time and acquired-now availability remain separate.

There are still 0 qualified training events and 0 qualified heldout events. Historical
availability, executable depth, independent context, dependency grouping and
historical rule versions remain unqualified. The separate 897,192-row publisher
L2 archive remains research-only.100 independent training and 100 heldout events,
proper calibration, realistic costs and explicit owner approval remain required.
No experimental result automatically promotes a strategy.

## Operations and verification

The installed experimental systemd service starts at boot and restarts on failure.
It has a 50% CPU quota,768 MiB memory cap and its own writable project-data directory.
Certified storage is read-only in its actual mount namespace. Account paths,
markers, symlinks/hardlinks and process ownership are checked before writers open.
The certified ledger and existing unrelated listeners/services remain preserved.

Experimental SQLite storage is bounded to 512 MiB with an 8 GiB free-disk floor.
Exhaustion visibly suspends trading and preserves evidence. Automated archive
export/retention is not implemented; long-running operation needs capacity
monitoring. The archive samples actual states rather than promising every tick.
Unsupported fee curves, quiet/stale books and missing evidence reject safely.

412 backend tests passed, including isolated capital, genuine quote replay,
post-latency/partial execution, duplicate orders, fees, settlement, stale marks,
kill switches, restart reconciliation and phone rendering. Five browser tests,
production build, Ruff checks and Python/npm dependency audits passed. The final source revision is 121bc31; [both CI jobs passed](https://github.com/Neraium/Neraium-Poly/actions/runs/42154963153). An earlier CI run caught an unset thread-environment
reporting assumption;8328325 fixes it with an explicit regression. A final telemetry scope mistake was corrected in 121bc31 and verified before reloading the services. Relationship definitions and evidence are durably archived before admission.

Development used three concurrent writing agents plus the coordinator in isolated
worktrees, with a second monitor wave after historical implementation. Tests used
two actual pytest worker processes; historical row processing used two CPU workers
(five job processes including coordinator/control helpers); diagnostics used two
actual concurrent CPU workers. Numerical threads were limited to one per worker.
Per-job PIDs, actual overlap and scope are recorded in `concurrency.json`; this is
not a claim that all CPU job groups ran simultaneously. Long-duration profitability
and certified real-data performance remain unestablished.

PAPER_TRADING=true; LIVE_TRADING_ENABLED=false. LiveBroker always raises. There is
no funded wallet, transaction signer or live-order transport. Native hook trust
was not established; explicit reviews and recorded verification were used.
