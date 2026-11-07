# Neraium-Poly

**See Beyond the Signals.** An SII-inspired prediction-market research platform with evidence-qualified relationship intelligence, calibrated probability estimation, portfolio risk controls and paper execution. This is an independent implementation; it contains no proprietary Neraium-2.0 code.

Python modular monolith · React/TypeScript dashboard · versioned Pydantic contracts · SQLite research ledgers · public Polymarket data adapter.

Phase14 adds domain-neutral discovery, evidence/model contracts, weather/crypto/
economic research adapters and a multi-domain SSH view:

```sh
uv run neraium-poly monitor --view domains
uv run neraium-poly monitor --view events
uv run neraium-poly monitor --view research
uv run neraium-poly monitor --view archives
uv run neraium-poly monitor --view operations
```

See [architecture](docs/phase14-architecture.md), [actual readiness and limitations](docs/phase14-readiness.md)
and [storage audit](docs/phase14-storage.md). The expanded root filesystem and
[verified archive lifecycle](docs/archive-recovery-report.md) restored persistent
live collection. Managed archives retain all originals, use separate 64 GiB/16 GiB
service budgets and stop safely at finite limits. New models remain research-only;
no independent non-sports forecasting advantage is claimed.

Phase 15 adds [verified cold recovery, bounded capacity alerts and continuous relationship research](docs/phase15-architecture.md). Originals remain retained. [Retention](docs/phase15-retention.md) and [experimental-stop recovery](docs/phase15-stop-readiness.md) require separate owner decisions; neither is automatic. New domain inputs remain research-only pending mapping and calibration.

Phase 16 adds [causal qualification history and depth-aware execution checks](docs/phase16-architecture.md). The [readiness report](docs/phase16-readiness.md) records negative research findings and one losing, risk-approved experimental paper round trip. Certification remains blocked. Use `uv run neraium-poly monitor --view readiness` for current evidence and cost readiness.

Phase 17 adds [prospective fixed-candidate research and parent-aware empirical evaluation](docs/phase17-architecture.md). The [readiness report](docs/phase17-readiness.md) documents no supported advantage, preserved paper capital histories, and remaining independent-evidence and storage blockers. Use `uv run neraium-poly monitor --view edge` for research progress; these models have no order authority.

## Isolated experimental research and SSH monitor

```sh
uv run neraium-poly monitor
uv run neraium-poly experimental-paper --config config/experimental-paper.example.json
```

The experimental service uses a separate $500 simulated account, shared authentic
books and the same operational risk controls. Its strategies and results remain
unvalidated. Certified strategy approval is unchanged. See [Phase9 readiness](docs/phase9-readiness.md),
[terminal monitor](docs/terminal-monitor.md) and [account controls](docs/experimental-account.md).
No trade frequency is required and no live execution exists.

## Integrated real-market paper service

The integrated coordinator runs at **http://127.0.0.1:18742** with persistent risk, broker and strategy ledgers:

```sh
uv run neraium-poly paper-live --config config/paper-live.example.json
uv run neraium-poly strategy-status --data-dir data/paper-live
```

It scans up to 200 liquid real public markets with bounded REST and native WebSocket ingestion, feeds observed books into relationship intelligence, and evaluates the explicit real-strategy approval gate before any paper order. With no passing real-data report and explicit signed owner approval, it continues collection and records why trading is withheld. No strategy or probability estimate is fabricated to create activity. Phase8 research sources and unresolved activation blockers are in [readiness](docs/phase8-readiness.md). See [persistent operation](docs/live-paper-operation.md) and [validation requirements](docs/real-strategy-validation.md). The commands below remain separate synthetic research demonstrations.

## Run locally

Requires Python 3.12+, uv and Node.js 22+.

```sh
uv sync --frozen --extra dev
npm ci --prefix frontend
npm run build --prefix frontend
uv run neraium-poly scenario --output .planning/evidence/scenario.json
uv run neraium-poly serve
```

Open **http://127.0.0.1:18740**. The default session runs a reproducible synthetic end-to-end paper scenario. It explicitly labels synthetic data, estimates, modeled fees, simulated positions and P/L. The emergency stop latches for the runtime. No browser reset or live-trading endpoint exists.

Collect actual public observations separately:

```sh
uv run neraium-poly collect --database data/public.sqlite --cycles 1
uv run neraium-poly serve --database data/public.sqlite
# Optional bounded-per-round polling, until interrupted:
uv run neraium-poly collect --database data/public.sqlite --cycles 0 --interval 30
```

Public archive mode shows actual market data and freshness, withholding trading findings until independently prepared models and relationships are explicitly configured. Synthetic models are never silently applied to real markets. Library consumers use `PaperWorkflow` to connect approved models, relationship definitions, archival records, mandatory risk decisions and the paper broker.

## Implemented workstreams

| Stream | Capability |
|---|---|
| A — Data | Public discovery, normalized outcome IDs, books, price history, bounded trades, WebSocket resnapshot/reconnect, lifecycle, freshness and append-only replay |
| B — Intelligence | Relationship graph, causal baselines, persistent shifts, regimes, logical-rule review, contextual evidence qualification and suppression |
| C — Strategy | Histogram calibration, uncertainty intervals, explicit model approval/rollback, conservative net-value ranking, fee bounds and event-purged walk-forward evaluation |
| D — Execution | Paper limit orders, latency, partial fills, shared depth, cancellation/expiry, durable idempotency, acknowledgement recovery and reconciliation |
| E — Risk | $500 initial bankroll, $2–$5/$5–$15/$15–$25 tiers, 20% aggregate ceiling, market/event/correlation caps, reservations, losses/drawdown, stress and emergency stop |
| F — Operations | Responsive console, market/evidence/opportunity/portfolio/order/model/research views, local API, public archive monitoring and deterministic scenario runner |

All simulated orders require a valid, immutable, expiring risk approval. Evidence, estimates, model approval and order creation must follow causal availability ordering. Unsupported execution, missing evidence, stale books, uncertainty, unknown fees and unavailable risk withhold action. Trading has no required daily volume, leverage, martingale or loss-chasing.

## Verification

```sh
uv run --frozen --extra dev pytest -q
uv run --frozen --extra dev ruff check backend tests
npm run build --prefix frontend
npx --prefix frontend playwright install chromium
npm test --prefix frontend
npm audit --prefix frontend --audit-level=high
```

Browser tests serve the production frontend build with their own backend on port18940, preserving the operational services. They never reuse another Neraium service. CI repeats contract, replay, strategy, risk, execution, concurrency, recovery, browser and dependency checks. Detailed evidence and limitations: [certification](docs/certification.md).

## Boundaries

This initial release is a local research platform. Calibration and backtest fixtures are synthetic; no real-market profitability has been established. BUY-only simulation, bounded public collection, a conservative maker approximation, and SQLite single-owner operation are deliberate limits. Historical order-book depth is not assumed. Long-running WebSocket soak tests, qualified real-label out-of-sample evaluation and production throughput certification remain future work. PostgreSQL multi-process operation and additional exchanges need separate engineering validation.

`PAPER_TRADING=true` and `LIVE_TRADING_ENABLED=false` are enforced at startup and in execution components. No wallets, transaction signing, deposits or live orders are included. Detached owner signatures authorize paper strategy activation only. See [security](SECURITY.md), [eligibility](docs/eligibility.md), [architecture](docs/architecture.md), [operations](docs/operations.md) and [roadmap](docs/roadmap.md).

### Independent sports event research (Phase 13)

The event view distinguishes prospective external-data NFL win/tie/loss research
forecasts from market-baseline records. Exact schedule/rule mappings, immutable
source snapshots, separate forecast journals and verified result checks preserve
provenance. These models are unvalidated research and have no trading authority.

```bash
uv run neraium-poly monitor --view events
```

See [Phase 13 readiness and actual observations](docs/phase13-readiness.md),
[architecture](docs/phase13-architecture.md) and
[source inventory](docs/phase13-sources.md). Historical certification and explicit
owner approval remain required; live financial trading remains disabled.

### Independent event and capacity research (Phase18)

Phase18 adds exact-rule independent crypto event-probability research, parent-disjoint
validation, default-deny evidence convergence and nonlinear liquidity-capacity scenarios.
Models remain uncalibrated research with no order authority. Actual managed archive budgets
are200GiBcollector/100GiBexperimental with a protected100GiBfilesystem reserve; originals
remain retained pending separate exact retention approval.

```bash
uv run neraium-poly monitor --view operations
uv run neraium-poly monitor --view edge
```

See [Phase18 readiness](docs/phase18-readiness.md), [architecture](docs/phase18-architecture.md),
[research findings](docs/phase18-research-findings.md),
[event-disjoint validation](docs/phase18-event-validation.md),
[capacity research](docs/phase18-high-conviction-and-capacity.md),
[storage](docs/phase18-storage-and-reliability.md) and
[retention proposal requiring separate approval](docs/phase18-retention-proposal.md).
No positive forecasting or trading advantage has been established.

### Phase 19

Bounded current-day discovery now supplements the broad feed with exact-rule markets
that have native two-sided books. Event forecasting remains research-only; calibration,
independent event review and certified approval requirements are unchanged.
See [actual results and blockers](docs/phase19-readiness.md). The read-only
`forecast-qualification` command requires explicit predeclared training/held-out cutoffs.

Phase 20: [forecast validation, controlled SII research and operational evidence](docs/phase20-readiness.md).

Phase 21: [verified-outcome readiness, causal calibration and latency evidence](docs/phase21-readiness.md).
