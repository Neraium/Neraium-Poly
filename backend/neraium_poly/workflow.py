"""Reusable synchronous, paper-only orchestration with an append-only audit.

No worker, exchange connection, inferred logical rule or automatic model approval
is started here. Callers provide causal observations and explicit dependencies.
"""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from hashlib import sha256
from math import isfinite
from threading import RLock
from typing import Literal

from pydantic import Field

from neraium_poly.contracts import (
    ExecutionReport,
    MarketRelationship,
    MarketSnapshot,
    ModelProvenance,
    OrderBookSnapshot,
    OrderIntent,
    ProbabilityEstimate,
    Record,
    RelationshipEvidence,
    RiskDecision,
    TradingOpportunity,
)
from neraium_poly.data import EventStore
from neraium_poly.execution import PaperBroker
from neraium_poly.intelligence import EvidenceContext, RelationshipEngine
from neraium_poly.risk import RiskEngine
from neraium_poly.strategy import FeeModel, ModelRegistry, OpportunityRanker


def _id(*parts: object) -> str:
    return sha256(repr(parts).encode()).hexdigest()


class WorkflowContext(Record):
    evaluation_key: str
    book_id: str
    market_ids: tuple[str, ...]
    relationship_ids: tuple[str, ...]
    liquidity_usd: float = Field(ge=0)
    spread: float = Field(ge=0)
    settlement_review_ids: tuple[str, ...]


class WorkflowModelApproval(Record):
    model: ModelProvenance


class WorkflowIngestion(Record):
    market_record_id: str
    accepted: bool
    reason: str


class WorkflowResult(Record):
    """Durable result; every suppression and external failure has a reason."""

    evaluation_key: str
    market_id: str
    book_id: str
    status: Literal["suppressed", "rejected", "submitted", "error"]
    reasons: tuple[str, ...] = ()
    evidence: tuple[RelationshipEvidence, ...] = ()
    estimate: ProbabilityEstimate | None = None
    opportunity: TradingOpportunity | None = None
    intent: OrderIntent | None = None
    risk_decision: RiskDecision | None = None
    execution: ExecutionReport | None = None


class PaperWorkflow:
    """A single-process research pipeline using durable risk/broker ledgers.

    Liquidity context is explicitly scoped to the target execution book; related
    market prices still require independent freshness and completeness checks.
    Logical settlement review is externally configured per relationship ID.
    The event store is required and written before risk/execution side effects.
    On construction, archived final results restore order idempotency. Market and
    relationship temporal state require explicit input replay by the caller.
    """

    def __init__(
        self,
        registry: ModelRegistry,
        model_id: str,
        relationships: Sequence[MarketRelationship],
        relationship_engine: RelationshipEngine,
        risk: RiskEngine,
        broker: PaperBroker,
        store: EventStore,
        *,
        ranker: OpportunityRanker | None = None,
        correlation_groups: Mapping[str, str] | None = None,
        settlement_reviews: Mapping[str, bool] | None = None,
        relationship_tokens: Mapping[str, str] | None = None,
        order_ttl_seconds: float = 30,
    ):
        self._paper_only()
        if not isinstance(broker, PaperBroker) or broker.risk is not risk:
            raise ValueError("paper broker and matching risk engine required")
        if not isfinite(order_ttl_seconds) or order_ttl_seconds <= 0:
            raise ValueError("invalid order expiry")
        if len({r.id for r in relationships}) != len(relationships):
            raise ValueError("duplicate relationship definitions")
        self.registry, self.model_id = registry, model_id
        self.relationships = tuple(relationships)
        self.engine, self.risk, self.broker, self.store = relationship_engine, risk, broker, store
        self.ranker = ranker or OpportunityRanker()
        self.correlation_groups = dict(correlation_groups or {})
        self.settlement_reviews = dict(settlement_reviews or {})
        self.relationship_tokens = dict(relationship_tokens or {})
        self.order_ttl_seconds = order_ttl_seconds
        self.markets: dict[tuple[str, str], MarketSnapshot] = {}
        self._lock = RLock()
        self._results: dict[str, WorkflowResult] = {}
        for relationship in self.relationships:
            self.engine.graph.add(relationship)
            self.store.append(relationship)
        # Recovery restores final decisions for idempotency. Baselines must be
        # explicitly replayed by callers from archived market/context records.
        for event in self.store.replay(kind="WorkflowResult"):
            result = WorkflowResult.model_validate(event["record"])
            self._results[result.evaluation_key] = result

    @staticmethod
    def _paper_only():
        if (
            os.getenv("PAPER_TRADING", "true").lower() != "true"
            or os.getenv("LIVE_TRADING_ENABLED", "false").lower() != "false"
        ):
            raise ValueError("paper execution is the only authorized mode")

    @staticmethod
    def _time(now: datetime):
        if now.tzinfo is None:
            raise ValueError("timezone-aware decision time required")

    def ingest_market(self, market: MarketSnapshot, now: datetime) -> bool:
        """Archive an observation; only available, monotonic observations activate."""
        self._time(now)
        with self._lock:
            self.store.append(market)
            key = (market.exchange, market.token_id)
            old = self.markets.get(key)
            reason = "accepted"
            if market.available_at > now:
                reason = "future_market_observation"
            elif old is not None and (market.available_at, market.timestamp, market.id) < (
                old.available_at,
                old.timestamp,
                old.id,
            ):
                reason = "out_of_order_market_observation"
            accepted = reason == "accepted"
            self.store.append(
                WorkflowIngestion(
                    id=_id("workflow-ingest/v1", market.id, now.isoformat(), reason),
                    timestamp=now,
                    available_at=now,
                    source="paper-workflow/v1",
                    market_record_id=market.id,
                    accepted=accepted,
                    reason=reason,
                )
            )
            if accepted:
                self.markets[key] = market
            return accepted

    def _finish(self, key, market_id, book, now, status, reasons, **records):
        result = WorkflowResult(
            id=_id("workflow-result/v1", key, status, now.isoformat(), tuple(reasons)),
            timestamp=now,
            available_at=now,
            source="paper-workflow/v1",
            evaluation_key=key,
            market_id=market_id,
            book_id=book.id,
            status=status,
            reasons=tuple(reasons),
            **records,
        )
        self.store.append(result)
        self._results[key] = result
        return result

    def evaluate(
        self,
        book: OrderBookSnapshot,
        now: datetime,
        fee_model: FeeModel | None,
        quantity: float = 10,
        tier: Literal["standard", "high", "exceptional"] = "standard",
    ) -> WorkflowResult:
        """Qualify evidence → estimate → opportunity → risk → paper submission.

        Repeated evaluation of the same immutable decision inputs returns its
        original archived result, never another order. New market observations
        or model approvals create a new decision. Call ``process_order`` to
        advance an already submitted order after simulated latency.
        """
        self._time(now)
        with self._lock:
            self.store.append(book)
            market = self.markets.get((book.exchange, book.token_id))
            market_id = book.market_id
            model = self.registry.approvals.get(self.model_id)
            # Explicit fee terms, not object identity or potentially unstable repr.
            fee_terms = None
            if fee_model is not None and book.asks:
                try:
                    fee_terms = (
                        fee_model.effective_notional_bound(),
                        tuple((p.price, fee_model.fee_per_share(p.price)) for p in book.asks),
                    )
                except (AttributeError, ValueError, TypeError, ArithmeticError):
                    fee_terms = "invalid"
            related = tuple(
                sorted((m.market_id, m.id) for m in self.markets.values() if m.exchange == book.exchange)
            )
            key = _id(
                "workflow-input/v1",
                book.id,
                related,
                self.model_id,
                model.model_dump_json() if model else None,
                quantity,
                tier,
                fee_terms,
                tuple(r.model_dump_json() for r in self.relationships),
                tuple(sorted(self.settlement_reviews.items())),
                tuple(sorted(self.correlation_groups.items())),
                tuple(sorted(self.relationship_tokens.items())),
            )
            if key in self._results:
                return self._results[key]
            try:
                self._paper_only()
            except ValueError:
                return self._finish(key, market_id, book, now, "suppressed", ("paper_mode_required",))
            if market is None or market.market_id != book.market_id:
                return self._finish(key, market_id, book, now, "suppressed", ("missing_matching_market",))
            if not isfinite(quantity) or quantity <= 0:
                return self._finish(key, market_id, book, now, "suppressed", ("invalid_quantity",))
            if fee_model is None or fee_terms == "invalid":
                return self._finish(
                    key, market_id, book, now, "suppressed", ("unknown_or_invalid_fee_schedule",)
                )
            scoped_token = self.relationship_tokens.get(market.market_id)
            if scoped_token is not None and scoped_token != book.token_id:
                return self._finish(
                    key, market_id, book, now, "suppressed", ("target_outcome_outside_reviewed_scope",)
                )
            if market.available_at > now or book.available_at > now:
                return self._finish(key, market_id, book, now, "suppressed", ("future_input",))
            if not book.complete or not book.bids or not book.asks:
                return self._finish(key, market_id, book, now, "suppressed", ("incomplete_order_book",))
            if (now - book.timestamp).total_seconds() > self.ranker.policy.max_age_seconds:
                return self._finish(key, market_id, book, now, "suppressed", ("stale_order_book",))
            relevant = [r for r in self.relationships if market.market_id in r.market_ids]
            if not relevant:
                return self._finish(key, market_id, book, now, "suppressed", ("no_configured_relationship",))
            snapshots = {market.market_id: market}
            for mid in sorted(
                {mid for relationship in relevant for mid in relationship.market_ids} - {market.market_id}
            ):
                candidates = [
                    m for m in self.markets.values() if m.exchange == market.exchange and m.market_id == mid
                ]
                selected_token = self.relationship_tokens.get(mid)
                if selected_token is not None:
                    candidates = [m for m in candidates if m.token_id == selected_token]
                if len(candidates) > 1:
                    return self._finish(
                        key, market_id, book, now, "suppressed", ("ambiguous_market_outcome_configuration",)
                    )
                if candidates:
                    snapshots[mid] = candidates[0]
            liquidity = sum(level.price * level.size for level in book.asks)
            spread = book.asks[0].price - book.bids[0].price
            context_record = WorkflowContext(
                id=_id("workflow-context/v1", key, now.isoformat()),
                timestamp=now,
                available_at=now,
                source="paper-workflow-target-book/v1",
                evaluation_key=key,
                book_id=book.id,
                market_ids=tuple(m.id for m in snapshots.values()),
                relationship_ids=tuple(r.id for r in relevant),
                liquidity_usd=liquidity,
                spread=spread,
                settlement_review_ids=tuple(
                    r.id for r in relevant if self.settlement_reviews.get(r.id, False)
                ),
            )
            self.store.append(context_record)
            evidence = []
            for relationship in relevant:
                context = EvidenceContext(
                    complete=all(mid in snapshots for mid in relationship.market_ids),
                    liquidity_usd=liquidity,
                    spread=spread,
                    settlement_reviewed=self.settlement_reviews.get(relationship.id, False),
                    source=f"target-book:{book.id}",
                )
                item = self.engine.observe(relationship, snapshots, now, context)
                self.store.append(item)
                evidence.append(item)
            qualified = tuple(item for item in evidence if item.qualified)
            if not qualified:
                return self._finish(
                    key,
                    market_id,
                    book,
                    now,
                    "suppressed",
                    ("no_qualified_relationship_evidence",),
                    evidence=tuple(evidence),
                )
            if model is None or self.registry.active_id != self.model_id:
                return self._finish(
                    key,
                    market_id,
                    book,
                    now,
                    "suppressed",
                    ("model_not_explicitly_approved",),
                    evidence=tuple(evidence),
                )
            self.store.append(
                WorkflowModelApproval(
                    id=_id("workflow-model-approval/v1", model.model_dump_json()),
                    timestamp=model.timestamp,
                    available_at=model.available_at,
                    source="paper-workflow/v1",
                    model=model,
                )
            )
            try:
                estimate = self.registry.estimate(self.model_id, market, now, tuple(e.id for e in qualified))
            except (ValueError, KeyError):
                return self._finish(
                    key,
                    market_id,
                    book,
                    now,
                    "suppressed",
                    ("model_unavailable_at_decision",),
                    evidence=tuple(evidence),
                )
            self.store.append(estimate)
            opportunity = self.ranker.rank(
                market, book, estimate, qualified, model, now, quantity, fee_model, tier=tier
            )
            if opportunity is None:
                return self._finish(
                    key,
                    market_id,
                    book,
                    now,
                    "suppressed",
                    self.ranker.last_reasons,
                    evidence=tuple(evidence),
                    estimate=estimate,
                )
            self.store.append(opportunity)
            intent = OrderIntent(
                id=_id("workflow-intent/v1", key),
                timestamp=now,
                available_at=now,
                source="paper-workflow/v1",
                client_order_id=_id("workflow-order/v1", key),
                market_id=market.market_id,
                token_id=market.token_id,
                event_id=market.event_id,
                opportunity_id=opportunity.id,
                side="BUY",
                limit_price=opportunity.market_probability,
                quantity=quantity,
                expires_at=now + timedelta(seconds=self.order_ttl_seconds),
                tier=opportunity.tier,
            )
            self.store.append(intent)
            payload = {
                "evidence": tuple(evidence),
                "estimate": estimate,
                "opportunity": opportunity,
                "intent": intent,
            }
            try:
                decision = self.risk.approve(
                    intent,
                    opportunity,
                    market,
                    book,
                    qualified,
                    now=now,
                    estimate=estimate,
                    model=model,
                    correlation_group=self.correlation_groups.get(market.market_id, "unclassified"),
                )
            except Exception:  # noqa: BLE001 - risk boundary: unavailability must never execute
                return self._finish(
                    key, market_id, book, now, "error", ("risk_engine_unavailable",), **payload
                )
            self.store.append(decision)
            payload["risk_decision"] = decision
            if not decision.approved:
                return self._finish(key, market_id, book, now, "rejected", decision.reasons, **payload)
            try:
                execution = self.broker.submit(intent, decision, book, now=now, fee_rate=opportunity.fee_rate)
            except Exception:  # noqa: BLE001 - external service boundary; reserve expires if release is unavailable
                release_failed = False
                if decision.reservation_id:
                    try:
                        self.risk.release(decision.reservation_id, now=now)
                    except Exception:  # noqa: BLE001 - ledger failure is an explicit audit reason
                        release_failed = True
                return self._finish(
                    key,
                    market_id,
                    book,
                    now,
                    "error",
                    ("paper_broker_unavailable", "reservation_release_unavailable")
                    if release_failed
                    else ("paper_broker_unavailable",),
                    **payload,
                )
            self.store.append(execution)
            return self._finish(
                key,
                market_id,
                book,
                now,
                "rejected" if execution.status == "rejected" else "submitted",
                (execution.reason,) if execution.reason else (),
                execution=execution,
                **payload,
            )

    def process_order(self, client_order_id: str, book: OrderBookSnapshot, now: datetime) -> ExecutionReport:
        """Advance an existing paper order; broker revalidates risk and freshness."""
        self._paper_only()
        self._time(now)
        with self._lock:
            self.store.append(book)
            report = self.broker.process(client_order_id, book, now=now)
            self.store.append(report)
            return report
