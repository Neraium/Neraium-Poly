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
from neraium_poly.research.archive import QuoteArchive
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
        self.archive_fault = None
        try:
            if config.archive_management_enabled:
                from neraium_poly.data.segmented import ManagedEventStore

                self.events = ManagedEventStore(
                    self.directory / "events.sqlite",
                    segment_bytes=config.archive_segment_mb * 1024**2,
                    budget_bytes=config.archive_budget_mb * 1024**2,
                    min_free_bytes=max(8192, config.min_free_disk_mb, config.archive_reserve_disk_mb) * 1024**2,
                    compress=config.archive_compression_enabled,
                    cold_verification_enabled=config.archive_cold_verification_enabled,
                    clock=self.clock,
                )
            else:
                self.events = EventStore(self.directory / "events.sqlite")
                self.events.connection.execute(
                    "CREATE INDEX IF NOT EXISTS events_kind_time ON events(kind,available_at)"
                )
                self.events.connection.commit()
            self.risk = RiskEngine(str(self.directory / "risk.sqlite"), limits=config.risk_limits)
            self.broker = PaperBroker(self.risk, str(self.directory / "broker.sqlite"))
            self.validation = validation or ValidationStore(
                str(self.directory / "approval.sqlite"), owner_public_key=config.owner_public_key
            )
            self.coverage = None
            if adapter is None and config.coverage_enabled:
                from neraium_poly.data.connectivity import CoverageFeed

                self.coverage = CoverageFeed(
                    max_tokens=config.max_subscription_tokens,
                    concurrency=config.collection_concurrency,
                    rate=config.request_rate,
                    queue_size=config.stream_queue_size,
                )
                self.adapter = self.coverage.adapter
            else:
                self.adapter = adapter or OperationalPolymarketAdapter()
            self.quote_archive = QuoteArchive(self.events, self.ledger.get("quote_archive", {}))
            self.stream_notifications = 0
            self.stream_generation = 0
            self._stream_identity = None
            self._stream_task = None
            self.last_research = None
            self.engine = RelationshipEngine(
                RelationshipPolicy(
                    max_relationships=config.max_relationships, max_age_seconds=config.max_book_age_seconds
                )
            )
            saved = self.ledger.get("relationship_checkpoint")
            if saved:
                self.engine.restore(saved)
            self.trade_engine = RelationshipEngine(self.engine.policy)
            saved_trade = self.ledger.get("workflow_relationship_checkpoint")
            if saved_trade:
                self.trade_engine.restore(saved_trade)
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
            self.order_activations = self.ledger.get("order_activations", {})
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
            self.last_receipt = None
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
            for name in ("events", "broker", "risk", "validation"):
                resource = getattr(self, name, None)
                if resource is not None and hasattr(resource, "close"):
                    try:
                        resource.close()
                    except Exception:  # Preserve the original startup failure.
                        log.exception("startup_resource_cleanup_failed:%s", name)
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
        self.ledger.put("workflow_relationship_checkpoint", self.trade_engine.checkpoint())
        self.ledger.put("totals", self.totals)
        self.ledger.put("scan", self.scan)
        self.ledger.put("book_offset", self.offset)
        self.ledger.put("quote_archive", self.quote_archive.state)
        self.ledger.put("order_activations", self.order_activations)

    def _budget_ok(self):
        if self.config.archive_management_enabled:
            if self.archive_fault:
                return False
            try:
                return self.events.can_write() if hasattr(self.events, "can_write") else self._archive_status()["health"] == "ok"
            except Exception as error:  # noqa: BLE001 - deny ingestion if archive accounting fails
                self.archive_fault = f"archive_budget:{type(error).__name__}:{str(error)[:160]}"
                return False
        files = [p for p in self.directory.glob("events.sqlite*") if p.is_file()]
        size = sum(p.stat().st_size for p in files)
        return (
            size < self.config.max_archive_mb * 1024 * 1024
            and shutil.disk_usage(self.directory).free > self.config.min_free_disk_mb * 1024 * 1024
        )

    def _archive_status(self):
        if not self.config.archive_management_enabled:
            return {"managed": False, "health": "legacy_budget", "budget_bytes": self.config.max_archive_mb * 1024**2,
                    "retention_policy": "append_only_no_rotation"}
        try:
            status = self.events.status()
        except Exception as error:  # noqa: BLE001 - a failed archive cannot grant write authority
            self.archive_fault = f"archive_status:{type(error).__name__}:{str(error)[:160]}"
            status = {"managed": True}
        if self.archive_fault:
            status.update(health="blocked", last_error=self.archive_fault)
        return status

    async def discover(self):
        from neraium_poly.data.operational import build_statistical_relationships

        now = self.clock()
        with self._lock:
            self._activation(now)
        if self.coverage and not self.config.rotate_liquid_universe:
            self.adapter.discovery_offset = 0
        discover = self.coverage.discover if self.coverage else self.adapter.discover_bounded
        batch = await discover(
            max_markets=self.config.max_markets,
            page_size=self.config.page_size,
            max_pages=self.config.max_pages,
        )
        if not batch.markets:
            raise ValueError("No valid real market metadata returned")
        approved_metadata = []
        if self.activation:
            from neraium_poly.data.polymarket import GAMMA, normalize_market

            for market_id in self.activation.relationship_tokens:
                raw = await self.adapter._get(GAMMA, f"/markets/{market_id}")
                approved_metadata.extend(normalize_market(raw, self.clock()))
        # Discovery observations become available after network completion.
        # Using the pre-request clock would wrongly suppress every real edge.
        now = self.clock()
        with self._lock:
            incoming = {m.token_id: m for m in batch.markets}
            for approved in approved_metadata:
                incoming[approved.token_id] = approved
            # Keep metadata needed to reconcile existing positions even when a market leaves discovery.
            for position in self.risk.positions(now=now):
                if position.token_id in self.markets:
                    incoming.setdefault(position.token_id, self.markets[position.token_id])
            self.markets = incoming
            retained_tokens = set(incoming)
            self.prices = {key: value for key, value in self.prices.items() if key in retained_tokens}
            self.books = {key: value for key, value in self.books.items() if key in retained_tokens}
            self.fees = {key: value for key, value in self.fees.items() if key in retained_tokens}
            self.quote_archive.retain(retained_tokens)
            self.token_map = {key: value for key, value in self.token_map.items() if value in retained_tokens}
            for m in (*batch.markets, *approved_metadata):
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
                if relationship.id not in self.relationships:
                    # A liquid-universe edge can disappear and re-enter later.
                    # Its stable identity retains the original immutable definition.
                    archived = self.events.get(relationship.id)
                    if archived is not None:
                        kind, payload, digest = archived
                        if (
                            kind != "MarketRelationship"
                            or hashlib.sha256(payload.encode()).hexdigest() != digest
                        ):
                            raise ValueError("invalid archived relationship definition")
                        original = MarketRelationship.model_validate_json(payload)
                        excluded = {"timestamp", "available_at"}
                        if original.model_dump(exclude=excluded) != relationship.model_dump(exclude=excluded):
                            raise ValueError("relationship semantics changed without versioned identity")
                        relationship = original
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
                "selection_order": "volume24hr_desc" if self.coverage else "active_market_id_pages",
                "errors": list(batch.errors),
                "at": now.isoformat(),
            }
            self.last_discovery = now
            self._save()
        if self.coverage and self.config.websocket_enabled:
            stream_identity = frozenset((m.exchange, m.market_id, m.token_id) for m in self.markets.values())
            if (self._stream_identity != stream_identity or self._stream_task is None
                or self._stream_task.done()):
                await self.coverage.stop_stream()
                self.stream_generation += 1
                self._stream_task = self.coverage.start_stream(list(self.markets.values()), self._stream_observed)
                self._stream_identity = stream_identity
            else:
                # Metadata refresh is not a subscription change. Preserve valid native
                # baselines and in-flight recovery; restart only a changed/failed stream.
                self.coverage.set_markets(list(self.markets.values()))

    def _stream_observed(self, book):
        # Native updates are sampled from authoritative feed.latest in cycle().
        # This callback never writes an unbounded tick stream to disk.
        self.stream_notifications += 1
        self.last_receipt = self.clock()
        if assess_book(book, self.clock(), max_age_seconds=self.config.max_book_age_seconds).healthy:
            self.last_success = self.clock()

    def _current_books(self):
        return dict(self.coverage.latest) if self.coverage else dict(self.books)

    def _archive_observation(self, book):
        if not self._budget_ok():
            self.last_error = "archive_or_disk_budget_exhausted"
            return False
        return self.quote_archive.record(book)

    def _refresh_research(self):
        now = self.clock()
        if (
            self.last_research
            and (now - self.last_research).total_seconds() < self.config.research_interval_seconds
        ):
            return
        self.last_research = now
        path = self.config.research_bundle_path
        if path is None or self.config.research_report_path is None or not (path / "bundle.json").is_file():
            return
        from neraium_poly.research.evaluation import write_report
        from neraium_poly.research.history import load_bundle

        try:
            bundle = load_bundle(path)
            self.config.research_report_path.parent.mkdir(parents=True, exist_ok=True)
            write_report(bundle, self.config.research_report_path)
        except (OSError, ValueError, KeyError, TypeError):
            self.last_error = "research_report_withheld_invalid_evidence"

    def _book_market(self, book):
        market = self.markets.get(book.token_id)
        if market is None or (book.market_id, book.token_id, book.exchange) != (
            market.market_id,
            market.token_id,
            market.exchange,
        ):
            raise ValueError("order book instrument identity mismatch")
        if not book.bids or not book.asks:
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
            source=book.source + ":observed-midpoint",
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
        self.ledger.put("workflow_relationship_checkpoint", self.trade_engine.checkpoint())
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
        if len(activation.relationship_tokens) > self.config.max_markets:
            self.workflow = None
            self.activation = None
            self.last_error = "approved_scope_exceeds_bounded_universe"
            return
        self.trade_engine.retain({r.id for r in activation.relationships})
        self.workflow = PaperWorkflow(
            activation.registry,
            activation.model_id,
            activation.relationships,
            self.trade_engine,
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
        with self._lock:
            self._activation(self.clock())
            market = self.markets.get(intent["token_id"])
            if (
                self.workflow is None
                or self.activation.relationship_tokens.get(intent["market_id"]) != intent["token_id"]
                or intent["tier"] not in self.activation.allowed_tiers
                or self.order_activations.get(report.client_order_id) != self.activation_id
                or market is None
                or market.status != "active"
                or (market.end_time is not None and market.end_time <= self.clock())
            ):
                self.events.append(self.broker.cancel(report.client_order_id, now=self.clock()))
                return
        try:
            book = (
                await self.coverage.execution_book(intent["token_id"])
                if self.coverage
                else await self.adapter.book(intent["market_id"], intent["token_id"])
            )
            if self.coverage:
                book = self.coverage.latest.get(intent["token_id"])
            if book is None:
                self.events.append(self.broker.cancel(report.client_order_id, now=self.clock()))
                return
            with self._lock:
                self._activation(self.clock())
                if (
                    self.workflow is None
                    or self.activation.relationship_tokens.get(intent["market_id"]) != intent["token_id"]
                    or intent["tier"] not in self.activation.allowed_tiers
                    or self.order_activations.get(report.client_order_id) != self.activation_id
                ):
                    self.events.append(self.broker.cancel(report.client_order_id, now=self.clock()))
                    return
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
            if self.coverage and book.source.startswith("wss:"):
                current = self.coverage.latest.get(book.token_id)
                if current is None:
                    reasons.append("websocket_gap_invalidated_quote")
                    continue
                book = current
                self._book_market(book)
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
                if self.coverage:
                    current = self.coverage.latest.get(book.token_id)
                    if current is None:
                        reasons.append("feed_gap_or_resolution_invalidated_quote")
                        continue
                    book = current
                    if not assess_book(
                        book, self.clock(), max_age_seconds=self.config.max_book_age_seconds
                    ).healthy:
                        reasons.append("stale_or_incomplete_execution_book_after_network")
                        continue
                    self._book_market(book)
                if (
                    self.activation.relationship_tokens.get(book.market_id) != book.token_id
                    or self.config.position_tier not in self.activation.allowed_tiers
                ):
                    reasons.append("strategy_scope_or_tier_changed")
                    continue
                for market in self.prices.values():
                    self.workflow.ingest_market(market, self.clock())
                qty = self.config.position_notional / book.asks[0].price
                result = self.workflow.evaluate(
                    book, self.clock(), fee_model=fee, quantity=qty, tier=self.config.position_tier
                )
                if result.execution:
                    self.order_activations[result.execution.client_order_id] = self.activation_id
                    self.ledger.put("order_activations", self.order_activations)
                self.totals["qualified_opportunities"] = self.events.count(kind="TradingOpportunity")
                self.totals["orders"] = self.broker.db.execute(
                    "SELECT count(*) FROM orders WHERE json_extract(report,'$.status') != 'rejected'"
                ).fetchone()[0]
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
            if (
                (result.market_id, result.token_id, result.event_id)
                != (market.market_id, market.token_id, market.event_id)
                or result.resolution_rules != market.resolution_rules
                or result.resolution_source != market.resolution_source
                or result.payout not in (0, 1)
                or not result.condition_id
                or not result.transaction_hash
            ):
                self.last_error = "settlement_observation_identity_or_rules_mismatch"
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
        if self.config.archive_management_enabled:
            try:
                self.events.maintain()
            except Exception as error:  # noqa: BLE001 - use the same stream stop as other storage faults
                self.archive_fault = f"archive_maintenance:{type(error).__name__}:{str(error)[:160]}"
        if not self._budget_ok():
            self.last_error = self._archive_status().get("last_error") if self.config.archive_management_enabled else "archive_or_disk_budget_exhausted"
            if self.coverage:
                await self.coverage.stop_stream()
            return
        self.working = True
        self.last_error = None
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
            self._refresh_research()
            received = []
            failures = []
            if self.coverage:
                await self.coverage.books(markets, limit=self.config.books_per_cycle)
                candidates = list(self.coverage.latest.values())
            else:
                candidates = []
                for market in chosen:
                    try:
                        candidates.append(await self.adapter.book(market.market_id, market.token_id))
                    except Exception as error:  # noqa: BLE001 - no quote is invented on a public-data failure
                        failures.append(f"book_unavailable:{market.market_id}:{type(error).__name__}")
            for book in candidates:
                try:
                    market = self.markets.get(book.token_id)
                    if market is None or (book.market_id, book.token_id, book.exchange) != (
                        market.market_id,
                        market.token_id,
                        market.exchange,
                    ):
                        raise ValueError("order book instrument identity mismatch")
                    with self._lock:
                        if self._archive_observation(book):
                            received.append(book)
                        self.books[book.token_id] = book
                        self.last_receipt = self.clock()
                        if assess_book(
                            book, self.clock(), max_age_seconds=self.config.max_book_age_seconds
                        ).healthy:
                            self.last_success = self.clock()
                        self._book_market(book)
                except Exception as error:  # noqa: BLE001 - withhold malformed or misrouted public evidence
                    failures.append(f"book_unavailable:{book.market_id}:{type(error).__name__}")
            if self.coverage:
                self.books = self._current_books()
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
                self.totals["qualified_evidence"] = self.events.count(kind="RelationshipEvidence", qualified=True)
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
                self.last_receipt = self.clock() if received else self.last_receipt
                self.last_success = (
                    self.clock()
                    if any(
                        assess_book(b, self.clock(), max_age_seconds=self.config.max_book_age_seconds).healthy
                        for b in received
                    )
                    else self.last_success
                )
                self.last_error = ",".join(failures[:3]) if failures else self.last_error
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
        return self.events.latest(kind, limit=limit)

    def market_frame(self):
        from neraium_poly.experimental.feed import market_frame

        return market_frame(self).model_dump(mode="json")

    def health(self):
        last_success = self.last_success
        now = self.clock()
        age = (now - last_success).total_seconds() if last_success else None
        return {
            "status": "ok"
            if age is not None
            and age < max(60, self.config.books_per_cycle * 0.5)
            and self.last_error is None
            and any(
                assess_book(b, now, max_age_seconds=self.config.max_book_age_seconds).healthy
                for b in self._current_books().values()
            )
            else "degraded",
            "paper_trading": True,
            "live_trading_enabled": False,
            "mode": "live_market_paper",
            "trading_status": "suspended"
            if self.suspended
            else ("active" if self.workflow else "validation_blocked"),
            "last_ingestion_at": last_success.isoformat() if last_success else None,
            "last_ingestion_age_seconds": age,
            "last_error": self.last_error,
            "ledger_consistent": self.reconciliation["consistent"],
            "timestamp": now.isoformat(),
        }

    def archive_state(self):
        """Small operational view without the historical-query/global-cycle lock."""
        account = self.risk.snapshot(now=self.clock())
        return {
            "mode": "live_market_paper", "generated_at": self.clock().isoformat(),
            "cash": account["cash"], "bankroll": account["equity"],
            "simulated_pnl": account["equity"] - self.config.risk_limits.bankroll,
            "suspended": account["kill_switch"], "archive": self._archive_status(),
            "operation": {"cycles": self.totals["cycles"], "scan": dict(self.scan),
                          "service": self.health(),
                          "connectivity": self.coverage.metrics() if self.coverage else {"ws_connected": False}},
            "scope": "archive health and current simulated capital; full event history remains in /api/state",
        }

    def operations_state(self):
        from neraium_poly.research.phase15.operations import add_capacity

        return add_capacity(self.archive_state(), service="collector", now=self.clock())

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
            view_books = self._current_books()
            from .research_view import research_view

            research = research_view(self.config.research_report_path, self.config.public_archive_report_path)
            healthy = sum(
                assess_book(b, now, max_age_seconds=self.config.max_book_age_seconds).healthy
                for b in self._current_books().values()
            )
            settlements = [a for a in self.risk.audit() if a["action"] == "simulated_settlement"]
            market_rows = []
            for token, metadata in self.markets.items():
                row = self.prices.get(token, metadata).model_dump(mode="json")
                book = view_books.get(token)
                row.update(
                    metadata_probability=metadata.probability,
                    best_bid=book.bids[0].price if book and book.bids else None,
                    best_ask=book.asks[0].price if book and book.asks else None,
                    ask_depth=book.asks[0].size if book and book.asks else None,
                    book_timestamp=book.timestamp.isoformat() if book else None,
                    book_age_seconds=(now - book.timestamp).total_seconds() if book else None,
                )
                market_rows.append(row)
            return {
                "mode": "live_market_paper",
                "archive": self._archive_status(),
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
                "markets": market_rows,
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
                "backtests": [
                    {
                        **validation["latest_report"],
                        "name": validation["latest_report"]["id"],
                        "samples": validation["latest_report"]["heldout_events"],
                        "pnl": validation["latest_report"]["simulated_pnl"],
                        "limitations": "Explicit validation screen; no future returns guarantee",
                    }
                ]
                if validation.get("latest_report")
                else [],
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
                "research": research,
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
                    "connectivity": self.coverage.metrics() if self.coverage else {"ws_connected": False},
                    "stream_notifications": self.stream_notifications,
                    "archive_representation": "sampled actual full states with exact quote-level deltas and receipt references",
                },
                "settlements": settlements,
                "replay_digest": identity(self.totals, self.scan),
            }

    async def close(self):
        self.stopping = True
        with self._lock:
            self._save()
        if self.coverage:
            await self.coverage.close()
        else:
            await self.adapter.close()
        self.validation.close()
        self.broker.close()
        self.risk.close()
        self.events.close()
        self.ledger.close()


async def serve_live(config: LivePaperConfig):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    import uvicorn

    from .api import create_app

    runtime = LivePaperRuntime(config)
    app = create_app(runtime=runtime, frontend_path=Path("frontend/dist"), local_port=config.port)
    server = uvicorn.Server(uvicorn.Config(app, host=config.host, port=config.port, log_level="info"))
    try:
        await asyncio.gather(server.serve(), runtime.run(lambda: server.should_exit))
    finally:
        await runtime.close()
