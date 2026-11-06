"""Controlled integration fixtures; never installed as operational observations."""

import hashlib
from datetime import UTC, datetime, timedelta

import pytest
from neraium_poly.experimental.migration import migrate_research_baseline, strategy_code_hash
from neraium_poly.experimental.runtime import ExperimentalRuntime
from neraium_poly.ops.live_ledger import LiveLedger
from test_experimental_account import book, fee, signal
from test_experimental_runtime import Feed, Fees, runtime


@pytest.fixture
def moment():
    return datetime(2026, 11, 6, 12, tzinfo=UTC)


async def test_admission_partial_fill_expiry_trace_and_restart(tmp_path, moment):
    r, clock, _feed = runtime(tmp_path, moment)
    b = book(moment, size=100)
    first = signal(moment, b)
    pending = [first]
    r.engine.evaluate_frame = lambda f, now: [pending.pop()] if pending else []
    r.fees[b.token_id] = fee(moment)
    original = _feed.read

    async def small_depth():
        frame = await original()
        return frame.model_copy(update={"books": (book(clock(), size=100 if clock() == moment else 10),)})

    _feed.read = small_depth
    try:
        await r.cycle()
        row = r.trace.status()["phase10_epoch"]["strategies"]["short_horizon"]
        assert row["order_attempts"] == row["submitted_orders"] == 1
        assert row["fills"] == 0
        assert r.last_cycle["decision_trace"]["strategies"]["short_horizon"]["submitted_orders"] == 1
        assert all(
            "samples" not in reason
            for reason in r.last_cycle["decision_trace"]["strategies"]["short_horizon"]["reasons"].values()
        )
        clock.now += timedelta(seconds=1)
        await r.cycle()
        row = r.trace.status()["phase10_epoch"]["strategies"]["short_horizon"]
        assert row["fills"] == row["entry_fills"] == 1
        assert r.state()["orders"][0]["status"] == "partial"
        assert r.state()["positions"][0]["quantity"] == pytest.approx(1)
        clock.now += timedelta(seconds=31)
        await r.cycle()
        row = r.trace.status()["phase10_epoch"]["strategies"]["short_horizon"]
        assert row["expired_orders"] == 1
        assert row["fills"] == 1
        cp = r.trace.checkpoint()
        cash = r.state()["cash"]
    finally:
        await r.close()
    restarted = ExperimentalRuntime(r.config, clock=clock, feed=Feed(clock), fee_adapter=Fees())
    try:
        assert restarted.trace.checkpoint() == cp
        restarted._trace_execution()
        assert restarted.trace.checkpoint() == cp
        assert restarted.state()["cash"] == cash
    finally:
        await restarted.close()


async def test_unavailable_risk_intent_is_audited_and_counted_fail_closed(tmp_path, moment):
    r, _clock, _feed = runtime(tmp_path, moment)
    b = book(moment)
    s = signal(moment, b)
    r.engine.evaluate_frame = lambda f, now: [s]
    r.fees[b.token_id] = fee(moment)

    def unavailable(*args, **kwargs):
        raise ConnectionError("controlled unavailable risk")

    r.account.risk.approve = unavailable
    try:
        await r.cycle()
        row = r.trace.status()["phase10_epoch"]["strategies"]["short_horizon"]
        assert row["order_attempts"] == row["risk_rejections"] == 1
        assert row["submitted_orders"] == row["fills"] == 0
        assert r.state()["orders_attempted"] == 1
        assert r.state()["cash"] == 500 and not r.state()["positions"]
        assert row["reasons"]["risk_unavailable"]["category"] == "RISK REJECTION"
    finally:
        await r.close()


async def test_migration_requires_stopped_service_and_preserves_account(tmp_path, moment):
    r, clock, _feed = runtime(tmp_path, moment)
    await r.cycle()
    config = r.config
    with pytest.raises(ValueError, match="another paper coordinator"):
        migrate_research_baseline(
            config, expected_previous_hash="a" * 64, reason="Controlled diagnostic baseline migration"
        )
    await r.close()
    ledger = LiveLedger(config.data_dir)
    checkpoint = ledger.get("strategy_engine")
    legacy = ledger.get("experimental_totals")
    ledger.put("strategy_code_hash", "a" * 64)
    ledger.close()
    risk = config.data_dir / "risk.sqlite"
    before = hashlib.sha256(risk.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match="exact changed"):
        migrate_research_baseline(
            config, expected_previous_hash="b" * 64, reason="Controlled diagnostic baseline migration"
        )
    result = migrate_research_baseline(
        config, expected_previous_hash="a" * 64, reason="Controlled diagnostic baseline migration"
    )
    assert result["new_hash"] == strategy_code_hash() and not result["account_mutation"]
    assert hashlib.sha256(risk.read_bytes()).hexdigest() == before
    ledger = LiveLedger(config.data_dir)
    try:
        assert ledger.get("strategy_engine") == checkpoint
        assert ledger.get("experimental_totals") == legacy
        assert ledger.get("research_baseline_migrations")[0]["previous_checkpoint"] == checkpoint
    finally:
        ledger.close()
    restarted = ExperimentalRuntime(config, clock=clock, feed=Feed(clock), fee_adapter=Fees())
    try:
        assert restarted.state()["cash"] == 500
        assert restarted.engine.checkpoint() == checkpoint
    finally:
        await restarted.close()


@pytest.mark.parametrize("stop_exit", [False, True])
async def test_horizon_exit_fill_or_emergency_cancellation_is_traced(tmp_path, moment, stop_exit):
    r, clock, _feed = runtime(tmp_path, moment)
    b = book(moment)
    pending = [signal(moment, b)]
    r.engine.evaluate_frame = lambda f, now: [pending.pop()] if pending else []
    r.fees[b.token_id] = fee(moment)
    try:
        await r.cycle()
        clock.now += timedelta(seconds=1)
        await r.cycle()
        clock.now += timedelta(seconds=60)
        await r.cycle()  # Creates a bid-side exit with its own latency.
        assert r.state()["exits"][0]["status"] == "open"
        if stop_exit:
            r.stop()
            r.stop()  # Idempotent audit and counter behavior.
            row = r.trace.status()["phase10_epoch"]["strategies"]["short_horizon"]
            assert row["cancelled_orders"] == 1
            assert row["fills"] == 1
            assert r.state()["kill_switch"]
        else:
            clock.now += timedelta(seconds=1)
            await r.cycle()
            row = r.trace.status()["phase10_epoch"]["strategies"]["short_horizon"]
            assert row["fills"] == 2 and row["exit_fills"] == 1
            assert not r.state()["positions"]
            assert r.state()["simulated_realized_pnl"] < 0  # Actual fixture spread+fees.
    finally:
        await r.close()


async def test_shutdown_cancellation_checkpoint_needs_no_later_cycle(tmp_path, moment):
    r, clock, _feed = runtime(tmp_path, moment)
    b = book(moment)
    pending = [signal(moment, b)]
    r.engine.evaluate_frame = lambda f, now: [pending.pop()] if pending else []
    r.fees[b.token_id] = fee(moment)
    await r.cycle()
    assert r.state()["orders"][0]["status"] == "open"
    await r.close()
    restarted = ExperimentalRuntime(r.config, clock=clock, feed=Feed(clock), fee_adapter=Fees())
    try:
        row = restarted.trace.status()["phase10_epoch"]["strategies"]["short_horizon"]
        assert row["submitted_orders"] == row["cancelled_orders"] == 1
        assert row["fills"] == 0
        assert restarted.state()["cash"] == 500
    finally:
        await restarted.close()
