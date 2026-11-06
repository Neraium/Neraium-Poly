"""Real-module reusable workflow integration, including causal suppression."""

from datetime import timedelta

import pytest
from neraium_poly.contracts import MarketRelationship
from neraium_poly.data import EventStore
from neraium_poly.execution import ExecutionConfig, PaperBroker
from neraium_poly.intelligence import RelationshipEngine, RelationshipPolicy
from neraium_poly.risk import RiskEngine
from neraium_poly.strategy import HistogramCalibrator, LabeledForecast, ModelRegistry, ProtocolFeeModel
from neraium_poly.workflow import PaperWorkflow


@pytest.fixture
def pipeline(now):
    rows = []
    for i in range(100):
        at = now - timedelta(days=10, seconds=-i)
        rows.append(
            LabeledForecast(
                id=f"label{i}",
                timestamp=at,
                available_at=at,
                source="synthetic",
                market_id=f"historical{i}",
                event_id=f"event{i}",
                probability=0.4,
                outcome=int(i % 10 < 9),
                label_available_at=at + timedelta(hours=1),
            )
        )
    registry = ModelRegistry()
    mid = registry.register(HistogramCalibrator.fit(rows, now - timedelta(hours=1)))
    registry.approve(mid, "explicit-test-reviewer", now - timedelta(minutes=1))
    relationship = MarketRelationship(
        id="configured-edge",
        timestamp=now,
        available_at=now,
        source="externally-reviewed-fixture",
        market_ids=("m1", "m2"),
        kind="statistical",
        confidence=0.95,
    )
    risk = RiskEngine()
    broker = PaperBroker(risk, config=ExecutionConfig(latency_ms=0))
    store = EventStore()
    flow = PaperWorkflow(
        registry,
        mid,
        [relationship],
        RelationshipEngine(RelationshipPolicy(baseline_size=3, persistence_required=2)),
        risk,
        broker,
        store,
    )
    yield flow
    broker.close()
    risk.close()
    store.close()


def step(flow, market, book, now, i, shift=0):
    at = now + timedelta(seconds=i)
    left = market.model_copy(
        update={"id": f"market-left-{i}", "timestamp": at, "available_at": at, "probability": 0.4 + shift}
    )
    right = market.model_copy(
        update={
            "id": f"market-right-{i}",
            "timestamp": at,
            "available_at": at,
            "market_id": "m2",
            "token_id": "t2",
            "probability": 0.4,
        }
    )
    current_book = book.model_copy(
        update={"id": f"book-{i}", "timestamp": at, "available_at": at, "sequence": i + 1}
    )
    assert flow.ingest_market(left, at)
    assert flow.ingest_market(right, at)
    return flow.evaluate(current_book, at, ProtocolFeeModel(0.02)), current_book, at


def train(flow, market, book, now):
    for i in range(3):
        result, _, _ = step(flow, market, book, now, i)
        assert result.status == "suppressed" and result.intent is None


def test_real_workflow_evidence_model_risk_execution_archive(pipeline, market, book, now):
    flow = pipeline
    train(flow, market, book, now)
    first, _, _ = step(flow, market, book, now, 3, 0.15)
    assert first.status == "suppressed"
    result, current_book, at = step(flow, market, book, now, 4, 0.15)
    assert result.status == "submitted", result.reasons
    assert result.execution.status == "filled"
    assert result.execution.filled_quantity == 10
    assert result.risk_decision.approved and result.risk_decision.reservation_id
    assert (
        result.evidence[0].available_at
        <= result.estimate.timestamp
        <= result.opportunity.timestamp
        <= result.intent.timestamp
    )
    assert result.opportunity.fee_rate == 0.02
    assert len(flow.risk.positions(now=at)) == 1
    assert flow.risk.snapshot(now=at)["cash"] == pytest.approx(495.92)
    kinds = {entry["kind"] for entry in flow.store.replay()}
    assert {
        "MarketSnapshot",
        "OrderBookSnapshot",
        "MarketRelationship",
        "RelationshipEvidence",
        "ProbabilityEstimate",
        "TradingOpportunity",
        "OrderIntent",
        "RiskDecision",
        "ExecutionReport",
        "WorkflowContext",
        "WorkflowResult",
        "WorkflowModelApproval",
        "WorkflowIngestion",
    } <= kinds
    duplicate = flow.evaluate(current_book, at + timedelta(milliseconds=10), ProtocolFeeModel(0.02))
    assert duplicate == result
    assert len(flow.broker.history()) == 1


def test_risk_unavailable_never_calls_broker(pipeline, market, book, now, monkeypatch):
    flow = pipeline
    train(flow, market, book, now)
    step(flow, market, book, now, 3, 0.15)

    def unavailable(*args, **kwargs):
        raise RuntimeError("risk unavailable")

    def must_not_execute(*args, **kwargs):
        pytest.fail("broker called without risk")

    monkeypatch.setattr(flow.risk, "approve", unavailable)
    monkeypatch.setattr(flow.broker, "submit", must_not_execute)
    result, _, _ = step(flow, market, book, now, 4, 0.15)
    assert result.status == "error" and result.reasons == ("risk_engine_unavailable",)
    assert result.intent and not result.risk_decision and not result.execution
    assert flow.store.replay(kind="WorkflowResult")[-1]["record"]["status"] == "error"


def test_no_model_self_approval(pipeline, market, book, now):
    flow = pipeline
    flow.registry.approvals.clear()
    flow.registry.active_id = None
    train(flow, market, book, now)
    step(flow, market, book, now, 3, 0.15)
    result, _, _ = step(flow, market, book, now, 4, 0.15)
    assert result.status == "suppressed" and "model_not_explicitly_approved" in result.reasons
    assert not flow.registry.approvals and flow.registry.active_id is None
    assert not flow.broker.history()


def test_kill_switch_rejection_archived(pipeline, market, book, now):
    flow = pipeline
    train(flow, market, book, now)
    step(flow, market, book, now, 3, 0.15)
    flow.risk.kill_switch(True, now=now + timedelta(seconds=4))
    result, _, _ = step(flow, market, book, now, 4, 0.15)
    assert result.status == "rejected" and "kill_switch" in result.reasons
    assert result.risk_decision and not result.execution
    assert not flow.broker.history()


def test_missing_stale_future_and_unknown_fee_suppress(pipeline, market, book, now):
    flow = pipeline
    result = flow.evaluate(book, now, ProtocolFeeModel(0.02))
    assert result.reasons == ("missing_matching_market",)
    assert flow.ingest_market(market, now)
    result = flow.evaluate(book, now + timedelta(seconds=31), ProtocolFeeModel(0.02))
    assert result.reasons == ("stale_order_book",)
    new = book.model_copy(update={"id": "future-book", "available_at": now + timedelta(seconds=100)})
    assert flow.evaluate(new, now, ProtocolFeeModel(0.02)).reasons == ("future_input",)
    assert flow.evaluate(book, now, None).reasons == ("unknown_or_invalid_fee_schedule",)
    future = market.model_copy(update={"id": "future-market", "available_at": now + timedelta(seconds=100)})
    assert not flow.ingest_market(future, now)
    assert flow.markets[("polymarket", "t1")] == market


def test_durable_result_recovery_prevents_duplicate_order(pipeline, market, book, now):
    flow = pipeline
    train(flow, market, book, now)
    step(flow, market, book, now, 3, 0.15)
    result, current_book, at = step(flow, market, book, now, 4, 0.15)
    restarted = PaperWorkflow(
        flow.registry,
        flow.model_id,
        flow.relationships,
        RelationshipEngine(RelationshipPolicy(baseline_size=3, persistence_required=2)),
        flow.risk,
        flow.broker,
        flow.store,
    )
    for current in flow.markets.values():
        restarted.ingest_market(current, at)
    duplicate = restarted.evaluate(current_book, at + timedelta(milliseconds=1), ProtocolFeeModel(0.02))
    assert duplicate == result
    assert len(flow.broker.history()) == 1


def test_latency_orders_advance_with_risk_revalidation(pipeline, market, book, now):
    flow = pipeline
    flow.broker.config = ExecutionConfig(latency_ms=100)
    train(flow, market, book, now)
    step(flow, market, book, now, 3, 0.15)
    result, current_book, at = step(flow, market, book, now, 4, 0.15)
    assert result.execution.status == "open"
    report = flow.process_order(result.intent.client_order_id, current_book, at + timedelta(milliseconds=101))
    assert report.status == "filled"
    assert flow.store.replay(kind="ExecutionReport")[-1]["record"]["status"] == "filled"


def test_archive_failure_prevents_risk_and_execution(pipeline, market, book, now, monkeypatch):
    flow = pipeline
    train(flow, market, book, now)
    step(flow, market, book, now, 3, 0.15)
    append = flow.store.append

    def fail_intent(record):
        if type(record).__name__ == "OrderIntent":
            raise RuntimeError("audit unavailable")
        return append(record)

    monkeypatch.setattr(flow.store, "append", fail_intent)
    with pytest.raises(RuntimeError, match="audit"):
        step(flow, market, book, now, 4, 0.15)
    assert not flow.broker.history()
    assert flow.risk.snapshot(now=now + timedelta(seconds=4))["reserved"] == 0


def test_runtime_live_mode_change_suppressed(pipeline, market, book, now, monkeypatch):
    flow = pipeline
    flow.ingest_market(market, now)
    monkeypatch.setenv("LIVE_TRADING_ENABLED", "true")
    result = flow.evaluate(book, now, ProtocolFeeModel(0.02))
    assert result.status == "suppressed" and result.reasons == ("paper_mode_required",)
    assert not flow.broker.history()


def test_unrelated_outcome_tokens_do_not_block_selected_relationship(pipeline, market, book, now):
    flow = pipeline
    other = market.model_copy(update={"id": "other", "market_id": "unrelated", "token_id": "unrelated-yes"})
    flow.ingest_market(other, now)
    flow.ingest_market(other.model_copy(update={"id": "other-no", "token_id": "unrelated-no"}), now)
    train(flow, market, book, now)
    step(flow, market, book, now, 3, 0.15)
    result, _, _ = step(flow, market, book, now, 4, 0.15)
    assert result.status == "submitted"
