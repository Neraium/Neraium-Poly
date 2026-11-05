from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from neraium_poly.contracts import (
    ModelProvenance,
    OrderIntent,
    ProbabilityEstimate,
    RelationshipEvidence,
    TradingOpportunity,
)
from neraium_poly.execution import ExecutionConfig, LiveBroker, PaperBroker
from neraium_poly.risk import RiskEngine, RiskViolation


def approved(now, market, book, risk, *, suffix="0", quantity=10, limit=0.4):
    evidence = RelationshipEvidence(
        id="e" + suffix,
        timestamp=now,
        available_at=now,
        source="fixture",
        relationship_id="r",
        sample_count=100,
        persistence=5,
        strength=0.2,
        confidence=0.9,
        qualified=True,
        observation_ids=("obs",),
    )
    model = ModelProvenance(
        id="model",
        timestamp=now - timedelta(days=1),
        available_at=now - timedelta(days=1),
        source="fixture",
        model_name="fixture",
        model_version="1",
        training_end=now - timedelta(days=2),
        artifact_hash="hash",
        approved=True,
        calibration_samples=100,
    )
    estimate = ProbabilityEstimate(
        id="estimate",
        timestamp=now,
        available_at=now,
        source="fixture",
        market_id=market.market_id,
        token_id=market.token_id,
        probability=0.7,
        lower=0.6,
        upper=0.8,
        model_id=model.id,
        calibrated=True,
        evidence_ids=(evidence.id,),
    )
    opportunity = TradingOpportunity(
        id="o" + suffix,
        timestamp=now,
        available_at=now,
        source="fixture",
        market_id=market.market_id,
        token_id=market.token_id,
        event_id=market.event_id,
        estimate_id=estimate.id,
        evidence_ids=(evidence.id,),
        market_probability=0.4,
        estimated_probability=0.7,
        conservative_probability=0.6,
        net_edge=0.18,
        fee_rate=0.02,
        slippage=0.002,
        liquidity=100,
        calibrated=True,
    )
    intent = OrderIntent(
        id="i" + suffix,
        timestamp=now,
        available_at=now,
        source="fixture",
        client_order_id="c" + suffix,
        market_id=market.market_id,
        token_id=market.token_id,
        event_id=market.event_id,
        opportunity_id=opportunity.id,
        limit_price=limit,
        quantity=quantity,
        expires_at=now + timedelta(minutes=1),
    )
    decision = risk.approve(
        intent, opportunity, market, book, [evidence], now=now, estimate=estimate, model=model
    )
    assert decision.approved, decision.reasons
    return intent, decision


def test_latency_fill_fees_idempotency(now, market, book):
    risk = RiskEngine()
    intent, decision = approved(now, market, book, risk)
    broker = PaperBroker(risk)
    assert broker.submit(intent, decision, book, now=now).status == "open"
    report = broker.process(intent.client_order_id, book, now=now + timedelta(milliseconds=100))
    assert report.status == "filled"
    assert report.filled_quantity == 10 and report.fees == pytest.approx(0.08)
    assert broker.submit(intent, decision, book, now=now) == report
    assert risk.snapshot(now=now)["cash"] == pytest.approx(495.92)
    assert broker.reconcile(now=now)["consistent"]


def test_partial_shared_liquidity_new_snapshot(now, market, book):
    risk = RiskEngine()
    broker = PaperBroker(risk, config=ExecutionConfig(latency_ms=0, participation_rate=0.05))
    intent, decision = approved(now, market, book, risk)
    first = broker.submit(intent, decision, book, now=now)
    assert first.status == "partial" and first.filled_quantity == 5
    assert broker.process(intent.client_order_id, book, now=now) == first
    second_intent, second_decision = approved(now, market, book, risk, suffix="1")
    assert broker.submit(second_intent, second_decision, book, now=now).filled_quantity == 0
    next_book = book.model_copy(
        update={
            "id": "new",
            "timestamp": now + timedelta(seconds=1),
            "available_at": now + timedelta(seconds=1),
            "sequence": 2,
        }
    )
    assert (
        broker.process(intent.client_order_id, next_book, now=now + timedelta(seconds=1)).status == "filled"
    )
    assert broker.reconcile(now=now)["consistent"]


def test_cancel_expire_and_kill(now, market, book):
    risk = RiskEngine()
    broker = PaperBroker(risk)
    intent, decision = approved(now, market, book, risk)
    broker.submit(intent, decision, book, now=now)
    assert broker.cancel(intent.client_order_id, now=now).status == "cancelled"
    assert risk.snapshot(now=now)["reserved"] == 0
    intent, decision = approved(now, market, book, risk, suffix="1")
    broker.submit(intent, decision, book, now=now)
    assert broker.expire(now=now + timedelta(seconds=11))[0].status == "expired"
    intent, decision = approved(now, market, book, risk, suffix="2")
    broker.submit(intent, decision, book, now=now)
    risk.kill_switch(True, now=now)
    assert broker.process(intent.client_order_id, book, now=now + timedelta(seconds=1)).status == "rejected"


def test_changed_duplicate_and_no_risk(now, market, book):
    risk = RiskEngine()
    broker = PaperBroker(risk)
    intent, decision = approved(now, market, book, risk)
    broker.submit(intent, decision, book, now=now)
    with pytest.raises(RiskViolation):
        broker.submit(intent.model_copy(update={"quantity": 11}), decision, book, now=now)
    with pytest.raises(RiskViolation):
        PaperBroker(None)
    with pytest.raises(RiskViolation):
        LiveBroker()


@pytest.mark.parametrize(
    "update",
    [{"complete": False}, {"asks": ()}, {"token_id": "wrong"}, {"available_at": None}, {"timestamp": None}],
)
def test_invalid_book_fail_closed(now, market, book, update):
    risk = RiskEngine()
    broker = PaperBroker(risk, config=ExecutionConfig(latency_ms=0))
    intent, decision = approved(now, market, book, risk)
    if "available_at" in update:
        update = {"available_at": now + timedelta(seconds=1)}
    if "timestamp" in update:
        update = {"timestamp": now - timedelta(seconds=60)}
    report = broker.submit(intent, decision, book.model_copy(update=update), now=now)
    assert report.status == "rejected"
    assert not risk.positions(now=now)


def test_risk_unavailable(now, market, book, monkeypatch):
    risk = RiskEngine()
    intent, decision = approved(now, market, book, risk)
    broker = PaperBroker(risk, config=ExecutionConfig(latency_ms=0))

    def unavailable(*args, **kwargs):
        raise ConnectionError("offline")

    monkeypatch.setattr(risk, "validate_approval", unavailable)
    assert broker.submit(intent, decision, book, now=now).status == "rejected"
    assert not risk.positions(now=now)


def test_fee_exceeds_approval_rejects_atomically(now, market, book):
    risk = RiskEngine()
    intent, decision = approved(now, market, book, risk)
    broker = PaperBroker(risk, config=ExecutionConfig(latency_ms=0))
    result = broker.submit(intent, decision, book, now=now, fee_rate=0.1)
    assert result.status == "rejected"
    assert risk.snapshot(now=now)["cash"] == 500


def test_recovery_after_risk_ack_crash(now, market, book, tmp_path, monkeypatch):
    risk = RiskEngine(str(tmp_path / "risk.sqlite"))
    intent, decision = approved(now, market, book, risk)
    path = str(tmp_path / "broker.sqlite")
    broker = PaperBroker(risk, path, ExecutionConfig(latency_ms=0))

    def crash(*args, **kwargs):
        raise SystemExit("simulated process crash after risk commit")

    monkeypatch.setattr(broker, "_finalize", crash)
    with pytest.raises(SystemExit):
        broker.submit(intent, decision, book, now=now)
    assert risk.snapshot(now=now)["cash"] == pytest.approx(495.92)
    broker.close()
    broker = PaperBroker(risk, path, ExecutionConfig(latency_ms=0))
    assert broker.reconcile(now=now + timedelta(seconds=20))["consistent"]
    assert broker.history()[0].status == "filled"
    assert risk.snapshot(now=now)["cash"] == pytest.approx(495.92)


def test_concurrent_idempotency_across_instances(now, market, book, tmp_path):
    risk = RiskEngine(str(tmp_path / "risk.sqlite"))
    intent, decision = approved(now, market, book, risk)
    brokers = [
        PaperBroker(risk, str(tmp_path / "broker.sqlite"), ExecutionConfig(latency_ms=0)) for _ in range(6)
    ]

    def execute(i):
        return brokers[i].submit(intent, decision, book, now=now)

    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(execute, range(6)))
    assert brokers[0].reconcile(now=now)["consistent"]
    assert risk.positions(now=now)[0].quantity == 10
    assert len(brokers[0].history()) == 1


def test_resting_maker_and_fees(now, market, book):
    risk = RiskEngine()
    # Approve at current executable price, then submit against a higher ask.
    intent, decision = approved(now, market, book, risk)
    resting = book.model_copy(update={"asks": (book.asks[0].model_copy(update={"price": 0.41}),)})
    broker = PaperBroker(risk, config=ExecutionConfig(latency_ms=0, maker_participation_rate=0.02))
    assert broker.submit(intent, decision, resting, now=now, maker=True).status == "open"
    later = book.model_copy(
        update={
            "id": "later",
            "sequence": 2,
            "timestamp": now + timedelta(seconds=1),
            "available_at": now + timedelta(seconds=1),
        }
    )
    report = broker.process(intent.client_order_id, later, now=now + timedelta(seconds=1))
    assert report.status == "partial" and report.filled_quantity == 2 and report.fees == 0


def test_live_environment_gate(monkeypatch):
    monkeypatch.setenv("LIVE_TRADING_ENABLED", "true")
    with pytest.raises(RiskViolation):
        PaperBroker(object())


def test_unknown_risk_ack_is_held_then_recovers(now, market, book, monkeypatch):
    risk = RiskEngine()
    intent, decision = approved(now, market, book, risk)
    broker = PaperBroker(risk, config=ExecutionConfig(latency_ms=0))
    original = risk.audit

    def unavailable():
        raise ConnectionError("audit temporarily unreachable")

    monkeypatch.setattr(risk, "audit", unavailable)
    report = broker.submit(intent, decision, book, now=now)
    assert report.reason == "risk_recovery_pending" and report.filled_quantity == 0
    assert not risk.positions(now=now)
    monkeypatch.setattr(risk, "audit", original)
    assert broker.process(intent.client_order_id, book, now=now).status == "filled"
    assert risk.positions(now=now)[0].quantity == 10


def test_lost_ack_after_commit_does_not_duplicate(now, market, book, monkeypatch):
    risk = RiskEngine()
    intent, decision = approved(now, market, book, risk)
    broker = PaperBroker(risk, config=ExecutionConfig(latency_ms=0))
    original = risk.record_fill

    def lost_ack(*args, **kwargs):
        original(*args, **kwargs)
        raise ConnectionError("committed but acknowledgement lost")

    monkeypatch.setattr(risk, "record_fill", lost_ack)
    report = broker.submit(intent, decision, book, now=now)
    assert report.status == "filled"
    assert risk.positions(now=now)[0].quantity == 10
    assert broker.reconcile(now=now)["consistent"]


def test_widening_spread_rejects_before_fill(now, market, book):
    risk = RiskEngine()
    intent, decision = approved(now, market, book, risk)
    broker = PaperBroker(risk)
    broker.submit(intent, decision, book, now=now)
    bad = book.model_copy(update={"bids": (book.bids[0].model_copy(update={"price": 0.1}),)})
    assert broker.process(intent.client_order_id, bad, now=now + timedelta(seconds=1)).status == "rejected"
    assert not risk.positions(now=now)
