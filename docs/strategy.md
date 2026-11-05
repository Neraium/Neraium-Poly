# Probability and strategy research v1

The baseline is an event-frequency histogram calibrator. `LabeledForecast`
separates forecast availability from settlement-label availability. Its `outcome`
is a known resolved label, never a proxy price. Fitting excludes labels that were
not available by the cutoff and rejects duplicate records or repeated events.
Each bin estimates a smoothed historical outcome frequency with a Wilson
interval; insufficient per-bin samples produce `calibrated=False`.

```python
from neraium_poly.strategy import HistogramCalibrator, ModelRegistry
model = HistogramCalibrator.fit(resolved_forecasts, cutoff, bins=5, min_samples=30)
registry = ModelRegistry()
model_id = registry.register(model)  # does not approve or activate
provenance = registry.approve(model_id, actor="research-reviewer", now=review_time)
estimate = registry.estimate(model_id, market, now, evidence_ids=(evidence.id,))
```

Training artifacts remain unapproved and immutable. Approval yields separate
provenance with its actual approval availability time; historical estimation
cannot use a future approval. Registering a replacement does not promote it.
`rollback` explicitly reactivates a previously approved artifact and records the
actor, time and model ID. Registry state is in-process and must be persisted by
the operational coordinator before process recovery. There is no automatic model
promotion and no production-trained model bundled with the application.

`OpportunityRanker.rank(market, book, estimate, evidence, provenance, now,
quantity=10, fee_model=ProtocolFeeModel(protocol_rate=...), tier="standard")`
returns `TradingOpportunity` or `None`; suppression reasons appear in
`last_reasons`. Every referenced evidence record must be supplied, qualified,
fresh and supported by observation provenance. Exceptional opportunities require
at least two distinct evidence sources with disjoint supporting observations;
this is a conservative provenance check, not statistical proof of independence.
Downstream risk approval remains mandatory for every tier.

Quotes cross only visible ask depth within a configurable slippage limit. The
opportunity records the worst crossed ask as the executable limit probability,
slippage versus the best ask, and executable liquidity in **outcome shares**.
Quantity is also shares. Net edge per share is the lower estimated probability
minus the worst quote, conservative fee per share, and latency buffer. The fee
reserve uses an explicit global effective notional bound valid over all possible
BUY price improvements, including fills against later books. A marketable book quote
cannot claim maker fees. Unknown fee schedules suppress the opportunity.

The official [Polymarket fee documentation](https://docs.polymarket.com/trading/fees.md),
reviewed 2026-11-06 UTC, specifies taker fee = shares × protocol rate × price ×
(1-price), and zero maker fees. No category rate is guessed: callers must supply
a verified per-market rate or an explicit synthetic fixture rate. The opportunity's
`fee_rate` is the effective proportional rate against executable notional; for a
single level the exact ratio would be protocol_rate × (1-price), but this
implementation deliberately reserves and simulates the larger global bound
protocol_rate. This overstates fees conservatively and remains safe if execution
prices improve. Custom fee models must declare an effective_notional_bound();
spot-price fees alone cannot establish a safe reserve. The standalone historical
backtest retains the exact protocol curve rather than the conservative broker
bound. These cost assumptions are explicitly different and should be reported
with results. Protocol rates can
change; this document is not a promise of future exchange costs.

The ranker also rejects unavailable or stale inputs, cross-exchange instrument
mismatches, incomplete books, insufficient depth, large spreads, missing
settlement rules, expired markets, unapproved models, excessive uncertainty and
net edge below a conservative threshold. It supports BUY-only research and
provides no claim of profitable mispricing from a relationship shift alone.

`walk_forward(records, evaluation_end, min_samples=30, bins=5)` performs an
expanding training-window evaluation. Each decision uses only labels already
available at that decision, and removes the entire test event from training.
It reports Brier score and a fixed $2-target BUY rule on supplied historical
executable quotes/depth; missing quotes or fee parameters cannot create trades.
Settlements after `evaluation_end` are excluded. Simulated drawdown follows
settlement availability order. Results include dataset hashes, exact training
record IDs and per-decision attribution for deterministic audit and replay.
Position sizing does not increase after losses. This isolated strategy backtest
does not model an integrated bankroll, risk engine, queue priority or arbitrary
order-book depth history; full portfolio scenarios are separately required.

Tests use synthetic data and demonstrate behavior and leakage controls only.
Histogram stationarity, sampling quality, independent resolved labels and future
calibration remain assumptions requiring empirical validation. Synthetic results
are neither expected real returns nor profitability certification. No optional
machine-learning model is enabled without a separately reviewed artifact.
