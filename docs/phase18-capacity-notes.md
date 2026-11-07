# Phase 18 evidence convergence and capital-capacity research

These modules are pure research assessments. They never create an account, place an
order, alter a stop, change an operational risk limit or certify a strategy.
Synthetic tests exercise qualification; they are not authentic forecasting results.

## Convergence API

`qualify_convergence(forecast,market,book,evidence,*,now,risk_context=None)` accepts
existing market/book models or JSON mappings and domain-forecast/evidence mappings.
Default context withholds qualification. Every result has `eligible=false`,
`trading_authority=false`, `certification_authority=false`, no order attempt and no
account P/L. `research_qualified` denotes a proposal satisfying supplied verified
research prerequisites; it still grants no execution authority.

The assessment requires matching parent/market/token, exact rules hash and future
resolution horizon; versioned model/dataset/feature provenance; independently replayed
calibration; bounded probability uncertainty; authentic source/receipt-fresh books;
current verified fee provenance; at least two reviewed support dependency groups;
clear paper-only stop/configuration; existing explicit strategy/terminal-execution
admission and amount-bound risk approval. Numerical confidence alone is insufficient.

Each evidence payload records `supported_event_id` and `independence`:
`source_group`, nonempty `upstream_groups`, `reviewed=true`, `proof_sha256`.
The original canonical payload hash and source/retrieval/availability cutoffs must
verify. Different provider names do not prove independence: overlapping upstream
groups or duplicate records reject. External replay/dependency verifier callbacks are
required; structural self-assertions and URLs are not source truth.

`risk_context` supplies current verified `fee_observation`, paper/live/stop flags,
`experimental_admission_authorized`, `terminal_execution_authorized`, `risk_approved`,
`approved_notional`, initial bankroll500, unchanged aggregate fraction.2, cash and
remaining aggregate/market/event/correlation notional. Required replay callbacks are
`verify_evidence(e)`, `verify_independence(tuple_evidence)`, `verify_forecast(f)`,
`verify_rules(f,m)`, `verify_fee(schedule,m)`, `verify_admission(f)`,
`verify_risk(f,m,b)` and `verify_proposal(f,approach,proposal)`.
If a relationship finding was used, `verify_persistent_relationship(f)` is also
required. Exceptions or missing verifiers reject; callbacks do not run an order engine.

Two policy proposals are recorded, including rejected decisions on malformed input:

|Research approach|Initial target|Policy edge floor|Maximum interval width|
|---|---:|---:|---:|
|High-throughput|$2 standard|.03/share|.35|
|High-conviction|$5 high tier|.05/share|.15|

These new comparison policies are research definitions, not modifications to production
strategies. Minimum lots may increase principal only within existing standard$2–$5
or high$5–$15 limits.10%best-ask displayed participation is conservative versus the
existing25%risk maximum. Current cash/exposure/event/correlation and exact approved
notional must cover fee-inclusive reservation. Exceptional$15–$25 is not proposed
without a separately implemented, independently justified exceptional approval package.
No daily trade count or confidence-only size escalation exists.

Conservative modeled edge is lower_probability*(1-fee)-ask*(1+fee)-.02/share,
using known current fee bounds. This is not a claim about exact settlement fees.
Unvalidated probability/rules/evidence produces no qualified edge, even if raw arithmetic
can be calculated. Empty or absent evidence cannot become independent confirmation.

## Capital-capacity API

`capacity_scenarios(opportunity,book,*,bankrolls=(500,1000,10000,100000,1000000))`
requires the exact quoted book ID/hash/market/token from the convergence assessment.
Missing, stale, crossed, incomplete or untrusted books withhold all scenarios.
Duplicate levels and books beyond1000 levels per side reject rather than double-count.

With no fully qualified event forecast, the output is `liquidity_only_unqualified`:
actual observed depth can be described but expected value, profitability, returns,
drawdown, capital turnover and risk-adjusted performance remain null. No market-price
baseline is presented as an independent event forecast.

The hypothetical demand stress is20%of each scenario capital, bounded by unchanged
10%event/correlation fractions. Only10%of each observed level is used. Deeper asks
increase the weighted entry price; qualified modeled capacity stops when conservative
marginal edge falls below.03. Existing approved single-order maxima stay$5/$15/$25
for every hypothetical capital, and no scenario is an authorized order. Capacity
beyond the observed book, queue priority, post-latency entry survival and future exit
liquidity remain unverified. Current bid support is reported separately. Minimum lots
and minimum$2 principal prevent presenting tiny unavailable sizes as qualifying value.

An optional `already_committed_shares` crowds the same quoted liquidity rather than
creating a second independent pool for each research approach. Capital lockup uses a
known future contract end; additional settlement/dispute delays remain unknown.
Finite depth produces partial capacity and nonproportional scaling. If observed depth
ends before edge disappears, the economic capacity beyond it is null, not extrapolated.

## Authentic snapshot audit

A bounded read-only audit retained original shared-collector market-frame bytes,
source timestamps, frame ID and SHA. It generated three distinct-parent liquidity-only
profiles and no forecasts/opportunities/orders/fills. Data/artifacts in the isolated
worktree `data/phase18-capacity/actual-liquidity-audit-v2.json` are genuine snapshot
measurements, not trading performance. Largest-capital modeled support exhausts observed
participating depth; smaller capital is limited by concentration. No proportional
profit assumption or additional simulated trading account was introduced.

The integration coordinator retains the actual snapshot/hash evidence and reports
current balances and source health independently. These new policies cannot bypass
existing admission, certified 100/100 event requirements or separate owner approval.
