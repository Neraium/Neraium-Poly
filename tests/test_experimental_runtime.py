"""Controlled integration fixtures; no fixture is installed in operational accounts."""

import hashlib
from datetime import UTC, datetime, timedelta

import pytest
from neraium_poly.experimental.config import ExperimentalConfig
from neraium_poly.experimental.contracts import SharedMarketFrame
from neraium_poly.experimental.runtime import ExperimentalRuntime
from test_experimental_account import book, fee, market, signal


@pytest.fixture
def moment():
    return datetime(2026, 11, 6, 12, tzinfo=UTC)


class Clock:
    def __init__(self, now):
        self.now = now

    def __call__(self):
        return self.now


class Feed:
    def __init__(self, clock):
        self.clock = clock
        self.market = market(clock())
        self.stale = False
        self.failed = False
        self.closed = False

    async def read(self):
        if self.failed:
            raise ConnectionError("Controlled exchange disconnect")
        now = self.clock()
        b = book(now - timedelta(seconds=20) if self.stale else now)
        return SharedMarketFrame(
            timestamp=now,
            available_at=now,
            source="neraium-poly/public-market-frame/v1",
            producer_health={"status": "ok", "live_trading_enabled": False},
            markets=(self.market,),
            books=(b,),
        )

    async def close(self):
        self.closed = True


class Fees:
    async def close(self):
        pass


def runtime(tmp_path, moment):
    config = ExperimentalConfig(
        data_dir=tmp_path / "experimental",
        certified_directory=tmp_path / "certified",
        max_tokens=2,
        min_free_disk_mb=512,
        fee_batch=0,
    )
    clock = Clock(moment)
    feed = Feed(clock)
    r = ExperimentalRuntime(config, feed=feed, clock=clock, fee_adapter=Fees())
    return r, clock, feed


async def test_real_frame_pipeline_archives_inputs_and_rejections_without_approval(tmp_path, moment):
    r, _clock, feed = runtime(tmp_path, moment)
    try:
        await r.cycle()
        s = r.state()
        assert s["account_id"] == "experimental-paper" and s["cash"] == 500
        assert s["source_fresh_books"] == s["experimental_fresh_books"] == 1
        assert s["experimental_totals"]["signals"] == 6 and not s["orders"]
        assert s["rejection_reasons"]["unknown_fee_schedule"] > 0
        assert s["last_cycle"]["market_record_ids"] == [feed.market.id]
        assert s["last_cycle"]["strategy_code_sha256"] == r.model_hash
        assert r.events.count() > 0
    finally:
        await r.close()


async def test_pending_order_fills_only_from_new_post_latency_frame_and_recovers(tmp_path, moment):
    certified = tmp_path / "certified"
    certified.mkdir()
    sentinel = certified / "risk.sqlite"
    sentinel.write_bytes(b"protected certified fixture")
    digest = hashlib.sha256(sentinel.read_bytes()).hexdigest()
    r, clock, feed = runtime(tmp_path, moment)
    try:
        b = book(moment)
        r.fees[b.token_id] = fee(moment)
        submitted = r.account.submit(signal(moment, b), feed.market, b, now=moment, fee_schedule=fee(moment))
        assert submitted["status"] == "submitted"
        await r.cycle()
        assert r.state()["fills"] == 0
        clock.now += timedelta(seconds=1)
        await r.cycle()
        s = r.state()
        assert s["fills"] == 1 and len(s["positions"]) == 1
        assert s["pnl_valuation"] == "fresh_observed_bid_marks_or_cash"
        assert s["mark_sources"][b.token_id]["source_timestamp"] == clock.now.isoformat()
        cash = s["cash"]
    finally:
        await r.close()
    assert hashlib.sha256(sentinel.read_bytes()).hexdigest() == digest
    restarted = ExperimentalRuntime(r.config, feed=Feed(clock), clock=clock, fee_adapter=Fees())
    try:
        s = restarted.state()
        assert s["cash"] == cash and len(s["positions"]) == 1
        assert s["reconciliation"]["consistent"]
    finally:
        await restarted.close()


async def test_stale_held_marks_are_labeled_and_cannot_create_entries(tmp_path, moment):
    r, clock, feed = runtime(tmp_path, moment)
    try:
        b = book(moment)
        r.fees[b.token_id] = fee(moment)
        r.account.submit(signal(moment, b), feed.market, b, now=moment, fee_schedule=fee(moment))
        clock.now += timedelta(seconds=1)
        await r.cycle()
        assert r.state()["positions"]
        clock.now += timedelta(seconds=20)
        feed.stale = True
        await r.cycle()
        s = r.state()
        assert s["stale_mark_tokens"] == [b.token_id]
        assert s["pnl_valuation"] == "stale_last_observed_marks"
        assert len(s["orders"]) == 1
    finally:
        await r.close()


async def test_storage_limit_latches_only_experimental_stop(tmp_path, moment):
    r, _clock, _feed = runtime(tmp_path, moment)
    try:
        r._budget_ok = lambda: False
        await r.cycle()
        s = r.state()
        assert s["suspended"] and s["service"]["last_error"] == "experimental_storage_budget_exhausted"
        assert s["cash"] == 500 and not s["orders"]
    finally:
        await r.close()


def test_storage_and_port_configuration_cannot_alias_certified_account(tmp_path):
    with pytest.raises(ValueError):
        ExperimentalConfig(data_dir=tmp_path, certified_directory=tmp_path)
    with pytest.raises(ValueError):
        ExperimentalConfig(port=18742)
    with pytest.raises(ValueError):
        ExperimentalConfig(enabled_strategies=("unregistered",))
