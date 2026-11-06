# Phase8 research readiness

Phase8 adds authentic-history acquisition, bounded liquid-market discovery and
native market WebSocket ingestion, six competing research hypotheses, causal
forecast evaluation, an owner-signature activation gate and operational research
visibility. No strategy has qualified for activation. No profitability claim is
supported; unsupported model scores and execution returns remain null.

## Authentic acquired evidence

The official event-first acquisition retained 250 parent/event groups, 51 strict
verified outcome groups, 616 historical price points across 50 groups and 95
public METAR observations. The other 199 native resolution rows lack required
transaction references and remain unverified. The 51 labels lack the exact
settlement timing needed by the causal evaluator. Downloaded histories retain
today's availability time; historical exchange depth is not manufactured.

A separately licensed publisher archive contains 897,192 L2 rows across 805 slugs
and 1,610 tokens. It retains publisher capture time separately from retrieval
time. It lacks original exchange source/receipt times, official event mapping,
independently corroborated settlement and dependency review. An actual full-row
inspection found 20,189 crossed books and 52,912 one-sided books. The reproducible
5,000-row convenience sample is explicitly nonrepresentative: 69 crossed/locked,
242 one-sided. Publisher winners cannot enter model features. This archive is
research evidence, not certified exchange execution snapshots.

Sources, acquisition methodology, license attribution and raw-file hashes are in
[historical evidence](historical-evidence.md). Raw local data remains under
`data/phase8-history-events` and `data/phase8-public-l2-sample`; it is not committed
to Git. Normalized records bind raw hashes and source URLs. The service report
at `data/paper-live/research/report.json` is reproduced by `research-evaluate` and
its dataset hash is recorded under `.planning/evidence/phase8`.

## Strategy and certification outcome

All six documented hypotheses have callable precondition/qualification functions:
persistent relationship change, logical constraints, independent forecast,
liquidity making, event repricing and microstructure. Their documented assumptions
are in [strategy research](strategy-research.md). These functions cannot authorize
orders. Genuine logical bundle execution and calibrated microstructure/queue
models remain unsupported; research setup signals are not profitability results.

The evaluation supports raw-price, histogram and independent-context baselines,
chronological heldout scores, Brier/log-loss/calibration, nominal confidence
intervals and category/regime diagnostics when adequate causal observations
exist. This actual bundle yields zero causally usable forecast rows, zero
training rows and zero heldout rows. Consequently there is no numerical real-data
model comparison, confidence interval or backtest P/L to report. Repeated crypto
windows and related outcomes are not independent examples.

Certification still requires 100 reviewed independent training events and 100
heldout events, authentic predecision books/context, exact verified settlement
availability, reviewed rules, realistic costs/fills and confidence-bounded
out-of-sample improvement. Numeric thresholds were not relaxed. Independent
source provenance and cross-event dependency review are separate requirements.
Collecting 250 IDs or 897,192 snapshots does not satisfy that gate.

## Operational boundary

The persistent service uses real public markets. Its bankroll, broker and risk
ledgers survive restart with $500 initial simulated capital. Actual native
full/delta counts, REST counts, fresh-book counts, gaps and reconnects are exposed
separately. Depth storage samples real states; it does not archive every tick.
Strict 15-second source freshness, missing data and settlement checks remain.
Quiet/stale contracts are withheld even with an open WebSocket connection.

All simulated orders need current strategy scope and risk approval. Pending
orders bind the exact approval epoch and cancel after approval replacement,
revocation, expiry, token closure or missing current quotes. No public owner key
or signed approval is installed. An automated passing report alone cannot
activate trading. Only the owner can approve a future valid package, through the
[explicit approval process](real-strategy-validation.md).

`PAPER_TRADING=true`, `LIVE_TRADING_ENABLED=false`; LiveBroker always raises.
There is no wallet, transaction signer or live-order transport. Existing unrelated
services and the older readonly Polymarket collector remain preserved. Full
long-duration streaming/throughput certification, qualified real-data model
validation and eventual owner approval remain future work. History acquisition
is a bounded explicit command, while live collection and hourly report refresh
continue persistently. No timer silently downloads an unbounded historical corpus.
