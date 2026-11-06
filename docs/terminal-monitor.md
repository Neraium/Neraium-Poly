# Termius / iPhone monitor

```sh
uv run neraium-poly monitor
uv run neraium-poly monitor --once --width 38 --no-color
```

The monitor reads only loopback state APIs. It does not collect another exchange
stream, submit orders, approve strategies or write to either account. Ctrl-C
exits the monitor while paper services continue. Automatic refresh adapts to the
terminal's current width and height; one row is reserved for the interactive
cursor. It is suitable for a34–45column,24row iPhone SSH window. Colors are
restrained and optional; labels remain meaningful without color.

Every viewport distinguishes **REAL MARKET DATA**, **EXPERIMENTAL PAPER TRADING**
and **CERTIFIED PAPER TRADING**. Essential account identity, cash/P&L, execution
counts, exposure, approval gate and independent emergency-stop status take
priority over extra strategy detail. Larger viewports include more strategy
rows. Strategy rows rank observed realized simulated P/L when available; absent
performance stays unknown. An engine's enabled status is distinct from strategy
certification. Unvalidated paper results never authorize certified operation.

Current observations include market/fresh-book counts, connection/producer
health, native messages, relationship counts and a UTC observation timestamp.
The gap/reconnect counters are labeled `G/R`; conservative source-integrity and
missing-baseline invalidations must not be interpreted as confirmed lost packets.
Experimental rows show orders/fills/positions/opportunities and account exposure.
The certified gate and chronological training/test counts remain visible.
Rejection and recent activity lines are bounded to the viewport. A long value
gets an ellipsis instead of wrapping the safety rows out of view.

If a service is unavailable, its values remain **unknown**, not synthetic zeros.
An API labeled `mode="paper"` cannot present its demonstration values as live
market observations. Missing boolean flags remain unknown rather than implying
a clear emergency stop or connected feed. Stale held-position marks prominently
show **STALE MARKS** and `P/L(last)`, instead of presenting last-observed valuation
as current. Nonfinite/boolean numeric values do not render as valid cash or
counts. All strings are literal text; ANSI commands, terminal title sequences,
control characters and Unicode direction controls are removed.

The two HTTP reads run concurrently, use no redirects and have a5second timeout
and8MiB streaming response budget per service. One failed API does not substitute
values for that account or stop the other view. Rendering tests exercise widths
34,38,45and80 at24rows, very short/tall viewports, terminal injection, stale marks,
unknown flags, error isolation and concurrent bounded reads. Controlled rendering
fixtures remain explicitly separate from the actual read-only sample captured
under `.planning/evidence/phase9-monitor/`.
