"""Controlled transports test Phase8 guards; no operational approvals are created."""

import pytest
from neraium_poly.intelligence import RelationshipEngine, RelationshipPolicy
from neraium_poly.ops.live import LivePaperRuntime
from neraium_poly.ops.live_config import LivePaperConfig
from test_live_operation import (
    Clock,
    FakeAdapter,
    TestOnlyValidation,
    configuration,
    cycle,
    fixture_activation,
)


class TestCoverage:
    __test__ = False

    def __init__(self, adapter):
        self.adapter = adapter
        self.latest = {}
        self.resolved = False
        self.execution_requests = 0

    async def discover(self, **kwargs):
        return await self.adapter.discover_bounded(**kwargs)

    async def books(self, markets, limit):
        result = []
        for m in markets[:limit]:
            b = await self.adapter.book(m.market_id, m.token_id)
            self.latest[b.token_id] = b
            result.append(b)
        return result

    async def stop_stream(self):
        self.latest.clear()

    def start_stream(self, *args):
        return None

    def metrics(self):
        return {"ws_connected": False, "messages": 0, "gaps": 0}

    async def execution_book(self, token):
        self.execution_requests += 1
        if self.resolved:
            self.latest.pop(token, None)
            return None
        m = next(m for m in self.adapter.markets() if m.token_id == token)
        b = await self.adapter.book(m.market_id, token)
        self.latest[token] = b
        return b

    async def close(self):
        await self.adapter.close()


async def test_coverage_samples_without_changing_capital_or_approval(tmp_path, now):
    clock = Clock(now)
    adapter = FakeAdapter(clock)
    runtime = LivePaperRuntime(configuration(tmp_path, websocket_enabled=False), adapter=adapter, clock=clock)
    runtime.coverage = TestCoverage(adapter)
    try:
        await cycle(runtime, clock)
        s = runtime.state()
        assert s["operation"]["current_books"] == 2 and s["bankroll"] == 500
        assert s["operation"]["connectivity"]["ws_connected"] is False
        assert not s["orders"] and not s["operation"]["validation"]["active"]
    finally:
        await runtime.close()


async def test_gap_during_fee_wait_withholds_pre_gap_quote(tmp_path, now):
    clock = Clock(now)
    adapter = FakeAdapter(clock)
    validation = TestOnlyValidation(clock)
    validation.activation = fixture_activation(clock, adapter.markets())
    runtime = LivePaperRuntime(
        configuration(tmp_path, websocket_enabled=False), adapter=adapter, validation=validation, clock=clock
    )
    runtime.coverage = TestCoverage(adapter)
    runtime.trade_engine = RelationshipEngine(
        RelationshipPolicy(baseline_size=3, persistence_required=2, max_age_seconds=15)
    )
    try:
        for _ in range(3):
            await cycle(runtime, clock)
        await cycle(runtime, clock, shift=True)
        runtime.fees.clear()
        adapter.fee_callback = runtime.coverage.latest.clear
        await cycle(runtime, clock, shift=True)
        assert not runtime.state()["orders"]
        assert "feed_gap_or_resolution_invalidated_quote" in runtime.last_cycle["suppression_reasons"]
    finally:
        await runtime.close()


async def test_pending_execution_uses_resolution_guard_not_raw_rest(tmp_path, now):
    clock = Clock(now)
    adapter = FakeAdapter(clock)
    validation = TestOnlyValidation(clock)
    validation.activation = fixture_activation(clock, adapter.markets())
    runtime = LivePaperRuntime(
        configuration(tmp_path, websocket_enabled=False), adapter=adapter, validation=validation, clock=clock
    )
    runtime.coverage = TestCoverage(adapter)
    runtime.trade_engine = RelationshipEngine(
        RelationshipPolicy(baseline_size=3, persistence_required=2, max_age_seconds=15)
    )
    try:
        for _ in range(3):
            await cycle(runtime, clock)
        await cycle(runtime, clock, shift=True)
        runtime.coverage.resolved = True
        await cycle(runtime, clock, shift=True)
        assert runtime.coverage.execution_requests >= 1
        assert not runtime.risk.positions(now=clock())
        assert all(r.filled_quantity == 0 for r in runtime.broker.history())
    finally:
        await runtime.close()


def test_subscription_cap_fails_before_network():
    with pytest.raises(ValueError, match="subscription cap"):
        LivePaperConfig(max_markets=500, max_subscription_tokens=800)


async def test_one_sided_quote_after_fee_wait_is_explicitly_withheld(tmp_path, now):
    clock = Clock(now)
    adapter = FakeAdapter(clock)
    validation = TestOnlyValidation(clock)
    validation.activation = fixture_activation(clock, adapter.markets())
    runtime = LivePaperRuntime(
        configuration(tmp_path, websocket_enabled=False), adapter=adapter, validation=validation, clock=clock
    )
    runtime.coverage = TestCoverage(adapter)
    runtime.trade_engine = RelationshipEngine(
        RelationshipPolicy(baseline_size=3, persistence_required=2, max_age_seconds=15)
    )
    try:
        for _ in range(3):
            await cycle(runtime, clock)
        await cycle(runtime, clock, shift=True)
        runtime.fees.clear()

        def vanish():
            for token, book in list(runtime.coverage.latest.items()):
                runtime.coverage.latest[token] = book.model_copy(update={"asks": ()})

        adapter.fee_callback = vanish
        await cycle(runtime, clock, shift=True)
        assert not runtime.state()["orders"]
        assert "stale_or_incomplete_execution_book_after_network" in runtime.last_cycle["suppression_reasons"]
    finally:
        await runtime.close()
