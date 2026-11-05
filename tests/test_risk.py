from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from neraium_poly.contracts import OrderIntent, RelationshipEvidence, TradingOpportunity
from neraium_poly.risk import RiskEngine, RiskLimits, RiskViolation


def inputs(now, market, book, *, cost=4, tier="standard", suffix="0", fee=0.02):
    evidence = RelationshipEvidence(
        id="evidence-" + suffix,
        timestamp=now,
        available_at=now,
        source="independent-news",
        relationship_id="r1",
        sample_count=100,
        persistence=5,
        strength=0.3,
        confidence=0.9,
        qualified=True,
        observation_ids=("observation-" + suffix,),
    )
    opportunity = TradingOpportunity(
        id="opportunity-" + suffix,
        timestamp=now,
        available_at=now,
        source="strategy",
        market_id=market.market_id,
        token_id=market.token_id,
        event_id=market.event_id,
        estimate_id="estimate",
        evidence_ids=(evidence.id,),
        market_probability=0.4,
        estimated_probability=0.65,
        conservative_probability=0.55,
        net_edge=0.14,
        fee_rate=fee,
        slippage=0.002,
        liquidity=40,
        tier=tier,
    )
    intent = OrderIntent(
        id="intent-" + suffix,
        timestamp=now,
        available_at=now,
        source="strategy",
        client_order_id="client-" + suffix,
        market_id=market.market_id,
        token_id=market.token_id,
        event_id=market.event_id,
        opportunity_id=opportunity.id,
        limit_price=0.4,
        quantity=cost / 0.4,
        expires_at=now + timedelta(minutes=1),
        tier=tier,
    )
    return intent, opportunity, market, book, [evidence]


def test_approve_bind_and_idempotent(now, market, book):
    engine = RiskEngine()
    args = inputs(now, market, book)
    decision = engine.approve(*args, now=now)
    assert decision.approved
    assert decision.approved_notional == pytest.approx(4.08)
    assert engine.approve(*args, now=now) == decision
    assert engine.snapshot(now=now)["reserved"] == pytest.approx(4.08)
    changed = args[0].model_copy(update={"quantity": 11})
    assert not engine.validate_approval(changed, decision, now=now)
    assert not engine.approve(changed, *args[1:], now=now).approved
    assert not engine.validate_approval(
        args[0], decision.model_copy(update={"approved_notional": 100}), now=now
    )


@pytest.mark.parametrize(
    ("index", "update", "reason"),
    [
        (3, {"timestamp": None}, "stale_book"),
        (3, {"complete": False}, "missing_liquidity"),
        (2, {"resolution_rules": ""}, "unverified_market_rules"),
        (2, {"status": "closed"}, "unverified_market_rules"),
        (1, {"conservative_probability": 0.41}, "insufficient_net_edge"),
        (1, {"evidence_ids": ("missing",)}, "missing_evidence"),
        (0, {"side": "SELL"}, "unsupported_side"),
        (0, {"quantity": 1000}, "position_tier_limit"),
        (0, {"limit_price": 0.401}, "tick_size"),
    ],
)
def test_fail_closed(now, market, book, index, update, reason):
    args = list(inputs(now, market, book))
    if update.get("timestamp", "") is None:
        update = {"timestamp": now - timedelta(minutes=1)}
    args[index] = args[index].model_copy(update=update)
    result = RiskEngine().approve(*args, now=now)
    assert not result.approved
    assert reason in result.reasons


def test_evidence_future_unqualified(now, market, book):
    args = list(inputs(now, market, book))
    args[4] = [args[4][0].model_copy(update={"qualified": False, "available_at": now + timedelta(seconds=1)})]
    result = RiskEngine().approve(*args, now=now)
    assert {"future_information", "unqualified_evidence"} <= set(result.reasons)


def test_exceptional_not_confidence_alone(now, market, book):
    args = inputs(now, market, book, cost=20, tier="exceptional")
    result = RiskEngine().approve(*args, now=now)
    assert not result.approved and "exceptional_qualification" in result.reasons


def test_partial_fill_cash_reconciliation_and_restart(now, market, book, tmp_path):
    path = str(tmp_path / "risk.sqlite")
    engine = RiskEngine(path)
    args = inputs(now, market, book)
    intent = args[0]
    decision = engine.approve(*args, now=now)
    engine.record_fill(intent, decision, 5, 0.4, 0.04, now=now)
    engine.record_fill(intent, decision, 5, 0.4, 0.04, now=now)
    state = engine.snapshot(now=now)
    assert state["cash"] == pytest.approx(497.96)
    assert state["reserved"] == pytest.approx(2.04)
    assert state["invested"] == pytest.approx(2.04)
    engine.close()
    engine = RiskEngine(path)
    assert engine.positions(now=now)[0].quantity == 5
    engine.record_fill(intent, decision, 10, 0.4, 0.08, now=now)
    assert engine.snapshot(now=now)["cash"] == pytest.approx(495.92)
    assert engine.snapshot(now=now)["reserved"] == 0
    engine.release(decision.reservation_id, now=now)
    assert engine.snapshot(now=now)["invested"] == pytest.approx(4.08)
    with pytest.raises(RiskViolation):
        engine.record_fill(intent, decision, 10, 0.4, 0.08, now=now)


@pytest.mark.parametrize(
    "qty,price,fees", [(11, 0.4, 0.088), (5, 0.41, 0.04), (5, 0.4, 0.05), (float("nan"), 0.4, 0)]
)
def test_fill_boundary_atomic(now, market, book, qty, price, fees):
    engine = RiskEngine()
    args = inputs(now, market, book)
    decision = engine.approve(*args, now=now)
    with pytest.raises(RiskViolation):
        engine.record_fill(args[0], decision, qty, price, fees, now=now)
    assert engine.snapshot(now=now)["cash"] == 500
    assert not engine.positions(now=now)


def test_expiration_and_kill(now, market, book):
    engine = RiskEngine()
    args = inputs(now, market, book)
    decision = engine.approve(*args, now=now)
    assert not engine.validate_approval(args[0], decision, now=now + timedelta(seconds=11))
    assert engine.snapshot(now=now + timedelta(seconds=11))["reserved"] == 0
    args = inputs(now, market, book, suffix="next")
    decision = engine.approve(*args, now=now)
    engine.kill_switch(True, now=now)
    assert not engine.validate_approval(args[0], decision, now=now)
    assert engine.snapshot(now=now)["reserved"] == 0
    assert "kill_switch" in engine.approve(*inputs(now, market, book, suffix="blocked"), now=now).reasons


def test_market_event_and_correlation_limits(now, market, book):
    engine = RiskEngine(limits=RiskLimits(market_fraction=0.01))
    assert engine.approve(*inputs(now, market, book), now=now).approved
    assert "market_exposure" in engine.approve(*inputs(now, market, book, suffix="2"), now=now).reasons
    for field, reason in [("event_fraction", "event_exposure"), ("correlation_fraction", "cluster_exposure")]:
        engine = RiskEngine(limits=RiskLimits(**{field: 0.01}))
        assert engine.approve(*inputs(now, market, book), now=now).approved
        m2 = market.model_copy(update={"market_id": "m2", "token_id": "t2"})
        b2 = book.model_copy(update={"market_id": "m2", "token_id": "t2"})
        assert reason in engine.approve(*inputs(now, m2, b2, suffix="2"), now=now).reasons


def test_concurrent_reservations_across_instances(now, market, book, tmp_path):
    path = str(tmp_path / "shared.sqlite")
    limits = RiskLimits(aggregate_fraction=0.02, market_fraction=1, event_fraction=1, correlation_fraction=1)
    engines = [RiskEngine(path, limits) for _ in range(8)]

    def reserve(i):
        return engines[i].approve(*inputs(now, market, book, suffix=str(i)), now=now)

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(reserve, range(8)))
    assert sum(r.approved for r in results) == 2
    assert engines[0].snapshot(now=now)["reserved"] == pytest.approx(8.16)


def test_loss_streak_and_drawdown(now, market, book):
    engine = RiskEngine(limits=RiskLimits(daily_loss_fraction=0.01, drawdown_fraction=0.01))
    for i in range(2):
        args = inputs(now, market, book, suffix=str(i))
        decision = engine.approve(*args, now=now)
        assert decision.approved
        engine.record_fill(args[0], decision, 10, 0.4, 0.08, now=now)
        engine.settle("t1", 0, now=now, rules_verified=True, resolution_source="fixture")
    state = engine.snapshot(now=now)
    assert state["realized_pnl"] == pytest.approx(-8.16)
    result = engine.approve(*inputs(now, market, book, suffix="stop"), now=now)
    assert {"daily_loss_limit", "drawdown_circuit_breaker"} <= set(result.reasons)


def test_uncertain_settlement_and_stress(now, market, book):
    engine = RiskEngine()
    args = inputs(now, market, book)
    decision = engine.approve(*args, now=now)
    engine.record_fill(args[0], decision, 10, 0.4, 0.08, now=now)
    with pytest.raises(RiskViolation):
        engine.settle("t1", 1, now=now, rules_verified=False, resolution_source="")
    assert engine.stress(now=now)["worst_case_loss"] == pytest.approx(4.08)
    assert engine.settle("t1", 1, now=now, rules_verified=True, resolution_source="fixture") == pytest.approx(
        5.92
    )
    assert engine.settle("t1", 1, now=now, rules_verified=True, resolution_source="fixture") == 0


def test_liquidity_disappears_and_spread(now, market, book):
    args = list(inputs(now, market, book))
    args[3] = book.model_copy(update={"asks": ()})
    assert not RiskEngine().approve(*args, now=now).approved
    args[3] = book.model_copy(update={"bids": (book.bids[0].model_copy(update={"price": 0.2}),)})
    assert "large_spread" in RiskEngine().approve(*args, now=now).reasons


def test_limits_persist_and_live_gate(now, tmp_path, monkeypatch):
    path = str(tmp_path / "risk.sqlite")
    RiskEngine(path).close()
    with pytest.raises(RiskViolation):
        RiskEngine(path, RiskLimits(bankroll=1000))
    monkeypatch.setenv("LIVE_TRADING_ENABLED", "true")
    with pytest.raises(RiskViolation):
        RiskEngine()


def test_fractional_kelly_is_capped_and_optional(now, market, book):
    engine = RiskEngine()
    opportunity = inputs(now, market, book)[1]
    assert engine.size(opportunity) == 2
    assert engine.size(opportunity, fractional_kelly=True) <= 5
    assert engine.size(opportunity.model_copy(update={"net_edge": -0.1}), fractional_kelly=True) == 0
