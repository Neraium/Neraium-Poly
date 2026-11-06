# Explicitly registered experimental strategies

These six strategies are registered in `ExperimentalStrategyEngine`. Their
outputs are labeled `unvalidated`, identify the experimental account, and cannot
approve a certified strategy. Registration permits research evaluation; every
simulated order still needs the isolated operational risk engine and current
real executable liquidity. No minimum trade count exists.

| ID | Hypothesis and eligible universe | Entry / exit | Missing evidence and failure cases |
|---|---|---|---|
| cross_market_consistency | Reviewed complete logical payoff baskets may have inconsistent all-leg executable costs | No entry until separately reviewed exhaustive rules and safe all-leg execution exist; verified all-leg resolution or hedged close | Correlation is not a payoff identity; missing leg, rule mismatch and non-atomic execution reject |
| persistent_relationship | A persistent contextual change can support a separately modeled temporary repricing hypothesis | Qualified descriptive SII evidence **and** the measured horizon bid model below; exit at its fixed horizon using actual observed bids | A relationship change alone is insufficient; missing baseline, persistent evidence, rules, liquidity or forecast errors rejects |
| liquidity_spread | A supported fill process may compensate inventory and adverse-selection costs | No entry until queue/fill and two-sided inventory mechanics are independently supported; cancel/time limit and actual bid liquidation | Displayed depth does not establish queue priority or a fill; no invented maker fills |
| event_driven | Independently timestamped context can support a causal probability update | No entry without independently archived predecision context and a response model; fixed reviewed event horizon or evidence invalidation | Rewritten timestamps, already priced context, unsupported probability update or missing quote reject |
| short_horizon | A trailing bid reference may predict a temporary observed-price dislocation reversal | Monetary lower exit-bid estimate must clear entry ask, both fee bounds, both slippage buffers and $.03/share hurdle; observed bid exit at60seconds | Reference may fail under genuine repricing or regime change; error envelope is unvalidated and has no guaranteed coverage |
| calibrated_forecast | Independent context and verified prior outcomes can support calibrated terminal estimates | No entry without causal independent context, labels, calibration and scope; verified settlement or reviewed evidence invalidation | Current market price alone is never an independent calibrated probability; missing inputs reject |

All six emit explicit rejection reasons when prerequisites fail. Unsupported
strategies are not silently replaced with synthetic signals. Default registration
lists all six; configuration may enable a subset. Exceptional allocation remains
subject to the account's stricter qualification and cannot follow from confidence
or a large observed price movement alone.

## Measured, unvalidated horizon model

The implemented short-horizon model targets **USD per share at a future executable
bid**, not a terminal outcome probability. It uses a causal trailing20-observation
median of observed bids. For each previous decision it measures the actual bid
at the first source timestamp at least60seconds after that decision's **receipt
availability**, allowing up to30seconds of observation delay. Both feature and
label observations must already be available before the current decision. The
current quote is excluded from both the training reference and residual labels.
At least20 matured forecast errors and40 prior observations are required.

The current forecast is the trailing bid median plus the median prior matured
forecast error, clipped to [0,1]. Its empirical error envelope is the prior90th
percentile absolute centered residual with a $.01/share policy floor. This is a
transparent **unvalidated monetary uncertainty envelope**, not calibrated
confidence coverage. No binary-probability calibration flag is set or invented.
The interval must be no wider than $.35. The conservative round-trip estimate is:

`lower_exit_bid * (1-fee_bound) - entry_ask * (1+fee_bound) - 2*slippage_per_share`

The default slippage buffer is $.01/share per leg and the minimum net estimate is
$.03/share. Known global notional fee bounds are conservatively used for both
legs; missing, future, stale or nonofficial fee observations reject. A quoted
zero requires a genuine official observation reference. Account checks recompute
the bound and enforce actual instrument minimum size, tick size, participation,
capital reservations, event/correlation limits, drawdown, losses and shutdown.
A model-qualified signal is not a fill or an assurance that its exit will exist.

Only complete, two-sided, non-crossed actual official CLOB/native WebSocket books
with source age at most15seconds and spread at most$.05 enter history. Unknown
sources, future inputs, changed immutable IDs and out-of-order books reject.
Re-receiving a source timestamp cannot inflate observations. A source gap over
120seconds resets that token's model. State is bounded to96 minimal numeric
quotes per token (configurable60–240) and supports policy-bound restart recovery.
It does not retain full depth arrays in the model checkpoint.

## SII-inspired evidence

The descriptive graph uses explicit same-event YES membership hypotheses and the
existing frozen temporal relationship baselines, contextual liquidity checks,
persistence and source/availability ordering. Named binary outcomes are not
renamed YES. Duplicate paired observations cannot inflate persistence. The graph
never converts statistical association into mutual exclusivity or a guaranteed
payoff constraint. Regime/evidence output records actual paired book IDs and
reasons; a qualified structural finding still needs the independent horizon model
and all operational controls before experimental allocation.

## Evaluation and feedback boundary

Experimental marks and simulated realized P/L are account results, not independent
resolution labels. They must not train or certify a probability model. The
formal100/100 independent-event approval process is unchanged. Experimental
registrations, checkpoints, performance rankings and automatic loss suspensions
cannot promote themselves to certified operation. The no-trade cash baseline
remains $500 with zero trading P/L; comparing against it is not a market-model
certification result. Missing actual fees, exits or point-in-time metadata yield
null execution results in historical diagnostics rather than invented fills.
