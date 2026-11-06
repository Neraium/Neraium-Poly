"""Synthetic reference workflow, using real subsystem interfaces and no network.

A fixture model is explicitly approved for this scenario alone. Research results
are not evidence of profitability in actual markets.
"""

import json
from datetime import UTC, datetime, timedelta
from hashlib import sha256

from neraium_poly.contracts import (
    MarketRelationship,
    MarketSnapshot,
    OrderBookSnapshot,
    OrderIntent,
    PriceLevel,
)
from neraium_poly.data import EventStore
from neraium_poly.intelligence import EvidenceContext, RelationshipEngine, RelationshipPolicy
from neraium_poly.risk import RiskEngine


class ResearchRuntime:
    def __init__(self):
        self.suspended = False
        self.risk = RiskEngine()
        self.store = EventStore()
        self.clock = datetime(2026, 11, 5, 12, tzinfo=UTC)
        self.records = {
            key: []
            for key in (
                "markets",
                "relationships",
                "evidence",
                "opportunities",
                "orders",
                "risk_decisions",
                "models",
                "performance",
                "backtests",
            )
        }

    def stop(self):
        self.suspended = True
        self.risk.kill_switch(True, now=self.clock)

    def _save(self, key, record):
        self.store.append(record)
        self.records[key].append(record.model_dump(mode="json"))

    def run_scenario(self):
        if self.suspended:
            raise ValueError("Emergency stop latched")
        from neraium_poly.execution import PaperBroker
        from neraium_poly.strategy import (
            HistogramCalibrator,
            LabeledForecast,
            ModelRegistry,
            OpportunityRanker,
            ProtocolFeeModel,
            walk_forward,
        )

        # Re-running a fixture replaces its isolated research session. It never
        # resets the emergency-stop latch or any persistent operational ledger.
        self.risk.close()
        self.store.close()
        self.risk = RiskEngine()
        self.store = EventStore()
        for key in self.records:
            self.records[key] = []
        base = self.clock.replace(second=0)
        cutoff = base - timedelta(hours=1)
        training = []
        for i in range(120):
            at = base - timedelta(days=2) + timedelta(minutes=i * 2)
            training.append(
                LabeledForecast(
                    id=f"train-{i}",
                    timestamp=at,
                    available_at=at,
                    source="synthetic-label-fixture",
                    market_id=f"train-market-{i}",
                    event_id=f"train-event-{i}",
                    probability=0.4,
                    outcome=int(i % 20 < 17),
                    label_available_at=at + timedelta(minutes=1),
                    executable_price=0.4,
                    executable_quantity=100,
                    protocol_fee_rate=0.02,
                )
            )
        model = HistogramCalibrator.fit(training, cutoff)
        registry = ModelRegistry()
        model_id = registry.register(model)
        approved = registry.approve(model_id, actor="explicit-synthetic-fixture-only", now=cutoff)
        self._save("models", approved)
        edge = MarketRelationship(
            id="fixture-statistical-edge",
            timestamp=base,
            available_at=base,
            source="fixture-ontology",
            market_ids=("fixture-a", "fixture-b"),
            kind="statistical",
            confidence=0.95,
            rule_description="Research association only; no enforceable pricing equality",
        )
        self._save("relationships", edge)
        engine = RelationshipEngine(RelationshipPolicy(baseline_size=20, persistence_required=3))
        for i in range(23):
            at = base + timedelta(seconds=i)
            pair = {}
            for mid, p in [("fixture-a", 0.4), ("fixture-b", 0.4 + (i % 2) * 0.002 if i < 20 else 0.6)]:
                market = MarketSnapshot(
                    id=f"{mid}-{i}",
                    timestamp=at,
                    available_at=at,
                    source="synthetic-market-fixture",
                    market_id=mid,
                    token_id=f"{mid}-yes",
                    event_id=f"{mid}-event",
                    question=f"Synthetic research outcome {mid[-1].upper()}?",
                    probability=p,
                    status="active",
                    resolution_rules="Pays YES only if the synthetic oracle resolves YES",
                    resolution_source="synthetic-fixture-oracle",
                )
                pair[mid] = market
                self.store.append(market)
            evidence = engine.observe(edge, pair, at, EvidenceContext(source="synthetic-reviewed-context"))
            self._save("evidence", evidence)
        now = base + timedelta(seconds=22)
        self.clock = now
        market = pair["fixture-a"]
        self.records["markets"] = [m.model_dump(mode="json") for m in pair.values()]
        book = OrderBookSnapshot(
            id="fixture-book",
            timestamp=now,
            available_at=now,
            source="synthetic-book-fixture",
            market_id=market.market_id,
            token_id=market.token_id,
            sequence=1,
            bids=(PriceLevel(price=0.39, size=100),),
            asks=(PriceLevel(price=0.4, size=100),),
        )
        self.store.append(book)
        estimate = registry.estimate(model_id, market, now, evidence_ids=(evidence.id,))
        self.store.append(estimate)
        ranker = OpportunityRanker()
        opportunity = ranker.rank(
            market,
            book,
            estimate,
            [evidence],
            approved,
            now,
            quantity=10,
            fee_model=ProtocolFeeModel(protocol_rate=0.02),
        )
        if opportunity is None:
            raise ValueError(f"Fixture opportunity suppressed: {ranker.last_reasons}")
        self._save("opportunities", opportunity)
        intent = OrderIntent(
            id="fixture-intent",
            timestamp=now,
            available_at=now,
            source="synthetic-strategy",
            client_order_id="fixture-paper-order",
            market_id=market.market_id,
            token_id=market.token_id,
            event_id=market.event_id,
            opportunity_id=opportunity.id,
            limit_price=0.4,
            quantity=10,
            expires_at=now + timedelta(seconds=9),
        )
        self.store.append(intent)
        decision = self.risk.approve(
            intent, opportunity, market, book, [evidence], now=now, estimate=estimate, model=approved
        )
        self._save("risk_decisions", decision)
        if not decision.approved:
            raise ValueError(f"Fixture risk rejected: {decision.reasons}")
        broker = PaperBroker(self.risk)
        report = broker.submit(intent, decision, book, now=now, fee_rate=opportunity.fee_rate)
        if report.status in {"open", "partial"}:
            report = broker.process(intent.client_order_id, book, now=now + timedelta(seconds=1))
        self._save("orders", report)
        self.clock = now + timedelta(seconds=1)
        self.risk.mark({market.token_id: 0.41}, now=now + timedelta(seconds=1))
        result = walk_forward(training, evaluation_end=cutoff)
        self._save("performance", result.performance)
        self.records["backtests"] = [
            {
                "name": "Synthetic event-purged walk-forward",
                "samples": len(result.predictions),
                "brier_score": result.performance.brier_score,
                "pnl": result.performance.simulated_pnl,
                "limitations": "Synthetic labels and quotes; no evidence of real-market returns",
            }
        ]
        broker.close()

    def state(self):
        account = self.risk.snapshot(now=self.clock)
        return {
            **self.records,
            "mode": "paper",
            "generated_at": self.clock.isoformat(),
            "scenario": "Deterministic synthetic research replay",
            "bankroll": account["equity"],
            "cash": account["cash"],
            "exposure": account["exposure"],
            "simulated_pnl": account["equity"] - 500,
            "realized_pnl": 0,
            "suspended": self.suspended,
            "positions": [p.model_dump(mode="json") for p in self.risk.positions(now=self.clock)],
            "limits": self.risk.limits.model_dump(),
            "alerts": [
                "Synthetic research data; no claim of real-market profitability.",
                "Public data collection is a separate bounded command; this view is a replay.",
            ]
            + (["Emergency stop latched."] if self.suspended else []),
            "health": [
                {
                    "component": "Public adapter",
                    "status": "available / not streaming",
                    "detail": "Run collect to archive public snapshots",
                },
                {
                    "component": "Research replay",
                    "status": "ready",
                    "detail": f"{self.store.count()} archived records",
                },
                {
                    "component": "Risk engine",
                    "status": "suspended" if self.suspended else "ready",
                    "detail": "Transactional paper reservations",
                },
                {
                    "component": "Live execution",
                    "status": "disabled",
                    "detail": "No live order transport implemented",
                },
            ],
            "replay_digest": sha256(json.dumps(self.store.replay(), sort_keys=True).encode()).hexdigest(),
        }
