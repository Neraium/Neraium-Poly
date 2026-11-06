"""Controlled integration records; no fixture is installed in operational archives."""

import hashlib
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from neraium_poly.contracts import Record
from neraium_poly.data import EventStore
from neraium_poly.data.segmented import ManagedEventStore
from neraium_poly.experimental.config import ExperimentalConfig
from neraium_poly.experimental.runtime import ExperimentalRuntime
from neraium_poly.ops.live import LivePaperRuntime
from neraium_poly.ops.live_config import LivePaperConfig
from neraium_poly.research.archive import QuoteArchive, replay_sampled_books
from test_experimental_runtime import Clock, Feed, Fees
from test_live_operation import FakeAdapter


class ControlledPayload(Record):
    text: str


def fill(store, now, count=4):
    for i in range(count):
        store.append(ControlledPayload(id=f"filler-{i}", timestamp=now, available_at=now,
                                       source="CONTROLLED", text="fixture" * 1000))


def test_quote_references_and_history_survive_legacy_rotation_and_restart(tmp_path, book, now):
    path = tmp_path / "events.sqlite"
    original = EventStore(path)
    quotes = QuoteArchive(original)
    quotes.record(book)
    state = quotes.state
    original.close()
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    settings = {"segment_bytes": 4096, "budget_bytes": 64 * 1024**2, "min_free_bytes": 0}
    store = ManagedEventStore(path, **settings)
    try:
        quotes = QuoteArchive(store, state)
        fill(store, now)
        later = book.model_copy(update={"id": "later-observed", "timestamp": now + timedelta(seconds=1),
                                        "available_at": now + timedelta(seconds=2)})
        quotes.record(later)
        store.maintain()
        assert replay_sampled_books(store) == (book, later)
        assert store.count(kind="OrderBookSnapshot") == 1
        assert store.count(kind="BookReceipt") == 1
        count = store.count()
        saved = quotes.state
    finally:
        store.close()
    store = ManagedEventStore(path, **settings)
    try:
        assert store.count() == count
        assert not QuoteArchive(store, saved).record(later)
        assert replay_sampled_books(store) == (book, later)
        assert hashlib.sha256(path.read_bytes()).hexdigest() == digest
    finally:
        store.close()


async def test_experimental_managed_archive_preserves_stop_and_certified_account(tmp_path, now):
    certified = tmp_path / "certified"
    certified.mkdir()
    sentinel = certified / "existing-evidence"
    sentinel.write_text("CONTROLLED certified evidence")
    before = sentinel.read_bytes()
    config = ExperimentalConfig(data_dir=tmp_path / "experimental", certified_directory=certified,
                                archive_management_enabled=True, archive_reserve_disk_mb=8192,
                                archive_segment_mb=1, archive_budget_mb=64, fee_batch=0,
                                event_research_enabled=False)
    clock = Clock(now)
    r = ExperimentalRuntime(config, feed=Feed(clock), clock=clock, fee_adapter=Fees())
    try:
        r.account.stop(now=now)
        await r.cycle()
        assert r.state()["archive"]["health"] == "ok"
        assert r.state()["kill_switch"] is True
        assert r.state()["cash"] == 500
        count = r.events.count()
    finally:
        await r.close()
    r = ExperimentalRuntime(config, feed=Feed(clock), clock=clock, fee_adapter=Fees())
    try:
        assert r.events.count() == count
        await r.cycle()
        assert r.account.snapshot(now=now)["kill_switch"] is True
        assert r.state()["orders_attempted"] == 0
        assert r.state()["cash"] == 500 and r.state()["simulated_pnl"] == 0
    finally:
        await r.close()
    assert sentinel.read_bytes() == before


@pytest.mark.parametrize("fault", ["maintain", "status"])
async def test_managed_collector_fault_stops_stream_and_keeps_archive_health_visible(tmp_path, now, fault):
    clock = Clock(now)
    config = LivePaperConfig(data_dir=tmp_path / "collector", coverage_enabled=False,
                            archive_management_enabled=True, archive_reserve_disk_mb=8192,
                            archive_budget_mb=64)
    r = LivePaperRuntime(config, adapter=FakeAdapter(clock), clock=clock)
    real = r.events
    broken = SimpleNamespace(maintain=lambda: None, status=lambda: {"health": "ok"})

    def fail():
        raise OSError("CONTROLLED archive fault")

    setattr(broken, fault, fail)
    r.events = broken
    coverage = SimpleNamespace(stop_stream=AsyncMock())
    r.coverage = coverage
    try:
        await r.cycle()
        coverage.stop_stream.assert_awaited_once()
        assert r._archive_status()["health"] == "blocked"
        assert "CONTROLLED archive fault" in r._archive_status()["last_error"]
        assert r.risk.snapshot(now=now)["cash"] == 500
    finally:
        r.coverage = None
        r.events = real
        await r.close()


async def test_experimental_archive_exception_latches_stop_before_feed_or_order(tmp_path, now):
    clock = Clock(now)
    config = ExperimentalConfig(data_dir=tmp_path / "experimental", certified_directory=tmp_path / "certified",
                                archive_management_enabled=True, archive_reserve_disk_mb=8192,
                                archive_budget_mb=64, fee_batch=0, event_research_enabled=False)
    r = ExperimentalRuntime(config, feed=Feed(clock), clock=clock, fee_adapter=Fees())
    real = r.events

    def fail():
        raise OSError("CONTROLLED maintenance fault")

    r.events = SimpleNamespace(maintain=fail, status=lambda: {"health": "ok"})
    try:
        await r.cycle()
        state = r.state()
        assert state["kill_switch"] is True and state["orders_attempted"] == 0
        assert state["archive"]["health"] == "blocked" and state["cash"] == 500
    finally:
        r.events = real
        await r.close()


@pytest.mark.parametrize("kind", ["collector", "experimental"])
async def test_failed_post_open_initialization_releases_both_owner_locks(tmp_path, now, monkeypatch, kind):
    from neraium_poly.experimental import runtime as experimental_module
    from neraium_poly.ops import live as live_module

    clock = Clock(now)

    def fail(*_args):
        raise ValueError("CONTROLLED recovered quote failure")

    module = live_module if kind == "collector" else experimental_module
    original = module.QuoteArchive
    monkeypatch.setattr(module, "QuoteArchive", fail)
    if kind == "collector":
        config = LivePaperConfig(data_dir=tmp_path / kind, coverage_enabled=False,
                                archive_management_enabled=True, archive_reserve_disk_mb=8192,
                                archive_budget_mb=64)
        create = lambda: LivePaperRuntime(config, adapter=FakeAdapter(clock), clock=clock)
    else:
        config = ExperimentalConfig(data_dir=tmp_path / kind, certified_directory=tmp_path / "certified",
                                    archive_management_enabled=True, archive_reserve_disk_mb=8192,
                                    archive_budget_mb=64, fee_batch=0, event_research_enabled=False)
        create = lambda: ExperimentalRuntime(config, feed=Feed(clock), clock=clock, fee_adapter=Fees())
    with pytest.raises(ValueError, match="CONTROLLED recovered"):
        create()
    monkeypatch.setattr(module, "QuoteArchive", original)
    recovered = create()
    try:
        assert recovered.events.status()["health"] == "ok"
    finally:
        await recovered.close()
