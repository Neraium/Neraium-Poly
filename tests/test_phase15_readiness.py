"""Controlled fixtures only; no production stop reset or authentic trade claims."""
import copy
import hashlib
from datetime import UTC, datetime, timedelta

import pytest
from neraium_poly.research.phase15.readiness import assess_recovery, digest, strategy_readiness
from neraium_poly.risk import RiskLimits
from test_experimental_account import account, book, fee, market, signal

NOW = datetime(2026, 11, 6, 20, tzinfo=UTC)


def evidence():
    service = {"status": "ok", "paper_trading": True, "live_trading_enabled": False,
               "timestamp": NOW.isoformat(), "trading_status": "validation_blocked"}
    archive = {"health": "ok", "usage_bytes": 100, "budget_bytes": 1000,
               "free_bytes": 100 * 1024**3, "global_floor_bytes": 8 * 1024**3,
               "seconds_to_exhaustion": 100000}
    value = {"captured_at": NOW.isoformat(), "account": {"cash": 500, "peak": 500, "realized": 0, "kill": 1},
             "certified_account": {"cash": 500, "peak": 500, "realized": 0},
             "marker": {"account_id": "experimental-paper", "mode": "experimental_paper", "schema_version": "1.0"},
             "paths_isolated": True, "limits": RiskLimits().model_dump(), "configured_limits": RiskLimits().model_dump(),
             "positions": 0, "orders": 0, "fills": 0, "pending_reservations": 0, "daily": [], "registry": [],
             "first_active_stop": {"seq": 5249, "timestamp": (NOW-timedelta(hours=1)).isoformat(), "payload": {"active": True}},
             "historical_snapshots": [
                 {"service": {"timestamp": (NOW-timedelta(hours=2)).isoformat(), "status": "ok"}, "kill_switch": False},
                 {"service": {"timestamp": NOW.isoformat(), "last_error": "experimental_storage_budget_exhausted",
                              "last_ingestion_at": (NOW-timedelta(hours=1,seconds=11)).isoformat()}, "kill_switch": True}],
             "services": {"collector": {"generated_at": NOW.isoformat(), "archive": archive,
                                        "operation": {"service": service, "connectivity": {"ws_connected": True, "fresh_books": 10}}},
                          "experimental": {"generated_at": NOW.isoformat(), "archive": archive, "service": service, "kill_switch": True}}}
    value = copy.deepcopy(value)
    return signed(value)


def signed(value):
    value.pop("evidence_sha256", None)
    value["evidence_sha256"] = digest(value)
    return value


def window():
    return {"all_healthy": True, "samples": 3, "duration_seconds": 60,
            "ended_at": NOW.isoformat(), "source_evidence_sha256": "a"*64}


def test_review_package_never_authorizes_or_clears_stop():
    value = evidence()
    before = copy.deepcopy(value)
    result = assess_recovery(value, now=NOW, observation_window=window())
    assert result["technical_conditions_pass"] and result["operator_reset_candidate"]
    assert not result["reset_authorized"] and not result["automatic_reset_authority"]
    assert not result["certified_strategy_authority"]
    assert result["assessment_sha256"] in result["owner_approval_request"]
    assert "5249" in result["owner_approval_request"]
    assert value == before


@pytest.mark.parametrize("change,reason", [
    (lambda v: v.update(captured_at=(NOW-timedelta(seconds=61)).isoformat()), "stale_or_future_readiness_evidence"),
    (lambda v: v["account"].update(cash=499), "nonbaseline_capital_requires_independent_reconciliation"),
    (lambda v: v["certified_account"].update(cash=499), "certified_account_requires_independent_reconciliation"),
    (lambda v: v.update(positions=1), "nonempty_account_requires_full_manual_reconciliation"),
    (lambda v: v["limits"].update(max_spread=.06), "operational_risk_limit_weakened_or_missing:max_spread"),
    (lambda v: v["services"]["collector"]["operation"]["service"].update(live_trading_enabled=True), "collector_paper_only_mode_unverified"),
    (lambda v: v["services"]["collector"]["operation"]["service"].update(trading_status="approved"), "certified_strategy_gate_not_verified_blocked"),
    (lambda v: v["services"]["experimental"].update(generated_at=(NOW-timedelta(seconds=31)).isoformat()), "experimental_source_observation_stale_or_future"),
    (lambda v: v["services"]["experimental"]["archive"].update(usage_bytes=1000), "experimental_storage_condition_unresolved"),
    (lambda v: v.update(historical_snapshots=[]), "original_stop_cause_unresolved"),
])
def test_recovery_fails_closed_for_unresolved_conditions(change, reason):
    value = evidence()
    change(value)
    result = assess_recovery(signed(value), now=NOW, observation_window=window())
    assert reason in result["blockers"] and not result["operator_reset_candidate"]
    assert result["owner_approval_request"] is None


def test_soak_and_integrity_required():
    result = assess_recovery(evidence(), now=NOW)
    assert "current_sustained_healthy_window_required" in result["blockers"]
    value = evidence()
    value["account"]["kill"] = 0
    with pytest.raises(ValueError, match="hash mismatch"):
        assess_recovery(value, now=NOW)


def test_six_strategies_only_two_supported_without_fabricated_metrics():
    result = strategy_readiness(evidence())
    assert len(result["strategies"]) == 6
    assert {r["strategy_id"] for r in result["strategies"] if r["order_admission_supported_by_current_engine"]} == {"short_horizon", "persistent_relationship"}
    assert all(r["current_estimated_net_edge"] is None and r["baseline_superiority"] is None for r in result["strategies"])
    assert all(not r["risk_ready"] and not r["certified_approval"] for r in result["strategies"])


def test_controlled_owner_reset_then_fresh_signal_risk_fill_restart_isolation(tmp_path):
    # This temporary account contains CONTROLLED fixtures, never real observations.
    certified = tmp_path / "certified"
    certified.mkdir()
    sentinel = certified / "risk.sqlite"
    sentinel.write_bytes(b"CONTROLLED certified sentinel")
    original = hashlib.sha256(sentinel.read_bytes()).hexdigest()
    a = account(tmp_path, NOW)
    a.stop(now=NOW)
    b = book(NOW)
    rejected = a.submit(signal(NOW,b),market(NOW),b,now=NOW,fee_schedule=fee(NOW))
    assert rejected["status"] == "rejected" and "kill_switch" in rejected["reasons"]
    a.close()
    a = account(tmp_path, NOW+timedelta(seconds=1))
    assert a.snapshot(now=NOW)["kill_switch"]
    explicit_fixture_owner_approval = True
    assert explicit_fixture_owner_approval
    a.risk.kill_switch(False, now=NOW+timedelta(seconds=1))
    t=NOW+timedelta(seconds=2)
    b=book(t)
    submitted=a.submit(signal(t,b),market(t),b,now=t,fee_schedule=fee(t))
    assert submitted["status"] == "submitted" and submitted["risk_decision"]["approved"]
    a.advance({b.token_id:book(t+timedelta(seconds=1))},now=t+timedelta(seconds=1))
    assert a.snapshot(now=t)["cash"] == pytest.approx(497.96)
    assert a.snapshot(now=t)["fills"] == 1
    a.close()
    a=account(tmp_path,t+timedelta(seconds=2))
    assert a.snapshot(now=t)["reconciliation"]["consistent"]
    assert a.snapshot(now=t)["cash"] == pytest.approx(497.96)
    a.close()
    assert hashlib.sha256(sentinel.read_bytes()).hexdigest() == original
