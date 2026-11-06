# Termius / iPhone monitor

```sh
uv run neraium-poly monitor
uv run neraium-poly monitor --once --width 38 --no-color
uv run neraium-poly monitor --view strategies --scope cycle
uv run neraium-poly monitor --view rejections --scope epoch
```

The default summary and the strategy/rejection pages fit 34–45 columns and 24
rows. `--scope cycle` shows the latest completed decision cycle; `--scope epoch`
shows persisted Phase10 totals. Pick a page before starting the automatic refresh;
there are no terminal keys that trade, approve, reset or stop an account. Ctrl-C
exits only the monitor. Terminal size is reread on every refresh and one row is
reserved for the interactive cursor. Larger screens show more details. Table
counts use truncated whole thousands (`k`), millions (`M`) and billions (`G`)
when necessary; API counts remain exact. Unknown values remain `—`/`unknown`.

Every page distinguishes **REAL MARKET DATA**, **EXPERIMENTAL PAPER TRADING**
and **CERTIFIED PAPER TRADING**. Unvalidated results cannot authorize certified
operation. A registered/enabled research path is distinct from executable order
admission and from certification. Summary legacy strategy rankings use observed
realized simulated P/L, not assumed profitability. Account cash, simulated P/L,
position counts, independent emergency-stop flags and the certified validation
gate remain separate. Stale position valuations say `STALE MARKS` / `P/L(last)`.
An observed live-enabled or paper-disabled service configuration replaces the
normal live-disabled footer with an unsafe-configuration warning.

Source fresh-book percentage divides `operation.fresh_books` by the subscribed
source token count (`operation.connectivity.subscribed_tokens`, then
`experimental.source_tokens`). Legacy APIs without either denominator use the
known `operation.current_books` count; that legacy percentage covers available
books rather than missing subscribed tokens.
The experimental detail row uses `experimental_fresh_books / selected_tokens`.
These different denominators must never be mixed. Missing, zero or contradictory
denominators suppress the percentage. Book timestamps, integrity and age are
validated by producer services; a fresh count alone does not establish strategy
eligibility or profitability. `Seen` is the producer view timestamp, **not** the
exchange source timestamp. Cycle and epoch timestamps are UTC.

## Decision counters

`decision_trace.latest_cycle.strategies` is replaced after each completed
experimental cycle. `decision_trace.phase10_epoch.strategies` is cumulative from
`epoch_started_at` and survives normal restarts through the durable account
checkpoint. `last_evaluation_at` labels the completed traced evaluation. Missing
trace fields never become zeros. Pre-Phase10 counters retain their own legacy
scope and are never added to the new epoch. Explicit trace resets require a new
epoch; restarting the monitor resets nothing. The monitor also reads the initial
flat `totals` / `latest_cycle` trace proposal for compatibility.

Each strategy has separate counters. A considered market is an evaluation
attempt, not an independent event or a unique market count over the epoch.
Repeated cycles therefore increase considered counts. Summary totals sum across
strategies, so the same source market can count several times. The strategy page
shows all six strategy IDs using compact names:

| Column / field | Meaning |
| --- | --- |
| C / `markets_considered` | Market evaluations attempted by this strategy. |
| `valid_observations` | Observations passing its data prerequisite checks. |
| S / `candidate_signals` | Data/evidence prerequisites passed and a numerical valuation exists; costs/risk can still reject it. |
| R / `rejected_signals` | Signals rejected at strategy qualification. |
| Q / `qualified_opportunities` | Strategy admission predicates passed before portfolio risk. |
| `risk_rejections` | Portfolio risk denied an intent. |
| `order_attempts` | An intent was created and presented to risk. |
| O / `submitted_orders` | Paper orders admitted to the simulated broker. |
| F / `fills` | Newly observed simulated fill events, including partials. |
| `expired_orders` / `cancelled_orders` | Explicit order lifecycle transitions. |

The remaining stage totals appear below the six strategy rows. Rejection pages
show structured categories and sampled reason counts from the selected scope.
Reasons are **nonexclusive**: one rejected signal may fail several predicates,
so reason/category counts must not be summed into unique rejected signals.
Long predicates have concise display labels (for example
`conservative_roundtrip_edge_insufficient` becomes `net edge below floor`);
the full IDs, bounded examples and evidence remain in the state API. Empty
rejection data says it is missing rather than inventing a cause. Unsupported
performance metrics remain unknown.

## Previous cryptic labels and legacy counters

* `ExpEval` is now `Evidence/cycle`: `strategy_engine.intelligence.evaluations`
  is the length of the SII engine's latest relationship-evidence collection.
  It is a latest-cycle gauge, **not** cumulative strategy evaluations, signals,
  independent evidence events, or trades.
* `G/R` is now `Process gaps` / `Reconnect`. These come from
  `CoverageFeed.metrics()` and accumulate for that producer process, resetting
  when a new producer object/process is constructed. A gap is a conservative
  integrity invalidation, including missing baselines and intentional universe
  changes. It does **not** count proven lost packets. Reconnect counts stream
  failures handled by its retry loop; intentional subscription generations and
  invalidations must not all be interpreted as failed network reconnects.
* Legacy message counts are native messages processed by the producer, cumulative
  for its process. They do not prove usable books, qualified signals, or trades.
* `experimental_totals` are durable legacy cycle/observation/emitted-signal totals.
  A legacy emitted `signal` can be a rejected research record. It is distinct
  from the new candidate/qualified stage definitions. `last_cycle` counts and
  its rejection histogram describe only that completed cycle. The legacy
  summary labels itself `LEGACY STRATEGIES / REJECTIONS` until trace is present.
* Bankroll/order/fill/position values are account state, not monitor counters;
  refreshing, disconnecting or changing view cannot mutate them.

The monitor reads only loopback GET state APIs. It does not collect another
exchange stream, submit orders, approve strategies or write either account.
The two HTTP reads run concurrently with no redirects, a 5-second timeout and
an 8-MiB streaming response budget per API. One failed API leaves that account
unknown while the other continues. An API in demonstration `mode="paper"`
cannot present its values as real-market observations. ANSI sequences, terminal
title commands, control characters and Unicode direction controls are removed.

Rendering tests use explicitly controlled presentation fixtures. Sized Rich
console captures verify widths/heights, not a physical iPhone or browser. Actual
read-only service captures are kept separately under
`.planning/evidence/phase10-monitor/`; they are observations at capture time.
