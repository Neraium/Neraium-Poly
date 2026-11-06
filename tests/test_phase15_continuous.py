"""Controlled fixtures; never counted as real relationship observations."""

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from neraium_poly.data import EventStore
from neraium_poly.ops.api import create_app
from neraium_poly.research.phase15.continuous import ContinuousRelationships
from neraium_poly.research.phase15.operations import add_capacity
from test_phase15_relationships import frame


def test_durable_study_restarts_without_duplicate_history(tmp_path):
    store = EventStore(tmp_path / "controlled.sqlite")
    try:
        service = ContinuousRelationships(store)
        f, now = frame()
        assert service.observe(f, now=now)
        assert not service.observe(f, now=now + timedelta(seconds=1))
        row = store.latest("RelationshipStudy", 1)[0]
        assert row["raw_sources"] == f
        assert row["qualified"] is row["trading_authority"] is False
        restored = ContinuousRelationships(store)
        assert restored.engine.checkpoint() == service.engine.checkpoint()
        assert not restored.observe(f, now=now)
        f, later = frame(1)
        assert restored.observe(f, now=later)
        assert store.count(kind="RelationshipStudy") == 2
    finally:
        store.close()


def test_archive_failure_cannot_advance_uncommitted_state(tmp_path, monkeypatch):
    store = EventStore(tmp_path / "controlled.sqlite")
    try:
        service = ContinuousRelationships(store)
        before = service.engine.checkpoint()
        def full(_record):
            raise OSError("CONTROLLED no space")
        monkeypatch.setattr(store, "append", full)
        f, now = frame()
        with pytest.raises(OSError):
            service.observe(f, now=now)
        assert service.engine.checkpoint() == before
        assert store.count() == 0
    finally:
        store.close()


def test_tampered_checkpoint_never_becomes_research_or_trading_authority(tmp_path, monkeypatch):
    store = EventStore(tmp_path / "controlled.sqlite")
    try:
        service = ContinuousRelationships(store)
        f, now = frame()
        service.observe(f, now=now)
        raw = store.latest("RelationshipStudy", 1)[0]
        raw["checkpoint_sha256"] = "0" * 64
        monkeypatch.setattr(store, "latest", lambda *_args, **_kwargs: [raw])
        with pytest.raises(ValueError):
            ContinuousRelationships(store)
    finally:
        store.close()


def test_operations_api_never_falls_back_to_synthetic_state():
    with TestClient(create_app()) as client:
        assert client.get("/api/operations-state").status_code == 404


def test_operations_unknown_capacity_fails_closed(now):
    result = add_capacity({"generated_at": now.isoformat(), "archive": {}}, service="collector", now=now)
    assert result["capacity"]["backpressure"]


async def test_continuous_runtime_recovery_preserves_isolated_stop(tmp_path, now):
    from neraium_poly.experimental.config import ExperimentalConfig
    from neraium_poly.experimental.runtime import ExperimentalRuntime
    from test_experimental_runtime import Clock, Feed, Fees

    cfg = ExperimentalConfig(data_dir=tmp_path / "experimental", certified_directory=tmp_path / "certified",
                             phase15_relationship_research_enabled=True, event_research_enabled=False,
                             fee_batch=0)
    clock = Clock(now)
    runtime = ExperimentalRuntime(cfg, feed=Feed(clock), clock=clock, fee_adapter=Fees())
    try:
        runtime.account.stop(now=now)
        await runtime.cycle()
        assert runtime.phase15_relationships.summary()["cycles"] == 1
        state = runtime.operations_state()
        assert state["cash"] == 500 and state["kill_switch"] is True
        assert state["operations_research"]["relationships"]["trading_authority"] is False
        assert len(state["operations_research"]["readiness_snapshot"]["strategies"]) == 6
    finally:
        await runtime.close()
    runtime = ExperimentalRuntime(cfg, feed=Feed(clock), clock=clock, fee_adapter=Fees())
    try:
        assert runtime.phase15_relationships.summary()["cycles"] == 1
        await runtime.cycle()
        assert runtime.events.count(kind="RelationshipStudy") == 1
        assert runtime.account.snapshot(now=now)["kill_switch"] is True
    finally:
        await runtime.close()
