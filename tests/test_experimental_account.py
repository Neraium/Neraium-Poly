"""Controlled fixture execution; never actual Polymarket strategy evidence."""

import hashlib
import os
from datetime import UTC, datetime, timedelta

import pytest
from neraium_poly.contracts import MarketSnapshot, OrderBookSnapshot, PriceLevel
from neraium_poly.data.operational import SettlementObservation
from neraium_poly.experimental.account import ExperimentalAccount, identity
from neraium_poly.experimental.contracts import ExperimentalSignal
from neraium_poly.risk import RiskEngine, RiskLimits, RiskViolation


@pytest.fixture
def moment():
    return datetime(2026, 11, 6, 12, tzinfo=UTC)


def market(now, token="test-token"):
    return MarketSnapshot(
        id="test-market-record-" + token,
        timestamp=now,
        available_at=now,
        source="https://gamma-api.polymarket.com",
        market_id="test-market-" + token,
        token_id=token,
        event_id="test-event-" + token,
        question="CONTROLLED fixture?",
        outcome="Yes",
        probability=0.4,
        status="active",
        resolution_rules="CONTROLLED explicit binary rules",
        resolution_source="https://test.invalid/oracle",
        end_time=now + timedelta(days=1),
        min_order_size=5,
        tick_size=0.01,
    )


def book(now, token="test-token", bid=0.39, ask=0.4, size=100):
    return OrderBookSnapshot(
        id=f"test-book-{token}-{now.isoformat()}-{bid}-{size}",
        timestamp=now,
        available_at=now,
        source="https://clob.polymarket.com",
        market_id="test-market-" + token,
        token_id=token,
        bids=(PriceLevel(price=bid, size=size),),
        asks=(PriceLevel(price=ask, size=size),),
    )


def signal(now, b, **updates):
    edge = 0.52 * 0.98 - b.asks[0].price * 1.02 - 0.02
    values = {
        "id": "test-signal-" + b.id,
        "timestamp": now,
        "available_at": now,
        "source": "controlled-test-forecast",
        "strategy_id": "short_horizon",
        "market_id": b.market_id,
        "token_id": b.token_id,
        "event_id": "test-event-" + b.token_id,
        "eligible": True,
        "forecast_value": 0.55,
        "lower_value": 0.52,
        "upper_value": 0.58,
        "estimated_net_edge": edge,
        "fee_rate": 0.02,
        "evidence_ids": (b.id,),
        "hypothesis": "CONTROLLED unvalidated mark forecast",
        "uncertainty": "CONTROLLED fixture interval, not calibrated probability",
        "assumptions": ("Controlled test input",),
    }
    values.update(updates)
    return ExperimentalSignal(**values)


def fee(now, rate=0.02):
    return {
        "fee_rate": rate,
        "observed_at": now.isoformat(),
        "source": "https://clob.polymarket.com",
        "reference": "controlled-fee-fixture-not-real-evidence",
    }


def account(tmp_path, now, **kwargs):
    return ExperimentalAccount(tmp_path / "experimental", tmp_path / "certified", clock=lambda: now, **kwargs)


def enter(a, now, size=100):
    m, b = market(now), book(now, size=size)
    s = signal(now, b)
    result = a.submit(s, m, b, now=now, fee_schedule=fee(now))
    return s, result


def test_capital_isolated_durable_and_mode_explicit(tmp_path, moment):
    certified = tmp_path / "certified"
    certified.mkdir()
    (certified / "risk.sqlite").write_bytes(b"certified readonly sentinel")
    before = hashlib.sha256((certified / "risk.sqlite").read_bytes()).hexdigest()
    a = account(tmp_path, moment)
    try:
        s, result = enter(a, moment)
        assert result["status"] == "submitted" and result["validation_status"] == "unvalidated"
        assert result["risk_decision"]["approved"]
        assert a.snapshot(now=moment)["reserved"] == pytest.approx(2.04)
        a.advance({"test-token": book(moment + timedelta(seconds=1))}, now=moment + timedelta(seconds=1))
        state = a.snapshot(now=moment + timedelta(seconds=1))
        assert state["cash"] == pytest.approx(497.96)
        assert state["fills"] == 1 and state["positions"][0]["quantity"] == pytest.approx(5)
        assert not hasattr(s, "calibrated")
        assert a.submit(s, market(moment), book(moment), now=moment, fee_schedule=fee(moment)) == result
    finally:
        a.close()
    assert hashlib.sha256((certified / "risk.sqlite").read_bytes()).hexdigest() == before
    a = account(tmp_path, moment + timedelta(seconds=2))
    try:
        assert a.snapshot(now=moment + timedelta(seconds=2))["cash"] == pytest.approx(497.96)
    finally:
        a.close()


def test_paths_and_hardlinks_refused_before_writing(tmp_path, moment):
    certified = tmp_path / "certified"
    certified.mkdir()
    sentinel = certified / "risk.sqlite"
    sentinel.write_bytes(b"unchanged")
    with pytest.raises(RiskViolation, match="disjoint"):
        ExperimentalAccount(certified, certified)
    alias = tmp_path / "alias"
    alias.symlink_to(certified, target_is_directory=True)
    with pytest.raises(RiskViolation, match="disjoint"):
        ExperimentalAccount(alias, certified)
    other = tmp_path / "experimental"
    other.mkdir()
    os.link(sentinel, other / "risk.sqlite")
    with pytest.raises(RiskViolation, match="aliases"):
        ExperimentalAccount(other, certified)
    assert sentinel.read_bytes() == b"unchanged" and not (other / "account.json").exists()


def test_unknown_existing_account_is_not_adopted(tmp_path):
    d = tmp_path / "experiment"
    d.mkdir()
    (d / "broker.sqlite").write_bytes(b"unknown")
    with pytest.raises(RiskViolation, match="unidentified"):
        ExperimentalAccount(d, tmp_path / "certified")


def test_partial_entry_repeated_book_and_expiration(tmp_path, moment):
    a = account(tmp_path, moment)
    try:
        _, result = enter(a, moment, size=30)
        t = moment + timedelta(seconds=1)
        b = book(t, size=30)
        a.advance({b.token_id: b}, now=t)
        assert a.snapshot(now=t)["positions"][0]["quantity"] == pytest.approx(3)
        a.advance({b.token_id: b}, now=t)
        assert a.snapshot(now=t)["positions"][0]["quantity"] == pytest.approx(3)
        a.advance({}, now=t + timedelta(seconds=11))
        assert a.snapshot(now=t + timedelta(seconds=11))["reserved"] == 0
        assert result["execution"]["status"] == "open"
    finally:
        a.close()


@pytest.mark.parametrize(
    "change,reason",
    [
        ({"fee_schedule": None}, "verified_current_fee_schedule_required"),
        ({"signal_updates": {"strategy_id": "unknown"}}, "experimental_strategy_not_registered"),
        ({"signal_updates": {"upper_value": 0.95}}, "experimental_uncertainty_limit"),
        (
            {"signal_updates": {"tier": "exceptional"}, "target_notional": 15},
            "exceptional_requires_independently_calibrated_evidence",
        ),
        ({"signal_updates": {"estimated_net_edge": 0.4}}, "insufficient_or_overstated_experimental_net_edge"),
        (
            {"book_updates": {"source": "controlled-synthetic-source"}},
            "authentic_public_book_source_required",
        ),
    ],
)
def test_risk_rejections(tmp_path, moment, change, reason):
    a = account(tmp_path, moment)
    try:
        b = book(moment).model_copy(update=change.get("book_updates", {}))
        s = signal(moment, b, **change.get("signal_updates", {}))
        r = a.submit(
            s,
            market(moment),
            b,
            now=moment,
            target_notional=change.get("target_notional", 2),
            fee_schedule=change.get("fee_schedule", fee(moment)),
        )
        assert r["status"] == "rejected" and reason in r["reasons"]
        assert a.snapshot(now=moment)["cash"] == 500 and a.snapshot(now=moment)["reserved"] == 0
    finally:
        a.close()


def test_stale_book_fee_and_duplicate_signal_payload(tmp_path, moment):
    a = account(tmp_path, moment)
    try:
        b = book(moment - timedelta(seconds=16))
        s = signal(moment, b)
        r = a.submit(s, market(moment), b, now=moment, fee_schedule=fee(moment - timedelta(seconds=301)))
        assert "stale_book" in r["reasons"] and "verified_current_fee_schedule_required" in r["reasons"]
        with pytest.raises(RiskViolation, match="different payload"):
            a.submit(s.model_copy(update={"hypothesis": "changed"}), market(moment), b, now=moment)
    finally:
        a.close()


def test_horizon_exit_uses_actual_bid_and_realizes_costs_once(tmp_path, moment):
    a = account(tmp_path, moment)
    try:
        enter(a, moment)
        t = moment + timedelta(seconds=1)
        a.advance({"test-token": book(t)}, now=t)
        due = moment + timedelta(seconds=60)
        a.advance({"test-token": book(due, bid=0.55, ask=0.56)}, now=due, fees={"test-token": fee(due)})
        assert a.snapshot(now=due)["positions"]
        t = due + timedelta(seconds=1)
        b = book(t, bid=0.55, ask=0.56)
        a.advance({"test-token": b}, now=t, fees={"test-token": fee(t)})
        state = a.snapshot(now=t)
        assert not state["positions"] and state["cash"] == pytest.approx(500.655)
        assert state["simulated_realized_pnl"] == pytest.approx(0.655)
        assert state["exits"][0]["status"] == "filled"
        a.advance({"test-token": b}, now=t, fees={"test-token": fee(t)})
        assert a.snapshot(now=t)["cash"] == pytest.approx(500.655)
        assert a.broker.reconcile(now=t)["consistent"]
    finally:
        a.close()


def test_exit_partial_depth_does_not_replenish_same_source_book(tmp_path, moment):
    a = account(tmp_path, moment)
    try:
        enter(a, moment)
        t = moment + timedelta(seconds=1)
        a.advance({"test-token": book(t)}, now=t)
        due = moment + timedelta(seconds=60)
        a.advance({"test-token": book(due, bid=0.55, ask=0.56)}, now=due)
        t = due + timedelta(seconds=1)
        b = book(t, bid=0.55, ask=0.56, size=10)
        a.advance({"test-token": b}, now=t, fees={"test-token": fee(t)})
        assert a.snapshot(now=t)["positions"][0]["quantity"] == pytest.approx(4)
        a.advance(
            {
                "test-token": b.model_copy(
                    update={"id": b.id + "-new-receipt", "available_at": t + timedelta(milliseconds=1)}
                )
            },
            now=t + timedelta(milliseconds=1),
            fees={"test-token": fee(t)},
        )
        assert a.snapshot(now=t)["positions"][0]["quantity"] == pytest.approx(4)
    finally:
        a.close()


def test_kill_switch_persistent_and_cancels_without_certified_change(tmp_path, moment):
    a = account(tmp_path, moment)
    enter(a, moment)
    a.stop(now=moment)
    assert a.snapshot(now=moment)["reserved"] == 0
    a.close()
    a = account(tmp_path, moment + timedelta(seconds=1))
    try:
        b = book(moment + timedelta(seconds=1))
        r = a.submit(
            signal(b.timestamp, b), market(b.timestamp), b, now=b.timestamp, fee_schedule=fee(b.timestamp)
        )
        assert "kill_switch" in r["reasons"] and a.snapshot(now=b.timestamp)["cash"] == 500
    finally:
        a.close()


def test_settlement_requires_exact_rules_review_and_is_idempotent(tmp_path, moment):
    a = account(tmp_path, moment)
    m = market(moment)
    try:
        enter(a, moment)
        t = moment + timedelta(seconds=1)
        a.advance({"test-token": book(t)}, now=t)
        p = SettlementObservation(
            id="controlled-settlement",
            timestamp=t,
            available_at=t,
            source="https://clob.polymarket.com",
            market_id=m.market_id,
            event_id=m.event_id,
            token_id=m.token_id,
            condition_id="controlled-condition",
            payout=1,
            resolution_source=m.resolution_source,
            resolution_rules=m.resolution_rules,
            transaction_hash="controlled-transaction-ref",
            outcome_index=0,
            reporter="controlled-reporter",
            rules_reviewed=True,
        )
        with pytest.raises(RiskViolation):
            a.settle(p, m, now=t)
        review = identity(m.market_id, m.token_id, m.outcome, m.resolution_rules, m.resolution_source)
        pnl = a.settle(p, m, now=t, rule_review_hash=review, review_actor="controlled-test-reviewer")
        assert pnl == pytest.approx(2.96) and a.snapshot(now=t)["cash"] == pytest.approx(502.96)
        assert a.settle(p, m, now=t, rule_review_hash=review, review_actor="controlled-test-reviewer") == pnl
        assert a.snapshot(now=t)["cash"] == pytest.approx(502.96)
    finally:
        a.close()


def test_certified_risk_rejects_experimental_signal(tmp_path, moment):
    # Certified RiskEngine has no mode switch or path to experimental approval.
    risk = RiskEngine(str(tmp_path / "certified.sqlite"))
    try:
        from neraium_poly.contracts import OrderIntent, TradingOpportunity

        b = book(moment)
        s = signal(moment, b)
        intent = OrderIntent(
            timestamp=moment,
            available_at=moment,
            source="controlled",
            client_order_id="c",
            market_id=b.market_id,
            token_id=b.token_id,
            event_id=s.event_id,
            opportunity_id="o",
            limit_price=0.4,
            quantity=5,
            expires_at=moment + timedelta(seconds=10),
        )
        o = TradingOpportunity(
            id="o",
            timestamp=moment,
            available_at=moment,
            source="controlled",
            market_id=b.market_id,
            token_id=b.token_id,
            event_id=s.event_id,
            estimate_id="not-certified",
            evidence_ids=(),
            market_probability=0.4,
            estimated_probability=0.55,
            conservative_probability=0.52,
            net_edge=0.08,
            fee_rate=0.02,
            slippage=0.01,
            liquidity=100,
            calibrated=False,
        )
        r = risk.approve(intent, o, market(moment), b, (), now=moment)
        assert (
            not r.approved and "uncalibrated_probability" in r.reasons and "unapproved_model" not in r.reasons
        )
    finally:
        risk.close()


def test_exit_restart_reconciles_net_inventory_and_cash(tmp_path, moment):
    a = account(tmp_path, moment)
    enter(a, moment)
    t = moment + timedelta(seconds=1)
    a.advance({"test-token": book(t)}, now=t)
    due = moment + timedelta(seconds=60)
    a.advance({"test-token": book(due, bid=0.55, ask=0.56)}, now=due)
    t = due + timedelta(seconds=1)
    a.advance({"test-token": book(t, bid=0.55, ask=0.56)}, now=t, fees={"test-token": fee(t)})
    assert a.reconciliation["consistent"]
    a.close()
    a = account(tmp_path, t)
    try:
        state = a.snapshot(now=t)
        assert state["reconciliation"]["consistent"] and state["cash"] == pytest.approx(500.655)
        assert not state["positions"] and not state["kill_switch"]
        a.risk.db.execute("UPDATE account SET cash=cash+1 WHERE id=1")
        assert not a.reconcile(now=t)["consistent"]
    finally:
        a.close()


def test_recover_crash_between_broker_submission_and_final_signal(tmp_path, moment, monkeypatch):
    a = account(tmp_path, moment)

    def fail(*args, **kwargs):
        raise RuntimeError("controlled final-audit crash")

    monkeypatch.setattr(a, "_finish", fail)
    with pytest.raises(RuntimeError):
        enter(a, moment)
    a.close()
    t = moment + timedelta(seconds=1)
    a = account(tmp_path, t)
    try:
        a.advance({"test-token": book(t)}, now=t)
        assert a.snapshot(now=t)["cash"] == pytest.approx(497.96)
        assert len(a.snapshot(now=t)["orders"]) == 1
        assert a.reconciliation["consistent"]
    finally:
        a.close()


def test_recover_abandoned_reservation_before_broker_submission(tmp_path, moment, monkeypatch):
    class Crash(BaseException):
        pass

    a = account(tmp_path, moment)

    def fail(*args, **kwargs):
        raise Crash("controlled submission crash")

    monkeypatch.setattr(a.broker, "submit", fail)
    with pytest.raises(Crash):
        enter(a, moment)
    a.close()
    a = account(tmp_path, moment + timedelta(seconds=1))
    try:
        state = a.snapshot(now=moment + timedelta(seconds=1))
        assert state["cash"] == 500 and state["reserved"] == 0 and not state["orders"]
        assert state["reconciliation"]["consistent"]
    finally:
        a.close()


def test_exit_transaction_rollback_does_not_consume_depth_or_invent_profit(tmp_path, moment, monkeypatch):
    a = account(tmp_path, moment)
    try:
        enter(a, moment)
        t = moment + timedelta(seconds=1)
        a.advance({"test-token": book(t)}, now=t)
        due = moment + timedelta(seconds=60)
        a.advance({"test-token": book(due, bid=0.55, ask=0.56)}, now=due)
        original = a.risk._audit

        def fail(action, payload, now):
            if action == "experimental_exit_fill":
                raise RuntimeError("controlled atomic failure")
            return original(action, payload, now)

        monkeypatch.setattr(a.risk, "_audit", fail)
        t = due + timedelta(seconds=1)
        b = book(t, bid=0.55, ask=0.56)
        with pytest.raises(RuntimeError):
            a.advance({"test-token": b}, now=t, fees={"test-token": fee(t)})
        assert a.snapshot(now=t)["cash"] == pytest.approx(497.96)
        assert a.snapshot(now=t)["positions"][0]["quantity"] == 5
        monkeypatch.setattr(a.risk, "_audit", original)
        a.advance({"test-token": b}, now=t, fees={"test-token": fee(t)})
        assert a.snapshot(now=t)["cash"] == pytest.approx(500.655)
        assert a.reconcile(now=t)["consistent"]
    finally:
        a.close()


def test_correlation_and_aggregate_reservation_boundaries(tmp_path, moment):
    for name, limits, expected_count, reason in [
        ("correlation", RiskLimits(), 10, "cluster_exposure"),
        ("aggregate", RiskLimits(correlation_fraction=1, event_fraction=1), 20, "aggregate_exposure"),
    ]:
        a = ExperimentalAccount(tmp_path / name, tmp_path / "certified", limits=limits, clock=lambda: moment)
        try:
            for i in range(expected_count + 1):
                token = "token-" + str(i)
                b = book(moment, token=token)
                m = market(moment, token=token)
                r = a.submit(
                    signal(moment, b), m, b, now=moment, target_notional=4.9, fee_schedule=fee(moment)
                )
                if i < expected_count:
                    assert r["status"] == "submitted"
                else:
                    assert r["status"] == "rejected" and reason in r["reasons"]
            assert a.snapshot(now=moment)["cash"] == 500
        finally:
            a.close()


def test_strategy_losing_streak_suspends_without_martingale(tmp_path, moment):
    a = account(tmp_path, moment)
    try:
        for i in range(5):
            now = moment + timedelta(seconds=i * 70)
            _, r = enter(a, now)
            assert r["status"] == "submitted"
            t = now + timedelta(seconds=1)
            a.advance({"test-token": book(t)}, now=t)
            due = now + timedelta(seconds=60)
            a.advance({"test-token": book(due, bid=0.2, ask=0.21)}, now=due)
            t = due + timedelta(seconds=1)
            a.advance({"test-token": book(t, bid=0.2, ask=0.21)}, now=t, fees={"test-token": fee(t)})
        row = next(x for x in a.snapshot(now=t)["strategies"] if x["strategy_id"] == "short_horizon")
        assert row["suspended"] and row["suspension_reason"] == "strategy_losing_streak"
        t += timedelta(seconds=10)
        _, r = enter(a, t)
        assert r["status"] == "rejected" and "experimental_strategy_suspended" in r["reasons"]
        assert a.reconcile(now=t)["consistent"]
    finally:
        a.close()


def test_buy_requires_post_latency_source_and_receipt(tmp_path, moment):
    a = account(tmp_path, moment)
    try:
        enter(a, moment)
        t = moment + timedelta(seconds=1)
        before = book(moment).model_copy(update={"available_at": t})
        a.advance({"test-token": before}, now=t)
        assert not a.snapshot(now=t)["positions"] and a.snapshot(now=t)["cash"] == 500
        fresh = book(t)
        a.advance({"test-token": fresh}, now=t)
        assert a.snapshot(now=t)["positions"][0]["quantity"] == 5
        row = a.risk.db.execute(
            "SELECT payload,digest FROM experimental_observations WHERE id=?", (fresh.id,)
        ).fetchone()
        assert row[0] == fresh.model_dump_json() and row[1] == hashlib.sha256(row[0].encode()).hexdigest()
    finally:
        a.close()


def test_synthetic_advance_cannot_spend_real_observation_approval(tmp_path, moment):
    a = account(tmp_path, moment)
    try:
        enter(a, moment)
        t = moment + timedelta(seconds=1)
        a.advance({"test-token": book(t).model_copy(update={"source": "SYNTHETIC-TEST-ONLY"})}, now=t)
        state = a.snapshot(now=t)
        assert state["cash"] == 500 and state["reserved"] == 0 and not state["positions"]
        assert state["orders"][0]["status"] == "cancelled"
    finally:
        a.close()


def test_stale_entry_fee_evidence_expires_before_pending_fill(tmp_path, moment):
    a = account(tmp_path, moment)
    try:
        b = book(moment)
        r = a.submit(
            signal(moment, b),
            market(moment),
            b,
            now=moment,
            fee_schedule=fee(moment - timedelta(seconds=299)),
        )
        assert r["status"] == "submitted"
        t = moment + timedelta(seconds=2)
        a.advance({"test-token": book(t)}, now=t)
        assert a.snapshot(now=t)["cash"] == 500 and not a.snapshot(now=t)["positions"]
        assert a.snapshot(now=t)["orders"][0]["status"] == "rejected"
    finally:
        a.close()


def test_execution_book_conflict_and_misrouted_marks_fail_closed(tmp_path, moment):
    a = account(tmp_path, moment)
    try:
        enter(a, moment)
        t = moment + timedelta(seconds=1)
        b = book(t)
        a._archive_book(b)
        bad = b.model_copy(update={"bids": (PriceLevel(price=0.38, size=100),)})
        with pytest.raises(RiskViolation, match="collision"):
            a.advance({"test-token": bad}, now=t)
        assert a.snapshot(now=t)["cash"] == 500
        a.advance({"test-token": b}, now=t)
        state = a.mark(
            {"test-token": book(t + timedelta(seconds=1), token="wrong-token", bid=0.9, ask=0.91)},
            now=t + timedelta(seconds=1),
        )
        assert state["simulated_pnl"] == pytest.approx(-0.09)
        newer = book(t + timedelta(seconds=2), bid=0.6, ask=0.61)
        a.mark({"test-token": newer}, now=newer.timestamp)
        state = a.mark({"test-token": b}, now=newer.timestamp)
        assert state["positions"][0]["mark_price"] == 0.6
    finally:
        a.close()
