# Isolated experimental paper account

`ExperimentalAccount` owns an independent $500 simulated bankroll and explicit
`experimental-paper` identity. Its `account.json`, `risk.sqlite`, `broker.sqlite`
and `service.sqlite` reside in a directory disjoint from certified storage.
Startup refuses overlap, symlink/hardlink storage aliases, wrong identity markers
and unidentified existing databases before opening any writable database. The
runtime should also give its systemd service write access only to this directory.
No certified ledger or strategy-validation database is opened by this account.

Six named research strategy IDs can be explicitly registered/enabled in account
configuration. Registration is not certification. Signals retain `unvalidated`
status and distinguish monetary horizon marks from terminal probabilities. No
`ModelProvenance.approved` or `ProbabilityEstimate.calibrated` flag is fabricated.
The current execution path supports horizon-mark BUY/exit experiments only;
terminal and multi-leg logical payoff proposals are rejected until dedicated
execution semantics exist. Unsupported signals remain research records.

## API

```
ExperimentalAccount(directory, certified_directory, limits=None,
                    enabled_strategies=None, execution_config=None, clock=None)
submit(signal, market, book, now=now, target_notional=2, fee_schedule=schedule)
advance(books_by_token, now=now, fees=fee_schedules_by_token)
mark(books_by_token, now=now)
snapshot(now=now)
cancel(client_order_id, now=now)
stop(now=now)
close()
```

`account.ledger` is the exclusive `LiveLedger` for this account; the runtime must
reuse it for checkpoints rather than acquiring a second owner lock. A separate
process cannot concurrently own this directory. A caller must enforce its storage
budget before recording inputs/signals, and use actual public observations only.

Each fee schedule contains `fee_rate`, timezone-aware `observed_at`, official
HTTPS `source` and nonempty `reference`. Entry risk and exits independently check
that the schedule is at most 300 seconds old and available before execution.
The signal rate must match the supplied schedule. Unknown fees, including an
unproven zero fee, reject. Source names and hashes do not independently establish
truth; the shared public-data collector authenticates transport and instrument
identity, and the runtime archives referenced source inputs.

## Shared operational risk

`RiskEngine._operational_checks` is factored from the existing certified checks.
Certified `RiskEngine._checks` still applies every calibration/model/evidence/EV
and exceptional qualification check. Its default opportunity decoder remains
`TradingOpportunity`. Only `ExperimentalRisk` decodes `ExperimentalSignal` and
substitutes explicit experimental valuation qualification in its separate account.
Capital reservation, fee bounds, cumulative fill acknowledgements, exposure,
event/correlation concentration, daily loss, drawdown and emergency-stop controls
are inherited unchanged. All unknown correlations share one conservative bucket.

Experimental approval additionally requires a registered active strategy,
matching actual entry-book evidence, causal fresh inputs, stated hypothesis and
uncertainty, interval width at most 0.35 and a conservative net edge at least the
risk limit. Net edge is recomputed as lower exit bid times one minus fee rate,
minus entry ask times one plus fee rate, minus two per-leg slippage buffers.
A horizon mark is never described as a calibrated settlement probability.
Unvalidated exceptional allocations reject. Instrument minimum size can increase
a $2 target only within the same hard $2–$5 standard tier; it cannot bypass a tier
limit. One strategy owns each token until entry remainders and inventory clear.
This prevents stacking and mixed strategy cost attribution.

## Execution, exits and settlement

Entries use the existing durable paper limit broker: observed asks only, bounded
participation, source freshness, latency, partial fills, cancellation, expiration,
shared snapshot liquidity and cumulative idempotent risk acknowledgements. Both
source and receipt times must be at or after the simulated latency deadline;
re-receiving a pre-latency quote cannot create an executable fill. Missing current
books cancel pending entries. Re-reading a source snapshot does not
replenish its liquidity.

At the signal horizon, entry remainders cancel before a long-only exit request.
Exit matching requires an actual post-latency, fresh, two-sided public book and
current verified fee schedule. It consumes observed bids within a per-share depth
slippage band and participation limit, without shorting or reusing the same
source-time liquidity. Conflicting or regressing depth is withheld. Latency price
changes remain real simulation losses or gains; the slippage buffer is an entry
EV safety margin, not an invented cash charge. Fees and actual entry/exit prices
are posted to simulated cash and proportionate cost basis. There is no maker
queue or hidden-liquidity assumption. Below-minimum leftover positions cannot be
invented into an executable replacement sell; they remain visible pending a
legitimate exit or separately verified settlement.

Exit depth consumption, cash, inventory, realized P/L and exit records commit in
one experimental risk-DB transaction. Pending submissions crossing the separate
broker DB recover conservatively: acknowledged broker submissions are recovered;
unacknowledged reservations are released. Restart reconciliation verifies BUY
acknowledgements and independently reconstructs net inventory, cash, realized P/L
and remaining cost basis from entries, exits and settlements. A mismatch latches
the emergency stop instead of resetting capital.

Settlement requires a matching native `SettlementObservation`, final binary payout,
transaction reference, reporter/condition identity, matching rules/source and
explicit named review of the exact token/rule hash. Closed flags and terminal
prices cannot settle. Proof identity and accounting are idempotent and atomic;
verified resolved tokens cannot enter again. No real token redemption occurs.

## Monitoring and suspension

Snapshots expose actual attempt counts, submitted BUY reports, exit orders, BUY
and exit fill events, positions, reservations, realized/unrealized simulated P/L,
strategy attribution and reconciliation. The cash-hold/no-trade baseline is not
an independently validated forecast. Per-strategy 2% bankroll loss or drawdown,
or five completed losing exits, suspends new strategy activity; account daily
loss/drawdown limits separately latch the account stop. Suspension never certifies
a promising strategy. `stop` independently cancels experimental orders and latches
its persistent kill switch without changing the certified account.

Tests use explicitly controlled fixtures; their positive orders and P/L are not
real-market results and must never be installed as operational research evidence.

Full actual execution and held-position mark books are stored in an immutable,
hash-checked experimental observation table before cash side effects. This
includes pending/held books outside the runtime's selected research sample.
Marks bind exact token, market and exchange and cannot regress source time.
Current fee evidence is checked again when spending an approval; changed higher
fee bounds cannot spend an old reservation. No private key or live transport is
used in these checks.
