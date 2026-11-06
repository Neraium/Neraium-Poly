"""Controlled operational presentation inputs; no fixture is a live observation."""
from datetime import UTC, datetime, timedelta
from io import StringIO

from neraium_poly.ops import monitor as module
from rich.console import Console


def sample():
    now = datetime.now(UTC).isoformat()
    service = {"status": "ok", "timestamp": now, "paper_trading": True, "live_trading_enabled": False}
    archive = {"usage_bytes": 6*1024**3, "budget_bytes": 64*1024**3,
        "growth_bytes_per_second": 1024, "seconds_to_exhaustion": 86400,
        "tier_usage_bytes": {"active": 1024**2, "warm": 1024**3, "cold": 2*1024**3},
        "cold_verified_segments": 3, "health": "ok"}
    c = {"mode": "live_market_paper", "generated_at": now, "cash": 500, "simulated_pnl": 0,
        "archive": archive, "capacity": {"status": "ok", "alerts": []},
        "operation": {"service": {**service, "trading_status": "validation_blocked"},
            "scan": {"discovered_markets": 200},
            "connectivity": {"ws_connected": True, "last_message_at": now, "fresh_books": 280}}}
    e = {"account_id": "experimental-paper", "generated_at": now, "cash": 500, "simulated_pnl": 0,
        "kill_switch": True, "service": service, "archive": {**archive, "budget_bytes": 16*1024**3},
        "capacity": {"status": "ok", "alerts": []}, "operations_research": {
            "domains": {"last_frame_at": now, "domains": {"sports": {"independent_forecasts": 2}}},
            "relationships": {"last_evaluation_at": now, "engine": {"evaluations": 75, "persistent_findings": 0}},
            "historical_qualification": {"qualifying_training_events": 0, "qualifying_heldout_events": 0,
                                         "chain_corroborated_exact_settlement_groups": 47},
            "readiness_snapshot": {"generated_at": now, "strategies": [{"id": "fixture"}],
                                   "assessment": {"status": "owner approval required"}}}}
    return c, e


def render(c=None, e=None, width=40, height=24, errors=()):
    out = StringIO(); console = Console(file=out, width=width, height=height, color_system=None)
    console.print(module.render_monitor(c, e, width=width, height=height, view="operations", errors=errors))
    value = out.getvalue()
    assert len(value.splitlines()) <= height
    assert all(len(row) <= width for row in value.splitlines())
    return value


def test_operations_phone_and_tiny_layout_preserve_banks_latch_and_live_prohibition():
    for width, height in ((30, 12), (40, 24), (80, 40)):
        c, e = sample(); value = render(c, e, width, height)
        assert "REAL MARKET DATA" in value
        assert "EXPERIMENTAL PAPER" in value and "CERTIFIED PAPER" in value
        assert value.count("$500.00") == 2 and "Stop ACTIVE" in value
        assert "LIVE TRADING DISABLED" in value
        if height >= 24:
            assert "64.0GiB" in value and "16.0GiB" in value
            assert "full 1.0d" in value and "A/W/C" in value
            assert "Cold verified 3" in value
            assert "Forecasts 2" in value and "Train/test 0 / 0" in value
            assert "SII eval 75 finds 0" in value


def test_unavailable_inputs_never_invent_bankroll_forecasts_or_safety_verification():
    value = render()
    assert "DATA STALE / UNAVAILABLE" in value and "$0.00" not in value
    assert "$500.00" not in value and "Forecasts —" in value
    assert "LIVE CONFIG UNVERIFIED" in value and "DISABLED" not in value


def test_old_or_future_service_source_timestamps_are_not_live():
    c, e = sample(); old = (datetime.now(UTC)-timedelta(seconds=61)).isoformat()
    c["generated_at"] = old; e["generated_at"] = old
    value = render(c, e)
    assert "REAL MARKET DATA" not in value and "stale" in value and "Last $500.00" in value
    assert "LIVE CONFIG UNVERIFIED" in value
    for field in ("last_message_at",):
        for stamp in (old, (datetime.now(UTC)+timedelta(minutes=2)).isoformat(), None):
            c, e = sample(); c["operation"]["connectivity"][field] = stamp
            value = render(c, e)
            assert "REAL MARKET DATA" not in value and "Fresh —" in value
    c, e = sample(); c["operation"]["service"]["timestamp"] = old
    assert "REAL MARKET DATA" not in render(c, e)


def test_stale_readiness_and_research_labeled_without_fake_current_inferences():
    c, e = sample(); old = (datetime.now(UTC)-timedelta(minutes=2)).isoformat()
    e["operations_research"]["readiness_snapshot"]["generated_at"] = old
    e["operations_research"]["domains"]["last_frame_at"] = old
    value = render(c, e)
    assert "Readiness unavailable/stale" in value
    assert "research snapshot stale" in value
    assert "owner approval required" not in value


def test_alerts_sanitized_and_unsafe_configuration_warning_overrides_default():
    c, e = sample(); e["service"]["live_trading_enabled"] = True
    e["capacity"]["alerts"] = ["disk\x1b[2Jfull"]
    value = render(c, e, height=40)
    assert "WARNING LIVE CONFIG UNSAFE" in value
    assert "diskfull" in value and "\x1b" not in value


def test_operations_view_uses_only_small_operations_endpoints(monkeypatch):
    urls = []
    async def fetch(certified, experimental):
        urls.extend([certified, experimental]); return *sample(), ()
    monkeypatch.setattr(module, "fetch_views", fetch)
    module.monitor(once=True, width=40, view="operations", no_color=True,
                   certified_url="http://127.0.0.1:18742/api/state",
                   experimental_url="http://127.0.0.1:18743/custom")
    assert urls == ["http://127.0.0.1:18742/api/operations-state", "http://127.0.0.1:18743/api/operations-state"]


def test_existing_views_keep_original_endpoint_semantics(monkeypatch):
    urls = []
    async def fetch(certified, experimental):
        urls.extend([certified, experimental]); return None, None, ()
    monkeypatch.setattr(module, "fetch_views", fetch)
    module.monitor(once=True, view="summary", no_color=True)
    assert all(url.endswith("/api/state") for url in urls)
    urls.clear(); module.monitor(once=True, view="archives", no_color=True)
    assert all(url.endswith("/api/archive-state") for url in urls)


def test_actual_readiness_historical_and_archive_contract_keys_render():
    c, e = sample()
    research = e["operations_research"]
    research["readiness_snapshot"]["assessment"] = {"owner_approval_required": True,
        "reset_authorized": False, "current_blocker": "emergency_stop_latched"}
    research["historical_qualification"] = {"qualified_training_events": 0, "qualified_heldout_events": 0,
        "chain_corroborated_exact_settlement_groups": 47}
    research["relationships"] = {"evaluations": 75, "persistent_findings": 0}
    for account in (c, e):
        account["archive"].pop("cold_verified_segments")
        account["archive"].update(compressed_segments=4, archive_tiers={"cold_proofs_present": 3})
    value = render(c, e, width=40, height=40)
    assert "emergency_stop_latched" in value and "Train/test 0 / 0" in value
    assert "SII eval 75 finds 0 · stale" in value
    assert "Gzip 4 Proofs 3" in value and "Stop ACTIVE · svc ok" in value
