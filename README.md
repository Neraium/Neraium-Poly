# Neraium-Poly

**See Beyond the Signals.** An SII-inspired prediction-market research platform with evidence-qualified relationship intelligence, calibrated probability estimation, portfolio risk controls and paper execution. This is an independent implementation; it contains no proprietary Neraium-2.0 code.

Python modular monolith · React/TypeScript dashboard · versioned Pydantic contracts · SQLite research ledgers · public Polymarket data adapter.

## Integrated real-market paper service

The integrated coordinator runs at **http://127.0.0.1:18742** with persistent risk, broker and strategy ledgers:

```sh
uv run neraium-poly paper-live --config config/paper-live.example.json
uv run neraium-poly strategy-status --data-dir data/paper-live
```

It scans real public markets, feeds observed books into relationship intelligence, and evaluates the explicit real-strategy approval gate before any paper order. With no passing real-data report and named approval, it continues collection and records why trading is withheld. No strategy or probability estimate is fabricated to create activity. See [persistent operation](docs/live-paper-operation.md) and [validation requirements](docs/real-strategy-validation.md). The commands below remain separate synthetic research demonstrations.

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

This initial release is a local research platform. Calibration and backtest fixtures are synthetic; no real-market profitability has been established. BUY-only simulation, bounded public collection, a conservative maker approximation, and SQLite single-owner operation are deliberate limits. Historical order-book depth is not assumed. Long-running WebSocket soak tests, real-label out-of-sample evaluation and production throughput certification remain future work. PostgreSQL multi-process operation and additional exchanges need separate engineering validation.

`PAPER_TRADING=true` and `LIVE_TRADING_ENABLED=false` are enforced at startup and in execution components. No wallets, signing, deposits, live orders, deployment or infrastructure changes are included. See [security](SECURITY.md), [eligibility](docs/eligibility.md), [architecture](docs/architecture.md), [operations](docs/operations.md) and [roadmap](docs/roadmap.md).
