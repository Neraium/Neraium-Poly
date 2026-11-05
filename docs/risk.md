# Capital intelligence

`RiskEngine(path=':memory:', limits=RiskLimits())` is a paper-only transactional ledger. SQLite WAL and `BEGIN IMMEDIATE` serialize approvals across instances. Persistent instances reject changed limit configurations until an explicit migration. It is suitable for a single-host research process, not distributed production custody.

`approve(intent, opportunity, market, book, evidence, *, now, estimate=None, model=None, correlation_group='unclassified')` returns `RiskDecision`. Unknown correlation membership shares one conservative bucket, capped at 10% of initial bankroll. No estimate alone grants exceptional sizing: exceptional orders require a calibrated estimate, manually approved model with 100 calibration samples, independent evidence sources with disjoint observation provenance, liquidity and every ordinary risk condition. Missing rules, stale/incomplete books, wide spreads, missing or unqualified evidence, low conservative net edge, future availability, excess participation and capital limits reject.

`TradingOpportunity.fee_rate` is an **effective notional fee bound**, not the exchange curve coefficient. For a fee curve `shares * rate * p * (1-p)`, use an effective bound `rate * (1-p)` over executable prices. Opportunity liquidity is measured in shares; sizing converts it to USD using market probability. Unknown fees must be withheld upstream. This ledger reserves `quantity * limit_price * (1 + fee_rate)` and recomputes net edge using that bound plus slippage. There are no fee-free assumptions.

Broker integration:

- `validate_approval(intent, decision, *, now)` verifies exact original intent and decision JSON, expiry, persistent reservation, emergency shutdown and current loss/drawdown stops. Risk errors must reject execution.
- `record_fill(intent, decision, cumulative_quantity, average_price, cumulative_fees, *, now)` transactionally records cumulative fills, making repeated acknowledgements idempotent. Changed economics at the same cumulative quantity reject; price, size and fees cannot exceed approval. SQLite failures raise and roll back.
- `release(reservation_id, *, now)` releases unused capital; invested capital remains exposed. Expiry also releases unused reservations. No identifier may be reused after expiry/cancellation.
- `positions(now=...)`, `snapshot(now=...)`, `mark({token: price}, now=...)` and `audit()` support reconciliation and reporting. Position average cost excludes fees; account equity and exposure include fees. P/L is simulated, including settlement P/L.
- `settle(token, payout, now=..., rules_verified=True, resolution_source=...)` supports verified binary simulated settlement; uncertain and fractional settlement reject. This is not a transaction transport.
- `kill_switch(True, now=...)` persists suspension and revokes every pending reservation. Re-enabling requires an explicit operator call; daily loss and drawdown stops still apply.
- `size(opportunity, fractional_kelly=False)` suggests dollars within configured limits; never authorizes execution. `stress(now=...)` reports all contracts losing simultaneously.

Limits default to $500 research capital, 20% aggregate exposure, 5% per market, 10% event/correlation, 5% daily loss, 10% drawdown, and $2–5 / $5–15 / $15–25 tiers. Repeated losses never increase suggested size. SELL and leverage are unsupported and reject.

Limitations: research provenance is caller-supplied; no source authenticity oracle exists. Approved model provenance and a calibrated, matching probability estimate are mandatory for every tier. Market and estimate timestamps have separate configurable freshness limits. Correlation groups require reviewed external configuration. Float calculations use 1e-8 tolerances; production multi-currency accounting should migrate to decimal fixed-point. Marks require an upstream conservative, fresh valuation policy; the engine does not silently synthesize missing prices. No profitability claim is made.
