"""Full reference workflow, API and public archival integration."""

import json
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from neraium_poly.data import EventStore
from neraium_poly.ops.api import create_app
from neraium_poly.ops.archive import PublicArchiveRuntime
from neraium_poly.ops.runtime import ResearchRuntime
from neraium_poly.settings import Settings


def test_complete_paper_flow_and_repeatable_economics():
    runtime = ResearchRuntime()
    runtime.run_scenario()
    state = runtime.state()
    assert state["orders"][0]["status"] == "filled"
    assert state["orders"][0]["filled_quantity"] == 10
    assert state["risk_decisions"][0]["approved"]
    assert len(state["positions"]) == 1
    assert state["exposure"] <= 100
    assert state["cash"] + state["positions"][0]["quantity"] * 0.41 == pytest.approx(state["bankroll"])
    assert state["realized_pnl"] == 0
    assert state["evidence"][-1]["qualified"]
    first = (state["cash"], state["bankroll"], state["orders"][0]["fees"], state["performance"])
    runtime.run_scenario()
    again = runtime.state()
    assert (again["cash"], again["bankroll"], again["orders"][0]["fees"], again["performance"]) == first
    replay = runtime.store.replay(until=runtime.clock - timedelta(seconds=1))
    assert not any(r["kind"] == "ExecutionReport" for r in replay)
    assert json.dumps(runtime.store.replay(), sort_keys=True) == json.dumps(
        runtime.store.replay(), sort_keys=True
    )


def test_kill_switch_latches_and_origin_guard():
    runtime = ResearchRuntime()
    runtime.run_scenario()
    with TestClient(create_app(runtime)) as client:
        assert client.get("/api/health").json()["live_trading_enabled"] is False
        assert (
            client.post("/api/kill-switch", headers={"Origin": "https://foreign.example"}).status_code == 403
        )
        assert client.post("/api/kill-switch").status_code == 200
        assert client.get("/api/state").json()["suspended"] is True
        assert client.post("/api/scenario").status_code == 409
    with pytest.raises(ValueError, match="latched"):
        runtime.run_scenario()


def test_live_flags_fail_closed(monkeypatch):
    monkeypatch.setenv("LIVE_TRADING_ENABLED", "true")
    with pytest.raises(ValueError):
        Settings.from_env()
    with pytest.raises(ValueError):
        create_app()
    monkeypatch.setenv("LIVE_TRADING_ENABLED", "false")
    monkeypatch.setenv("PAPER_TRADING", "false")
    with pytest.raises(ValueError):
        Settings.from_env()


def test_public_archive_data_is_separate_from_synthetic(tmp_path, market, book):
    path = tmp_path / "archive.sqlite"
    store = EventStore(path)
    store.append(market)
    store.append(book)
    store.close()
    runtime = PublicArchiveRuntime(path)
    state = runtime.state()
    assert state["mode"] == "public_readonly"
    assert state["markets"][0]["token_id"] == market.token_id
    assert not state["opportunities"]
    assert not state["orders"]
    with TestClient(create_app(runtime)) as client:
        assert client.post("/api/scenario").status_code == 409
