"""Synthetic transport fixtures test real coordinator modules, not actual research.

The positive activation is deliberately a TEST-ONLY injection. These tests do not
create or approve a production ValidationStore report or claim real profitability.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from neraium_poly.contracts import MarketSnapshot, OrderBookSnapshot, PriceLevel
from neraium_poly.data.operational import (
    DiscoveryBatch,
    SettlementObservation,
    build_statistical_relationships,
)
from neraium_poly.ops.live import LivePaperRuntime, identity
from neraium_poly.ops.live_config import LivePaperConfig
from neraium_poly.strategy import HistogramCalibrator, LabeledForecast, ModelRegistry, ProtocolFeeModel
from neraium_poly.validation import Activation


class Clock:
    def __init__(self, now):
        self.now = now

    def __call__(self):
        return self.now

    def advance(self, seconds=1):
        self.now += timedelta(seconds=seconds)


class FakeAdapter:
    """No network; inputs and labels are explicitly synthetic test fixtures."""

    def __init__(self, clock):
        self.clock = clock
        self.discovery_offset = 0
        self.book_calls = []
        self.fee_calls = []
        self.settlement_calls = []
        self.shift = False
        self.source_time = None
        self.stale = False
        self.fail_books = False
        self.fail_discovery = False
        self.wrong_identity = False
        self.empty_book = False
        self.fee_callback = None
        self.settlement_result = None
        self.closed = False

    def markets(self):
        now = self.clock()
        return tuple(
            MarketSnapshot(
                id=f"fixture-market-{i}-{now.isoformat()}",
                timestamp=now,
                available_at=now,
                source="synthetic-operational-test",
                market_id=f"m{i}",
                event_id="e1",
                token_id=f"t{i}",
                outcome="Yes",
                question=f"Test outcome{i}?",
                probability=0.4,
                status="active",
                resolution_rules="Explicit fixture rules",
                resolution_source="https://fixture.example/oracle",
            )
            for i in (1, 2)
        )

    async def discover_bounded(self, **kwargs):
        if self.fail_discovery:
            raise ConnectionError("fixture disconnect")
        self.discovery_offset += 2
        return DiscoveryBatch(self.markets(), 2, True, (), self.discovery_offset)

    async def _get(self, base, path):
        # Controlled metadata fixture for coordinator-approved scope pinning.
        market_id = path.rsplit("/", 1)[-1]
        return {
            "id": market_id,
            "eventId": "e1",
            "question": f"Test outcome{market_id[-1]}?",
            "clobTokenIds": [f"t{market_id[-1]}", f"n{market_id[-1]}"],
            "outcomes": ["Yes", "No"],
            "outcomePrices": [0.4, 0.6],
            "active": True,
            "closed": False,
            "description": "Explicit fixture rules",
            "resolutionSource": "https://fixture.example/oracle",
        }

    async def book(self, market_id, token_id):
        self.book_calls.append((market_id, token_id))
        if self.fail_books:
            raise ConnectionError("fixture disconnect")
        self.clock.advance(0.2)
        now = self.clock()
        source = self.source_time or (now - timedelta(seconds=100) if self.stale else now)
        ask = 0.6 if self.shift and market_id == "m2" else 0.4
        return OrderBookSnapshot(
            id=f"fixture-book-{token_id}-{now.isoformat()}",
            timestamp=source,
            available_at=now,
            source="synthetic-exchange-test",
            market_id="wrong-market" if self.wrong_identity else market_id,
            token_id=token_id,
            bids=() if self.empty_book else (PriceLevel(price=ask - 0.01, size=1000),),
            asks=() if self.empty_book else (PriceLevel(price=ask, size=1000),),
            complete=not self.empty_book,
        )

    async def fee_model(self, token_id):
        self.fee_calls.append(token_id)
        if self.fee_callback:
            self.fee_callback()
        return ProtocolFeeModel(0.02)

    async def settlement(self, market):
        self.settlement_calls.append(market.token_id)
        return self.settlement_result

    async def close(self):
        self.closed = True


class TestOnlyValidation:
    """Injection bypasses production approval solely to exercise downstream modules."""

    __test__ = False

    def __init__(self, clock):
        self.clock, self.activation = clock, None

    def load_active(self, now):
        if self.activation and now < self.activation.expires_at:
            return self.activation
        return None

    def status(self, now):
        return {"active": self.load_active(now) is not None, "test_only": True}

    def close(self):
        pass


def configuration(tmp_path, **updates):
    return LivePaperConfig(
        data_dir=tmp_path / "operation",
        max_markets=2,
        page_size=2,
        books_per_cycle=4,
        min_free_disk_mb=100,
        **updates,
    )


def fixture_activation(clock, markets):
    rows = []
    for i in range(120):
        at = clock() - timedelta(days=10) + timedelta(seconds=i)
        rows.append(
            LabeledForecast(
                id=f"synthetic-label-{i}",
                timestamp=at,
                available_at=at,
                source="synthetic-test-only",
                market_id=f"label-market-{i}",
                event_id=f"label-event-{i}",
                probability=0.395,
                outcome=int(i % 10 < 9),
                label_available_at=at + timedelta(hours=1),
            )
        )
    registry = ModelRegistry()
    mid = registry.register(HistogramCalibrator.fit(rows, clock() - timedelta(days=1)))
    approved_at = clock() - timedelta(hours=1)
    registry.approve(mid, "TEST-ONLY fixture approval; not production validation", approved_at)
    relationships, tokens = build_statistical_relationships(markets, clock())
    relationships = tuple(r.model_copy(update={"id": "TEST-ONLY-approved-" + r.id}) for r in relationships)
    return Activation(
        registry=registry,
        model_id=mid,
        relationships=relationships,
        relationship_tokens=tokens,
        settlement_reviews={},
        correlation_groups={"m1": "e1", "m2": "e1"},
        report_id="TEST-ONLY-report",
        approved_at=approved_at,
        expires_at=clock() + timedelta(hours=1),
        allowed_tiers=("standard",),
    )


async def cycle(runtime, clock, *, shift=False):
    runtime.adapter.shift = shift
    clock.advance(1)
    await runtime.cycle()


async def test_unapproved_real_validation_collects_persists_and_never_requests_fees(tmp_path, now):
    clock = Clock(now)
    adapter = FakeAdapter(clock)
    cfg = configuration(tmp_path)
    runtime = LivePaperRuntime(cfg, adapter=adapter, clock=clock)
    try:
        await cycle(runtime, clock)
        state = runtime.state()
        assert state["mode"] == "live_market_paper"
        assert state["initial_bankroll"] == state["bankroll"] == state["cash"] == 500
        assert state["operation"]["scan"]["markets_scanned"] == 2
        assert state["operation"]["current_books"] == 2
        assert len(state["relationships"]) == 1 and len(state["evidence"]) == 1
        assert not state["orders"] and not state["positions"] and not state["opportunities"]
        assert "no_approved_real_market_strategy" in state["operation"]["last_cycle"]["suppression_reasons"]
        assert not adapter.fee_calls
        assert runtime.health()["trading_status"] == "validation_blocked"
        assert not runtime.health()["live_trading_enabled"]
        with pytest.raises(ValueError, match="Synthetic scenarios"):
            runtime.run_scenario()
    finally:
        await runtime.close()
    restarted = LivePaperRuntime(cfg, adapter=FakeAdapter(clock), clock=clock)
    try:
        assert restarted.state()["cash"] == 500
        assert restarted.state()["operation"]["cycles"] == 1
        assert restarted.broker.reconcile(now=clock())["consistent"]
    finally:
        await restarted.close()


async def test_repeated_source_timestamp_cannot_inflate_baseline(tmp_path, now):
    clock = Clock(now)
    adapter = FakeAdapter(clock)
    runtime = LivePaperRuntime(configuration(tmp_path), adapter=adapter, clock=clock)
    try:
        await cycle(runtime, clock)
        first = runtime.engine.checkpoint()["states"][0]
        source = max(m.timestamp for m in runtime.prices.values())
        # Repeat each token's precise original timestamp, not a newly fetched time.
        original = adapter.book

        async def repeat(mid, token):
            book = await original(mid, token)
            return book.model_copy(update={"timestamp": runtime.prices[token].timestamp})

        adapter.book = repeat
        await cycle(runtime, clock)
        second = runtime.engine.checkpoint()["states"][0]
        assert first["samples"] == second["samples"] == 1
        assert first["baseline"] == second["baseline"]
        assert max(m.timestamp for m in runtime.prices.values()) == source
    finally:
        await runtime.close()


async def test_checkpoint_restart_preserves_causal_state_and_scan_cursor(tmp_path, now):
    clock = Clock(now)
    cfg = configuration(tmp_path)
    adapter = FakeAdapter(clock)
    runtime = LivePaperRuntime(cfg, adapter=adapter, clock=clock)
    await cycle(runtime, clock)
    await cycle(runtime, clock)
    checkpoint = runtime.engine.checkpoint()
    next_offset = runtime.scan["next_offset"]
    await runtime.close()
    next_adapter = FakeAdapter(clock)
    restarted = LivePaperRuntime(cfg, adapter=next_adapter, clock=clock)
    try:
        assert restarted.engine.checkpoint() == checkpoint
        assert next_adapter.discovery_offset == next_offset
        await cycle(restarted, clock)
        assert restarted.engine.checkpoint()["states"][0]["samples"] == 3
        assert restarted.scan["next_offset"] == next_offset + 2
    finally:
        await restarted.close()


async def test_book_rotation_offset_survives_restart(tmp_path, now):
    clock = Clock(now)
    cfg = configuration(tmp_path).model_copy(update={"books_per_cycle": 1})
    first = LivePaperRuntime(cfg, adapter=FakeAdapter(clock), clock=clock)
    await cycle(first, clock)
    assert first.offset == 1
    await first.close()
    adapter = FakeAdapter(clock)
    second = LivePaperRuntime(cfg, adapter=adapter, clock=clock)
    try:
        assert second.offset == 1
        await cycle(second, clock)
        assert adapter.book_calls[0] == ("m2", "t2")
    finally:
        await second.close()


async def test_exclusive_writer_and_persistent_kill_switch(tmp_path, now):
    clock = Clock(now)
    cfg = configuration(tmp_path)
    runtime = LivePaperRuntime(cfg, adapter=FakeAdapter(clock), clock=clock)
    with pytest.raises(ValueError, match="another paper coordinator"):
        LivePaperRuntime(cfg, adapter=FakeAdapter(clock), clock=clock)
    runtime.stop()
    await runtime.close()
    restarted = LivePaperRuntime(cfg, adapter=FakeAdapter(clock), clock=clock)
    try:
        assert restarted.suspended
        await cycle(restarted, clock)
        assert restarted.state()["suspended"] and not restarted.state()["orders"]
    finally:
        await restarted.close()


async def test_archive_budget_stops_ingestion_before_network_or_capital_changes(tmp_path, now):
    clock = Clock(now)
    adapter = FakeAdapter(clock)
    runtime = LivePaperRuntime(configuration(tmp_path, max_archive_mb=1), adapter=adapter, clock=clock)
    try:
        (runtime.directory / "events.sqlite-budget-test").write_bytes(b"0" * 1024 * 1024)
        await runtime.cycle()
        assert runtime.last_error == "archive_or_disk_budget_exhausted"
        assert not adapter.book_calls and runtime.totals["cycles"] == 0
        assert runtime.state()["cash"] == 500
    finally:
        await runtime.close()


@pytest.mark.parametrize("bad", ["stale", "empty_book", "fail_books"])
async def test_stale_missing_or_disconnected_books_do_not_trade(tmp_path, now, bad):
    clock = Clock(now)
    adapter = FakeAdapter(clock)
    setattr(adapter, bad, True)
    runtime = LivePaperRuntime(configuration(tmp_path), adapter=adapter, clock=clock)
    try:
        await cycle(runtime, clock)
        state = runtime.state()
        assert state["operation"]["fresh_books"] == 0
        assert not state["orders"] and state["exposure"] == 0
        assert all(not e["qualified"] for e in state["evidence"])
    finally:
        await runtime.close()


async def test_discovery_failure_recovery_keeps_bankroll_and_working_latch(tmp_path, now):
    clock = Clock(now)
    adapter = FakeAdapter(clock)
    adapter.fail_discovery = True
    runtime = LivePaperRuntime(configuration(tmp_path), adapter=adapter, clock=clock)
    try:
        with pytest.raises(ConnectionError):
            await runtime.cycle()
        assert not runtime.working and runtime.state()["cash"] == 500
        adapter.fail_discovery = False
        await cycle(runtime, clock)
        assert runtime.totals["cycles"] == 1 and runtime.health()["status"] == "ok"
    finally:
        await runtime.close()


async def test_test_only_activation_flows_through_real_intelligence_risk_and_broker(tmp_path, now):
    clock = Clock(now)
    adapter = FakeAdapter(clock)
    validation = TestOnlyValidation(clock)
    activation = fixture_activation(clock, adapter.markets())
    validation.activation = activation
    runtime = LivePaperRuntime(configuration(tmp_path), adapter=adapter, validation=validation, clock=clock)
    try:
        for _ in range(20):
            await cycle(runtime, clock)
        assert not runtime.state()["orders"]
        await cycle(runtime, clock, shift=True)
        await cycle(runtime, clock, shift=True)
        calls_before_fill_cycle = len(adapter.book_calls)
        await cycle(runtime, clock, shift=True)
        state = runtime.state()
        assert len(adapter.book_calls) >= calls_before_fill_cycle + 5  # Includes post-latency book re-fetch.
        assert state["orders"] and state["positions"]
        assert any(order["status"] == "filled" for order in state["orders"])
        assert state["operation"]["fills"] >= 1
        assert state["operation"]["qualified_opportunities"] >= 1
        assert state["risk_decisions"][0]["approved"]
        assert state["cash"] < 500 and state["exposure"] > 0
        assert state["operation"]["service"]["ledger_consistent"]
        assert adapter.fee_calls
        cash = state["cash"]
    finally:
        await runtime.close()
    restarted = LivePaperRuntime(configuration(tmp_path), adapter=FakeAdapter(clock), clock=clock)
    try:
        assert restarted.state()["cash"] == pytest.approx(cash)
        assert restarted.state()["positions"]
        assert restarted.broker.reconcile(now=clock())["consistent"]
    finally:
        await restarted.close()


async def test_revocation_during_fee_fetch_never_submits_order(tmp_path, now):
    clock = Clock(now)
    adapter = FakeAdapter(clock)
    validation = TestOnlyValidation(clock)
    validation.activation = fixture_activation(clock, adapter.markets())
    runtime = LivePaperRuntime(configuration(tmp_path), adapter=adapter, validation=validation, clock=clock)
    try:
        for _ in range(20):
            await cycle(runtime, clock)
        await cycle(runtime, clock, shift=True)
        await cycle(runtime, clock, shift=True)
        runtime.fees.clear()
        adapter.fee_callback = lambda: setattr(validation, "activation", None)
        await cycle(runtime, clock, shift=True)
        assert not runtime.state()["orders"]
        assert "strategy_revoked_or_expired" in runtime.last_cycle["suppression_reasons"]
    finally:
        await runtime.close()


async def test_unreviewed_settlement_withheld_without_invented_pnl(tmp_path, now):
    clock = Clock(now)
    adapter = FakeAdapter(clock)
    validation = TestOnlyValidation(clock)
    validation.activation = fixture_activation(clock, adapter.markets())
    runtime = LivePaperRuntime(configuration(tmp_path), adapter=adapter, validation=validation, clock=clock)
    try:
        for _ in range(20):
            await cycle(runtime, clock)
        await cycle(runtime, clock, shift=True)
        await cycle(runtime, clock, shift=True)
        await cycle(runtime, clock, shift=True)
        position = runtime.risk.positions(now=clock())[0]
        market = runtime.markets[position.token_id]
        adapter.settlement_result = SettlementObservation(
            id="synthetic-resolution-test",
            timestamp=clock(),
            available_at=clock(),
            source="synthetic-resolution-test",
            market_id=market.market_id,
            event_id=market.event_id,
            token_id=market.token_id,
            condition_id="test-condition",
            payout=1,
            resolution_source=market.resolution_source,
            resolution_rules=market.resolution_rules,
            transaction_hash="test-tx",
            outcome_index=0,
            reporter="UMA_OO",
        )
        before = runtime.risk.snapshot(now=clock())
        await runtime._settle(clock())
        after = runtime.risk.snapshot(now=clock())
        assert before["cash"] == after["cash"] and after["realized_pnl"] == 0
        assert runtime.risk.positions(now=clock())
        assert runtime.last_error == "settlement_withheld_unreviewed_rules"
        runtime.config = LivePaperConfig.model_validate(
            {
                **runtime.config.model_dump(),
                "allow_simulated_settlement": True,
                "settlement_review_actor": "TEST-ONLY external semantics review",
                "settlement_rule_hashes": {
                    market.token_id: identity(
                        market.market_id,
                        market.token_id,
                        market.outcome,
                        market.resolution_rules,
                        market.resolution_source,
                    )
                },
            }
        )
        original = adapter.settlement_result
        adapter.settlement_result = original.model_copy(update={"token_id": "wrong-reviewed-token"})
        await runtime._settle(clock())
        assert runtime.risk.positions(now=clock())
        assert runtime.last_error == "settlement_observation_identity_or_rules_mismatch"
        adapter.settlement_result = original
        await runtime._settle(clock())
        settled = runtime.state()
        assert not settled["positions"]
        assert settled["simulated_realized_pnl"] == pytest.approx(
            position.quantity - position.quantity * position.average_cost - 0.04
        )
        assert settled["operation"]["settlements"] == 1
        assert settled["realized_pnl"] == 0  # No real financial P/L.
    finally:
        await runtime.close()


async def test_wrong_market_identity_cannot_contaminate_midpoint_or_marks(tmp_path, now):
    clock = Clock(now)
    adapter = FakeAdapter(clock)
    adapter.wrong_identity = True
    runtime = LivePaperRuntime(configuration(tmp_path), adapter=adapter, clock=clock)
    try:
        await cycle(runtime, clock)
        assert not runtime.prices
        assert not runtime.books
        assert not runtime.state()["orders"]
    finally:
        await runtime.close()


async def test_expiry_during_fee_fetch_never_submits_order(tmp_path, now):
    clock = Clock(now)
    adapter = FakeAdapter(clock)
    validation = TestOnlyValidation(clock)
    validation.activation = fixture_activation(clock, adapter.markets())
    runtime = LivePaperRuntime(configuration(tmp_path), adapter=adapter, validation=validation, clock=clock)
    try:
        for _ in range(20):
            await cycle(runtime, clock)
        await cycle(runtime, clock, shift=True)
        await cycle(runtime, clock, shift=True)
        runtime.fees.clear()
        adapter.fee_callback = lambda: clock.advance(7200)
        await cycle(runtime, clock, shift=True)
        assert not runtime.state()["orders"]
        assert "strategy_revoked_or_expired" in runtime.last_cycle["suppression_reasons"]
    finally:
        await runtime.close()
