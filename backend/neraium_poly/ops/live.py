"""Persistent real-market coordinator; absence of validated research withholds orders.

All exchange traffic is public GET. No synthetic runtime is imported or executed.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import shutil
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock

from neraium_poly.contracts import MarketRelationship, MarketSnapshot, Record
from neraium_poly.data import EventStore, assess_book
from neraium_poly.execution import PaperBroker
from neraium_poly.intelligence import EvidenceContext, RelationshipEngine, RelationshipPolicy
from neraium_poly.risk import RiskEngine
from neraium_poly.settings import Settings
from neraium_poly.workflow import PaperWorkflow

from .live_config import LivePaperConfig
from .live_ledger import LiveLedger

log = logging.getLogger(__name__)


def identity(*parts):
    return hashlib.sha256(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()


class LiveCycle(Record):
    markets_scanned: int
    outcomes_observed: int
    books_received: int
    fresh_books: int
    evidence_qualified: int
    opportunities_qualified: int
    orders_submitted: int
    suppression_reasons: tuple[str, ...]


class LivePaperRuntime:
    def __init__(self, config: LivePaperConfig, *, adapter=None, validation=None, clock=None):
        Settings.from_env()
        from neraium_poly.data.operational import OperationalPolymarketAdapter
        from neraium_poly.validation import ValidationStore

        self.config = config
        self.clock = clock or (lambda: datetime.now(UTC))
        self.directory = config.data_dir.resolve()
        self.ledger = LiveLedger(self.directory)
        self._lock = RLock()
        try:
            self.events = EventStore(self.directory / "events.sqlite")
            self.risk = RiskEngine(str(self.directory / "risk.sqlite"), limits=config.risk_limits)
            self.broker = PaperBroker(self.risk, str(self.directory / "broker.sqlite"))
            self.validation = validation or ValidationStore(str(self.directory / "approval.sqlite"))
            self.adapter = adapter or OperationalPolymarketAdapter()
            self.engine = RelationshipEngine(
                RelationshipPolicy(
                    max_relationships=config.max_relationships, max_age_seconds=config.max_book_age_seconds
                )
            )
            saved = self.ledger.get("relationship_checkpoint")
            if saved:
                self.engine.restore(saved)
            self.markets = {
                m.token_id: m
                for m in (MarketSnapshot.model_validate(x) for x in self.ledger.get("markets", []))
            }
            self.prices = {
                m.token_id: m
                for m in (MarketSnapshot.model_validate(x) for x in self.ledger.get("prices", []))
            }
            self.relationships = {
                r.id: r
                for r in (MarketRelationship.model_validate(x) for x in self.ledger.get("relationships", []))
            }
            self.token_map = self.ledger.get("token_map", {})
            self.books = {}
            self.fees = {}
            self.workflow = None
            self.activation_id = None
            self.activation = None
            self.scan = self.ledger.get("scan", {})
            self.totals = self.ledger.get(
                "totals",
                {
                    "cycles": 0,
                    "books": 0,
                    "evaluations": 0,
                    "qualified_evidence": 0,
                    "qualified_opportunities": 0,
                    "orders": 0,
                },
            )
            self.last_discovery = None
            self.last_cycle = None
            self.last_success = None
            self.last_error = None
            self.started_at = self.clock()
            self.stopping = False
            self.offset = self.ledger.get("book_offset", 0)
            if hasattr(self.adapter, "discovery_offset"):
                self.adapter.discovery_offset = self.scan.get("next_offset", 0)
            self.working = False
            self.reconciliation = self.broker.reconcile(now=self.clock())
            if not self.reconciliation["consistent"]:
                self.risk.kill_switch(True, now=self.clock())
                self.last_error = "restart_reconciliation_failed"
        except BaseException:
            self.ledger.close()
            raise

    @property
    def suspended(self):
        return self.risk.snapshot(now=self.clock())["kill_switch"]

    def stop(self):
        with self._lock:
            self.risk.kill_switch(True, now=self.clock())

    def run_scenario(self):
        raise ValueError("Synthetic scenarios are disabled in the real-market coordinator")

    def _save(self):
        self.ledger.put("markets", [m.model_dump(mode="json") for m in self.markets.values()])
        self.ledger.put("prices", [m.model_dump(mode="json") for m in self.prices.values()])
        self.ledger.put("relationships", [r.model_dump(mode="json") for r in self.relationships.values()])
        self.ledger.put("token_map", self.token_map)
        self.ledger.put("relationship_checkpoint", self.engine.checkpoint())
        self.ledger.put("totals", self.totals)
        self.ledger.put("scan", self.scan)
        self.ledger.put("book_offset", self.offset)

    def _budget_ok(self):
        files = [p for p in self.directory.glob("events.sqlite*") if p.is_file()]
        size = sum(p.stat().st_size for p in files)
        return (
            size < self.config.max_archive_mb * 1024 * 1024
            and shutil.disk_usage(self.directory).free > self.config.min_free_disk_mb * 1024 * 1024
        )

    async def discover(self):
        from neraium_poly.data.operational import build_statistical_relationships

        now = self.clock()
        batch = await self.adapter.discover_bounded(
            max_markets=self.config.max_markets,
            page_size=self.config.page_size,
            max_pages=self.config.max_pages,
        )
        if not batch.markets:
            raise ValueError("No valid real market metadata returned")
        with self._lock:
            incoming = {m.token_id: m for m in batch.markets}
            # Keep metadata needed to reconcile existing positions even when a market leaves discovery.
            for position in self.risk.positions(now=now):
                if position.token_id in self.markets:
                    incoming.setdefault(position.token_id, self.markets[position.token_id])
            self.markets = incoming
            for m in batch.markets:
                self.events.append(m)
            generated, token_map = build_statistical_relationships(
                batch.markets, now, max_pairs=self.config.max_relationships
            )
            active_ids = {r.id for r in generated}
            if self.activation:
                active_ids.update(r.id for r in self.activation.relationships)
            self.relationships = {
                key: value for key, value in self.relationships.items() if key in active_ids
            }
            self.engine.retain(active_ids)
            for relationship in generated:
                self.relationships.setdefault(relationship.id, relationship)
                if len(self.relationships) > self.config.max_relationships:
                    self.relationships.pop(relationship.id, None)
                    continue
                self.engine.graph.add(self.relationships[relationship.id])
                self.events.append(self.relationships[relationship.id])
            self.token_map.update(token_map)
            self.scan = {
                "markets_scanned": batch.scanned_count,
                "discovered_markets": len({m.market_id for m in batch.markets}),
                "outcomes": len(batch.markets),
                "bounded": batch.truncated,
                "next_offset": batch.next_offset,
                "errors": list(batch.errors),
                "at": now.isoformat(),
            }
            self.last_discovery = now
            self._save()

    def _book_market(self, book):
        market = self.markets.get(book.token_id)
        if market is None or not book.bids or not book.asks:
            return None
        old = self.prices.get(book.token_id)
        # Repeated receipt of the same exchange state cannot inflate temporal evidence.
        if old and book.timestamp <= old.timestamp:
            return old
        values = market.model_dump()
        values.update(
            id=identity(
                "clob-observation",
                book.exchange,
                book.token_id,
                book.timestamp.isoformat(),
                [(p.price, p.size) for p in book.bids],
                [(p.price, p.size) for p in book.asks],
            ),
            timestamp=book.timestamp,
            available_at=book.available_at,
            source="https://clob.polymarket.com/book:observed-midpoint",
            probability=(book.bids[0].price + book.asks[0].price) / 2,
        )
        observed = MarketSnapshot.model_validate(values)
        self.prices[book.token_id] = observed
        self.events.append(observed)
        return observed

    def _intelligence(self, now):
        evidence = []
        for relationship in self.relationships.values():
            selected = {}
            related_books = []
            for mid in relationship.market_ids:
                token = self.token_map.get(mid)
                if token in self.prices:
                    selected[mid] = self.prices[token]
                if token in self.books:
                    related_books.append(self.books[token])
            complete = len(related_books) == len(relationship.market_ids) and all(
                assess_book(b, now, max_age_seconds=self.config.max_book_age_seconds).healthy
                for b in related_books
            )
            liquidity = min((sum(p.price * p.size for p in b.asks) for b in related_books), default=0)
            spread = max(
                (b.asks[0].price - b.bids[0].price for b in related_books if b.asks and b.bids), default=1
            )
            item = self.engine.observe(
                relationship,
                selected,
                now,
                EvidenceContext(
                    complete=complete,
                    liquidity_usd=liquidity,
                    spread=spread,
                    source="real-polymarket-peer-books",
                    settlement_reviewed=False,
                ),
            )
            self.events.append(item)
            evidence.append(item)
        self.ledger.put("relationship_checkpoint", self.engine.checkpoint())
        return evidence

    def _activation(self, now):
        try:
            activation = self.validation.load_active(now)
        except (ValueError, KeyError, TypeError) as error:
            self.last_error = "strategy_activation_invalid:" + type(error).__name__
            activation = None
        if activation is None:
            self.workflow = None
            self.activation = None
            self.activation_id = None
            return
        activation_id = identity(activation.report_id, activation.approved_at.isoformat())
        if activation_id == self.activation_id:
            return
        # Only reviewed relationships are allowed to authorize trades. Automatically
        # discovered associations remain research observations, not approved scope.
        self.workflow = PaperWorkflow(
            activation.registry,
            activation.model_id,
            activation.relationships,
            self.engine,
            self.risk,
            self.broker,
            self.events,
            correlation_groups=activation.correlation_groups,
            settlement_reviews=activation.settlement_reviews,
            relationship_tokens=activation.relationship_tokens,
        )
        self.activation = activation
        self.activation_id = activation_id
        for market in self.prices.values():
            self.workflow.ingest_market(market, now)

    async def _advance_order(self, report, now):
        if report.status not in {"open", "partial"}:
            return
        row = self.broker.db.execute(
            "SELECT intent FROM orders WHERE client_id=?", (report.client_order_id,)
        ).fetchone()
        if row is None:
            return
        intent = json.loads(row[0])
        try:
            book = await self.adapter.book(intent["market_id"], intent["token_id"])
            with self._lock:
                self.events.append(book)
                updated = self.broker.process(report.client_order_id, book, now=self.clock())
                self.events.append(updated)
        except Exception as error:  # noqa: BLE001 - retain reservations; expiry remains enforced
            self.last_error = "pending_order_update_failed:" + type(error).__name__

    async def _evaluate(self, books, now):
        self.totals["evaluations"] += len(books)
        with self._lock:
            self._activation(now)
        if self.workflow is None:
            return ["no_approved_real_market_strategy"]
        if self.config.position_tier not in self.activation.allowed_tiers:
            return ["position_tier_not_approved"]
        reasons = []
        for book in books:
            now = self.clock()
            if not assess_book(book, now, max_age_seconds=self.config.max_book_age_seconds).healthy:
                reasons.append("stale_or_incomplete_execution_book")
                continue
            if self.activation.relationship_tokens.get(book.market_id) != book.token_id:
                reasons.append("instrument_outside_approved_scope")
                continue
            cached = self.fees.get(book.token_id)
            if cached and (now - cached[0]).total_seconds() < self.config.max_fee_age_seconds:
                fee = cached[1]
            else:
                fee = await self.adapter.fee_model(book.token_id)
                if fee is not None:
                    self.fees[book.token_id] = (self.clock(), fee)
            with self._lock:
                self._activation(self.clock())
                if self.workflow is None:
                    reasons.append("strategy_revoked_or_expired")
                    break
                for market in self.prices.values():
                    self.workflow.ingest_market(market, self.clock())
                qty = self.config.position_notional / book.asks[0].price
                result = self.workflow.evaluate(
                    book, self.clock(), fee_model=fee, quantity=qty, tier=self.config.position_tier
                )
                if result.opportunity:
                    self.totals["qualified_opportunities"] += 1
                if result.execution and result.execution.status != "rejected":
                    self.totals["orders"] += 1
                reasons.extend(result.reasons)
            if result.execution and result.execution.status in {"open", "partial"}:
                await asyncio.sleep(self.broker.config.latency_ms / 1000)
                await self._advance_order(result.execution, self.clock())
        return sorted(set(reasons))[:30]

    async def _settle(self, now):
        for position in self.risk.positions(now=now):
            market = self.markets.get(position.token_id)
            if market is None:
                continue
            result = await self.adapter.settlement(market)
            if result is None:
                continue
            self.events.append(result)
            if (
                not self.config.allow_simulated_settlement
                or not self.config.settlement_review_actor.strip()
                or self.config.settlement_rule_hashes.get(market.token_id)
                != identity(
                    market.market_id,
                    market.token_id,
                    market.outcome,
                    market.resolution_rules,
                    market.resolution_source,
                )
            ):
                self.last_error = "settlement_withheld_unreviewed_rules"
                continue
            self.risk.settle(
                position.token_id,
                result.payout,
                now=self.clock(),
                rules_verified=True,
                resolution_source=result.resolution_source,
            )

    async def cycle(self):
        Settings.from_env()
        now = self.clock()
        if not self._budget_ok():
            self.last_error = "archive_or_disk_budget_exhausted"
            return
        self.working = True
        try:
            if (
                self.last_discovery is None
                or (now - self.last_discovery).total_seconds() >= self.config.discovery_interval_seconds
            ):
                await self.discover()
            markets = sorted(self.markets.values(), key=lambda m: (m.market_id, m.token_id))
            if not markets:
                raise ValueError("no markets available")
            chosen = [
                markets[(self.offset + i) % len(markets)]
                for i in range(min(len(markets), self.config.books_per_cycle))
            ]
            self.offset = (self.offset + len(chosen)) % len(markets)
            received = []
            failures = []
            for market in chosen:
                try:
                    book = await self.adapter.book(market.market_id, market.token_id)
                    with self._lock:
                        self.events.append(book)
                        self.books[book.token_id] = book
                        self._book_market(book)
                    received.append(book)
                except Exception as error:  # noqa: BLE001 - individual public-data failure withholds that instrument
                    failures.append(f"book_unavailable:{market.market_id}:{type(error).__name__}")
            now = self.clock()
            before_opportunities = self.totals["qualified_opportunities"]
            before_orders = self.totals["orders"]
            with self._lock:
                evidence = self._intelligence(now)
                marks = {
                    token: book.bids[0].price
                    for token, book in self.books.items()
                    if book.bids
                    and assess_book(book, now, max_age_seconds=self.config.max_book_age_seconds).healthy
                }
                self.risk.mark(marks, now=now)
                self.broker.expire(now=now)
                self.totals["books"] += len(received)
                self.totals["qualified_evidence"] += sum(e.qualified for e in evidence)
            reasons = await self._evaluate(received, now)
            for report in self.broker.history():
                await self._advance_order(report, self.clock())
            await self._settle(self.clock())
            with self._lock:
                self.reconciliation = self.broker.reconcile(now=self.clock())
                if not self.reconciliation["consistent"]:
                    self.risk.kill_switch(True, now=self.clock())
                    failures.append("ledger_reconciliation_failed")
                self.totals["cycles"] += 1
                record = LiveCycle(
                    timestamp=self.clock(),
                    available_at=self.clock(),
                    source="real-polymarket-paper-coordinator",
                    markets_scanned=len({m.market_id for m in markets}),
                    outcomes_observed=len(markets),
                    books_received=len(received),
                    fresh_books=sum(
                        assess_book(b, self.clock(), max_age_seconds=self.config.max_book_age_seconds).healthy
                        for b in received
                    ),
                    evidence_qualified=sum(e.qualified for e in evidence),
                    opportunities_qualified=self.totals["qualified_opportunities"] - before_opportunities,
                    orders_submitted=self.totals["orders"] - before_orders,
                    suppression_reasons=tuple(sorted(set(reasons + failures))[:40]),
                )
                self.events.append(record)
                self.last_cycle = record.model_dump(mode="json")
                self.last_success = self.clock() if received else self.last_success
                self.last_error = ",".join(failures[:3]) if failures else None
                self._save()
                log.info("cycle %s", json.dumps(self.last_cycle))
        finally:
            self.working = False

    async def run(self, should_stop=lambda: False):
        while not self.stopping and not should_stop():
            try:
                await self.cycle()
            except Exception as error:
                self.last_error = "cycle_failed:" + type(error).__name__
                log.exception("paper coordinator cycle withheld")
            for _ in range(max(1, int(self.config.cycle_interval_seconds))):
                if self.stopping or should_stop():
                    break
                await asyncio.sleep(1)

    def _latest(self, kind, limit=100):
        with self.events._lock:
            rows = self.events.connection.execute(
                "SELECT payload,digest FROM events WHERE kind=? ORDER BY available_at DESC,id DESC LIMIT ?",
                (kind, limit),
            ).fetchall()
        result = []
        for payload, digest in rows:
            if hashlib.sha256(payload.encode()).hexdigest() != digest:
                raise ValueError("corrupt archived record")
            result.append(json.loads(payload))
        return result

    def health(self):
        now = self.clock()
        age = (now - self.last_success).total_seconds() if self.last_success else None
        return {
            "status": "ok"
            if age is not None
            and age < max(60, self.config.books_per_cycle * 0.5)
            and self.last_error is None
            else "degraded",
            "paper_trading": True,
            "live_trading_enabled": False,
            "mode": "live_market_paper",
            "trading_status": "suspended"
            if self.suspended
            else ("active" if self.workflow else "validation_blocked"),
            "last_ingestion_at": self.last_success.isoformat() if self.last_success else None,
            "last_ingestion_age_seconds": age,
            "last_error": self.last_error,
            "ledger_consistent": self.reconciliation["consistent"],
            "timestamp": now.isoformat(),
        }

    def state(self):
        with self._lock:
            now = self.clock()
            account = self.risk.snapshot(now=now)
            validation = self.validation.status(now)
            orders = [r.model_dump(mode="json") for r in self.broker.history()]
            alerts = []
            if self.workflow is None:
                alerts.append(
                    "Paper trading withheld: no approved real-market strategy with valid out-of-sample evidence."
                )
            if self.last_error:
                alerts.append(self.last_error)
            if self.suspended:
                alerts.append("Persistent emergency stop active.")
            healthy = sum(
                assess_book(b, now, max_age_seconds=self.config.max_book_age_seconds).healthy
                for b in self.books.values()
            )
            settlements = [a for a in self.risk.audit() if a["action"] == "simulated_settlement"]
            return {
                "mode": "live_market_paper",
                "scenario": "Live Polymarket · paper execution gated by real-strategy validation",
                "generated_at": now.isoformat(),
                "bankroll": account["equity"],
                "initial_bankroll": self.config.risk_limits.bankroll,
                "cash": account["cash"],
                "exposure": account["exposure"],
                "reserved": account["reserved"],
                "simulated_pnl": account["equity"] - self.config.risk_limits.bankroll,
                "simulated_realized_pnl": account["realized_pnl"],
                "realized_pnl": 0,
                "suspended": account["kill_switch"],
                "markets": [m.model_dump(mode="json") for m in self.markets.values()],
                "relationships": [r.model_dump(mode="json") for r in self.relationships.values()],
                "evidence": self._latest("RelationshipEvidence"),
                "opportunities": self._latest("TradingOpportunity"),
                "positions": [p.model_dump(mode="json") for p in self.risk.positions(now=now)],
                "orders": orders,
                "risk_decisions": self._latest("RiskDecision"),
                "models": [p.model_dump(mode="json") for p in self.activation.registry.approvals.values()]
                if self.activation
                else [],
                "performance": self._latest("StrategyPerformance"),
                "backtests": [validation["latest_report"]] if validation.get("latest_report") else [],
                "alerts": alerts,
                "limits": self.risk.limits.model_dump(),
                "health": [
                    {
                        "component": "Public Polymarket REST",
                        "status": self.health()["status"],
                        "detail": f"{len(self.markets)} outcomes; {healthy}/{len(self.books)} fresh books; real source timestamps enforced",
                    },
                    {
                        "component": "Strategy approval",
                        "status": "approved" if self.workflow else "withheld",
                        "detail": json.dumps(validation, default=str),
                    },
                    {
                        "component": "Risk / broker ledgers",
                        "status": "consistent" if self.reconciliation["consistent"] else "inconsistent",
                        "detail": "Persistent bankroll, reservations and execution audit",
                    },
                    {
                        "component": "Live order submission",
                        "status": "disabled",
                        "detail": "No wallet, signer or live broker transport",
                    },
                ],
                "operation": {
                    **self.totals,
                    "scan": self.scan,
                    "last_cycle": self.last_cycle,
                    "fresh_books": healthy,
                    "current_books": len(self.books),
                    "validation": validation,
                    "settlements": len(settlements),
                    "fills": len(
                        [
                            a
                            for a in self.broker.db.execute(
                                "SELECT action FROM audit WHERE action='fill_ack'"
                            )
                        ]
                    ),
                    "service": self.health(),
                },
                "settlements": settlements,
                "replay_digest": identity(self.totals, self.scan),
            }

    async def close(self):
        self.stopping = True
        with self._lock:
            self._save()
        await self.adapter.close()
        self.validation.close()
        self.broker.close()
        self.risk.close()
        self.events.close()
        self.ledger.close()


async def serve_live(config: LivePaperConfig):
    import uvicorn

    from .api import create_app

    runtime = LivePaperRuntime(config)
    app = create_app(runtime=runtime, frontend_path=Path("frontend/dist"))
    server = uvicorn.Server(uvicorn.Config(app, host=config.host, port=config.port, log_level="info"))
    try:
        await asyncio.gather(server.serve(), runtime.run(lambda: server.should_exit))
    finally:
        await runtime.close()
