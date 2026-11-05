"""Regression coverage for ledger completeness and obsolete quote rejection."""

from datetime import timedelta

from neraium_poly.execution import ExecutionConfig, PaperBroker
from neraium_poly.risk import RiskEngine
from test_execution import approved


def test_newer_quote_invalidates_older_executable_liquidity(now, market, book, tmp_path):
    risk = RiskEngine()
    intent, decision = approved(now, market, book, risk)
    path = str(tmp_path / "broker.sqlite")
    broker = PaperBroker(risk, path, ExecutionConfig(latency_ms=0))
    newer = book.model_copy(
        update={
            "id": "newer",
            "sequence": 2,
            "timestamp": now + timedelta(seconds=1),
            "available_at": now + timedelta(seconds=1),
            "asks": (book.asks[0].model_copy(update={"price": 0.41}),),
        }
    )
    assert broker.submit(intent, decision, newer, now=now + timedelta(seconds=1)).status == "open"
    broker.close()
    broker = PaperBroker(risk, path, ExecutionConfig(latency_ms=0))
    result = broker.process(intent.client_order_id, book, now=now + timedelta(seconds=2))
    assert result.status == "rejected" and result.reason == "regressing_book_snapshot"
    assert not risk.positions(now=now)


def test_sequence_regression_rejects_despite_newer_timestamp(now, market, book):
    risk = RiskEngine()
    intent, decision = approved(now, market, book, risk)
    broker = PaperBroker(risk, config=ExecutionConfig(latency_ms=0))
    newer = book.model_copy(
        update={
            "id": "newer",
            "sequence": 3,
            "timestamp": now + timedelta(seconds=1),
            "available_at": now + timedelta(seconds=1),
            "asks": (book.asks[0].model_copy(update={"price": 0.41}),),
        }
    )
    broker.submit(intent, decision, newer, now=now + timedelta(seconds=1))
    regressed = book.model_copy(
        update={
            "sequence": 2,
            "timestamp": now + timedelta(seconds=2),
            "available_at": now + timedelta(seconds=2),
        }
    )
    assert (
        broker.process(intent.client_order_id, regressed, now=now + timedelta(seconds=2)).status == "rejected"
    )


def test_unmatched_risk_fill_cannot_certify_empty_broker(now, market, book):
    risk = RiskEngine()
    intent, decision = approved(now, market, book, risk)
    broker = PaperBroker(risk, config=ExecutionConfig(latency_ms=0))
    assert broker.submit(intent, decision, book, now=now).status == "filled"
    fresh = PaperBroker(risk)
    result = fresh.reconcile(now=now)
    assert not result["consistent"]
    assert result["mismatches"] == ["orphan-risk-fill:" + decision.reservation_id]


def test_unresolved_pending_ack_is_unknown_then_recovers(now, market, book, monkeypatch):
    risk = RiskEngine()
    intent, decision = approved(now, market, book, risk)
    broker = PaperBroker(risk, config=ExecutionConfig(latency_ms=0))
    original = risk.audit

    def unavailable():
        raise ConnectionError("audit offline")

    monkeypatch.setattr(risk, "audit", unavailable)
    assert broker.submit(intent, decision, book, now=now).reason == "risk_recovery_pending"
    result = broker.reconcile(now=now)
    assert not result["consistent"]
    assert result["pending_orders"] == [intent.client_order_id]
    assert result["unavailable"] == ["risk_audit_unavailable"]
    monkeypatch.setattr(risk, "audit", original)
    assert broker.reconcile(now=now)["consistent"]
    assert risk.positions(now=now)[0].quantity == 10
