"""Read-only stop investigation and source-bound research readiness; no reset authority."""

import hashlib
import json
import math
import sqlite3
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path

from neraium_poly.risk import RiskLimits

STRATEGIES = {
    "cross_market_consistency": {
        "supported": False, "target": "logical complete-payoff constraints",
        "missing": ["independently reviewed exhaustive payoff scope", "multi-leg execution and hedge support"],
    },
    "persistent_relationship": {
        "supported": True, "target": "unvalidated sixty-second executable bid mark",
        "missing": ["persistent qualified relationship evidence", "causal bid history and matured errors", "positive conservative cost-adjusted edge"],
    },
    "liquidity_spread": {
        "supported": False, "target": "passive spread compensation",
        "missing": ["validated queue/adverse-selection model", "two-sided inventory execution support"],
    },
    "event_driven": {
        "supported": False, "target": "independent event-response repricing",
        "missing": ["independent predecision event context", "qualified response model"],
    },
    "short_horizon": {
        "supported": True, "target": "unvalidated sixty-second executable bid mark",
        "missing": ["forty causal prior bid observations", "twenty matured historical mark errors", "positive conservative cost-adjusted edge"],
    },
    "calibrated_forecast": {
        "supported": False, "target": "independent terminal outcome probability",
        "missing": ["independent context", "verified event labels", "held-out probability calibration"],
    },
}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _time(value):
    value = value if isinstance(value, datetime) else datetime.fromisoformat(value)
    if value.tzinfo is None:
        raise ValueError("aware readiness timestamps required")
    return value.astimezone(UTC)


def _read_db(path):
    if path.is_symlink() or not path.is_file():
        raise ValueError("existing non-aliased account database required")
    connection = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    connection.execute("BEGIN")
    return connection


def _service_state(directory, keys):
    db = _read_db(directory / "service.sqlite")
    result = {}
    try:
        for key in keys:
            row = db.execute("SELECT payload,digest FROM state WHERE key=?", (key,)).fetchone()
            if row:
                if hashlib.sha256(row["payload"].encode()).hexdigest() != row["digest"]:
                    raise ValueError("corrupt readiness service checkpoint")
                result[key] = json.loads(row["payload"])
    finally:
        db.close()
    return result


def classify_stop(evidence):
    stop = evidence.get("first_active_stop")
    if not stop or stop.get("payload", {}).get("active") is not True:
        return "original_stop_unverified"
    at = _time(stop["timestamp"])
    before, after = False, False
    for snapshot in evidence.get("historical_snapshots", []):
        service = snapshot.get("service") or {}
        if not service.get("timestamp"):
            continue
        captured = _time(service["timestamp"])
        before |= captured < at and snapshot.get("kill_switch") is False and service.get("status") == "ok"
        if (captured > at and snapshot.get("kill_switch") is True
            and service.get("last_error") == "experimental_storage_budget_exhausted"
            and service.get("last_ingestion_at")):
            after |= 0 <= (at - _time(service["last_ingestion_at"])).total_seconds() <= 120
    return "storage_auto_stop_strongly_corroborated_actor_unrecorded" if before and after else "stop_cause_requires_manual_investigation"


def capture_readiness(root, *, api_states=None):
    """Capture native snapshots without opening an account owner or issuing mutations.

    No production RiskEngine/ExperimentalAccount is instantiated. Native SQLite
    connections use mode=ro and query_only, and only loopback GETs are permitted.
    """
    root = Path(root).resolve()
    experimental = root / "data/experimental-paper"
    certified = root / "data/paper-live"
    if experimental.resolve() == certified.resolve() or experimental.is_symlink() or certified.is_symlink():
        raise ValueError("isolated native account directories required")
    for name in ("risk.sqlite", "broker.sqlite", "service.sqlite"):
        if (experimental / name).samefile(certified / name):
            raise ValueError("account database alias detected")
    marker = json.loads((experimental / "account.json").read_text())
    config = json.loads((root / "config/experimental-paper.example.json").read_text())
    db = _read_db(experimental / "risk.sqlite")
    try:
        account = dict(db.execute("SELECT * FROM account WHERE id=1").fetchone())
        limits = json.loads(account.pop("limits"))
        stop = db.execute("SELECT * FROM audit WHERE action='kill_switch' AND json_extract(payload,'$.active')=1 ORDER BY seq LIMIT 1").fetchone()
        stop = dict(stop) if stop else None
        if stop:
            stop["payload"] = json.loads(stop["payload"])
        actions = [dict(r) for r in db.execute("SELECT action,count(*) AS records,min(timestamp) AS first_at,max(timestamp) AS last_at FROM audit GROUP BY action")]
        registry = [dict(r) for r in db.execute("SELECT * FROM experimental_registry ORDER BY strategy")]
        positions = db.execute("SELECT count(*) FROM positions").fetchone()[0]
        pending = db.execute("SELECT count(*) FROM reservations WHERE released=0 AND remaining>0").fetchone()[0]
        daily = [dict(r) for r in db.execute("SELECT * FROM daily ORDER BY day DESC LIMIT 32")]
        attempts = []
        for r in db.execute("SELECT id,payload,result FROM experimental_signals ORDER BY rowid DESC LIMIT 100"):
            signal, result = json.loads(r["payload"]), json.loads(r["result"])
            attempts.append({"signal_id": r["id"], "signal_sha256": hashlib.sha256(r["payload"].encode()).hexdigest(),
                             "timestamp": signal["timestamp"], "strategy_id": signal["strategy_id"],
                             "market_id": signal["market_id"], "event_id": signal["event_id"],
                             "estimated_net_edge": signal.get("estimated_net_edge"),
                             "lower_value": signal.get("lower_value"), "fee_rate": signal.get("fee_rate"),
                             "slippage_per_share": signal.get("slippage_per_share"),
                             "result": result})
        lifetime_attempts = db.execute("SELECT count(*) FROM experimental_signals").fetchone()[0]
    finally:
        db.close()
    db = _read_db(certified / "risk.sqlite")
    try:
        certified_account = dict(db.execute("SELECT * FROM account WHERE id=1").fetchone())
        certified_account.pop("limits", None)
    finally:
        db.close()
    db = _read_db(experimental / "broker.sqlite")
    try:
        orders = db.execute("SELECT count(*) FROM orders").fetchone()[0]
        fills = db.execute("SELECT count(*) FROM audit WHERE action='fill_ack'").fetchone()[0]
    finally:
        db.close()
    checkpoints = _service_state(experimental, ["decision_trace", "experimental_totals", "strategy_code_hash"])
    snapshots = []
    for relative in ["data/phase13-operations/experimental-baseline.json", "data/phase14-operations/experimental-baseline.json"]:
        path = root / relative
        if path.exists() and path.stat().st_size < 8 * 1024**2:
            raw = path.read_bytes()
            value = json.loads(raw)
            snapshots.append({"path": relative, "sha256": hashlib.sha256(raw).hexdigest(),
                              "service": value.get("service"), "kill_switch": value.get("kill_switch"),
                              "last_cycle_timestamp": (value.get("last_cycle") or {}).get("timestamp")})
    if api_states is None:
        api_states = {}
        for name, port in [("collector", 18742), ("experimental", 18743)]:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/archive-state", timeout=15) as response:
                body = response.read(1024**2 + 1)
            if len(body) > 1024**2:
                raise ValueError("bounded readiness service observation required")
            api_states[name] = json.loads(body)
    evidence = {"schema_version": "1.0", "captured_at": datetime.now(UTC).isoformat(),
                "account_id": "experimental-paper", "marker": marker,
                "paths_isolated": True, "account": account, "certified_account": certified_account, "limits": limits,
                "configured_limits": RiskLimits(**config["risk_limits"]).model_dump(), "first_active_stop": stop,
                "audit_action_counts": actions, "registry": registry, "positions": positions,
                "pending_reservations": pending, "daily": daily, "orders": orders, "fills": fills,
                "lifetime_attempts": lifetime_attempts, "recent_attempts": attempts,
                "attempt_scope": "Last100 immutable attempts; lifetime count separate",
                "checkpoints": checkpoints, "historical_snapshots": snapshots, "services": api_states,
                "read_only": True, "automatic_reset_authority": False}
    evidence["evidence_sha256"] = digest(evidence)
    return evidence


def assess_recovery(evidence, *, now, observation_window=None):
    """Return a bounded review package, never an executable reset approval."""
    now = _time(now)
    value = dict(evidence)
    claimed = value.pop("evidence_sha256", None)
    if claimed != digest(value):
        raise ValueError("readiness evidence hash mismatch")
    blockers, warnings = [], ["Original stop audit records no actor or reason; owner must confirm reset intent"]
    age = (now - _time(value["captured_at"])).total_seconds()
    if not 0 <= age <= 60:
        blockers.append("stale_or_future_readiness_evidence")
    account = value.get("account", {})
    marker = value.get("marker", {})
    if not value.get("paths_isolated") or marker != {"account_id": "experimental-paper", "mode": "experimental_paper", "schema_version": "1.0"}:
        blockers.append("account_identity_or_isolation_unverified")
    expected = {"bankroll": 500, "aggregate_fraction": 0.2, "standard_min": 2, "standard_max": 5,
                "high_min": 5, "high_max": 15, "exceptional_min": 15, "exceptional_max": 25}
    if any(value.get("limits", {}).get(k) != v for k, v in expected.items()) or value.get("limits") != value.get("configured_limits"):
        blockers.append("risk_limits_or_configuration_mismatch")
    upper_bounds = {"market_fraction": 0.05, "event_fraction": 0.1, "correlation_fraction": 0.1,
                    "daily_loss_fraction": 0.05, "drawdown_fraction": 0.1,
                    "max_book_age_seconds": 15, "max_market_age_seconds": 3600,
                    "max_estimate_age_seconds": 300, "max_evidence_age_seconds": 3600,
                    "max_spread": 0.05, "max_liquidity_participation": 0.25, "approval_ttl_seconds": 10,
                    "kelly_fraction": 0.1}
    for name, bound in upper_bounds.items():
        number = value.get("limits", {}).get(name)
        if isinstance(number, bool) or not isinstance(number, (int, float)) or not math.isfinite(number) or not 0 < number <= bound:
            blockers.append("operational_risk_limit_weakened_or_missing:" + name)
    if value.get("limits", {}).get("min_net_edge", -1) < 0.03:
        blockers.append("net_edge_threshold_weakened")
    for key in ["cash", "peak", "realized"]:
        if isinstance(account.get(key), bool) or not isinstance(account.get(key), (int, float)) or not math.isfinite(account[key]):
            blockers.append("invalid_account_capital")
    if account.get("cash") != 500 or account.get("peak") != 500 or account.get("realized") != 0:
        blockers.append("nonbaseline_capital_requires_independent_reconciliation")
    certified_account = value.get("certified_account", {})
    if any(certified_account.get(k) != v for k, v in {"cash": 500, "peak": 500, "realized": 0}.items()):
        blockers.append("certified_account_requires_independent_reconciliation")
    if value.get("positions") != 0 or value.get("pending_reservations") != 0 or value.get("orders") != 0 or value.get("fills") != 0:
        blockers.append("nonempty_account_requires_full_manual_reconciliation")
    if any(row.get("pnl", 0) != 0 for row in value.get("daily", [])):
        blockers.append("nonzero_daily_loss_requires_review")
    if account.get("kill") != 1 or not value.get("first_active_stop"):
        blockers.append("original_active_stop_not_verified")
    services = value.get("services", {})
    for name in ("collector", "experimental"):
        service = services.get(name, {})
        health = service.get("operation", {}).get("service", {}) if name == "collector" else service.get("service", {})
        try:
            source_age = (now - _time(service.get("generated_at") or health["timestamp"])).total_seconds()
            if not 0 <= source_age <= 30:
                blockers.append(name + "_source_observation_stale_or_future")
        except (KeyError, TypeError, ValueError):
            blockers.append(name + "_source_timestamp_missing")
        if health.get("paper_trading") is not True or health.get("live_trading_enabled") is not False:
            blockers.append(name + "_paper_only_mode_unverified")
        if health.get("status") != "ok":
            blockers.append(name + "_service_unhealthy")
        archive = service.get("archive", {})
        if (archive.get("health") != "ok" or not isinstance(archive.get("usage_bytes"), int)
            or not isinstance(archive.get("budget_bytes"), int) or archive["usage_bytes"] >= archive["budget_bytes"]
            or archive.get("free_bytes", -1) < archive.get("global_floor_bytes", 8 * 1024**3)):
            blockers.append(name + "_storage_condition_unresolved")
        horizon = archive.get("seconds_to_exhaustion")
        if isinstance(horizon, bool) or not isinstance(horizon, (int, float)) or not math.isfinite(horizon) or horizon < 86400:
            blockers.append(name + "_capacity_horizon_not_verified_for24h")
    connection = services.get("collector", {}).get("operation", {}).get("connectivity", {})
    if connection.get("ws_connected") is not True or not isinstance(connection.get("fresh_books"), int) or connection["fresh_books"] < 1:
        blockers.append("fresh_public_order_books_unavailable")
    if services.get("collector", {}).get("operation", {}).get("service", {}).get("trading_status") != "validation_blocked":
        blockers.append("certified_strategy_gate_not_verified_blocked")
    if services.get("experimental", {}).get("kill_switch") is not True:
        blockers.append("api_and_native_stop_state_disagree")
    window = observation_window or {}
    try:
        window_valid = (window.get("all_healthy") is True and window.get("samples", 0) >= 3
                        and window.get("duration_seconds", 0) >= 60
                        and 0 <= (now - _time(window["ended_at"])).total_seconds() <= 60
                        and isinstance(window.get("source_evidence_sha256"), str)
                        and len(window["source_evidence_sha256"]) == 64
                        and not set(window["source_evidence_sha256"]) - set("0123456789abcdef"))
    except (KeyError, TypeError, ValueError):
        window_valid = False
    if not window_valid:
        blockers.append("current_sustained_healthy_window_required")
    if any(row.get("suspended") for row in value.get("registry", [])):
        blockers.append("independent_strategy_suspension_requires_review")
    cause = classify_stop(value)
    if cause != "storage_auto_stop_strongly_corroborated_actor_unrecorded":
        blockers.append("original_stop_cause_unresolved")
    blockers = sorted(set(blockers))
    report = {"schema_version": "1.0", "assessed_at": now.isoformat(), "account_id": "experimental-paper",
              "evidence_sha256": claimed, "original_stop": value.get("first_active_stop"),
              "cause_classification": cause,
              "technical_conditions_pass": not blockers, "blockers": blockers, "warnings": warnings,
              "operator_reset_candidate": not blockers, "reset_authorized": False,
              "automatic_reset_authority": False, "certified_strategy_authority": False,
              "observation_window": observation_window, "valid_until": (now + timedelta(minutes=5)).isoformat(),
              "approval_required": "Explicit owner approval of this source-bound assessment, original stop intent, account identity and one-time operator reset; revalidate immediately before any action"}
    report["assessment_sha256"] = digest(report)
    report["owner_approval_request"] = (
        f"Approve one operator-reviewed reset of experimental-paper stop audit seq{value['first_active_stop']['seq']} "
        f"under assessment {report['assessment_sha256']}, exclusively paper-only, with unchanged risk/strategy gates. "
        "Acknowledge that the original audit does not identify the actor. Do not replay expired signals."
    ) if not blockers else None
    return report


def strategy_readiness(evidence):
    """Six independent strategy statuses; metrics remain null without supporting data."""
    checkpoint = evidence.get("checkpoints", {}).get("decision_trace", {}).get("checkpoint", {})
    registry = {r["strategy"]: r for r in evidence.get("registry", [])}
    rows = []
    for name, definition in STRATEGIES.items():
        epoch = checkpoint.get("phase10_epoch", {}).get("strategies", {}).get(name, {})
        latest = checkpoint.get("latest_cycle", {}).get("strategies", {}).get(name, {})
        attempts = [r for r in evidence.get("recent_attempts", []) if r["strategy_id"] == name]
        rows.append({"strategy_id": name, "registered": bool(registry.get(name, {}).get("active")),
                     "suspended": bool(registry.get(name, {}).get("suspended")),
                     "order_admission_supported_by_current_engine": definition["supported"],
                     "valuation_target": definition["target"], "missing_prerequisites": definition["missing"],
                     "calibration": "unvalidated mark-error envelope; not terminal probability calibration" if definition["supported"] else "unsupported/insufficient independent evidence",
                     "epoch_counts": {k: v for k, v in epoch.items() if k != "reasons"},
                     "latest_cycle_counts": {k: v for k, v in latest.items() if k != "reasons"},
                     "epoch_rejections": {k: {"count": v["count"], "category": v["category"]} for k, v in epoch.get("reasons", {}).items()},
                     "recorded_recent_attempts": attempts, "current_estimated_net_edge": None,
                     "realized_trading_advantage": None, "baseline_superiority": None,
                     "liquidity": "current authentic complete bid/ask, spread<=0.05, source age<=15s, participation<=25%, verified fees",
                     "cost_model": "lower exit-bid mark*(1-fee)-entry ask*(1+fee)-0.02; minimum0.03/share",
                     "risk_ready": evidence.get("account", {}).get("kill") == 0,
                     "certified_approval": False, "experimental_authorization_is_not_certification": True})
    return {"schema_version": "1.0", "evidence_sha256": evidence.get("evidence_sha256"),
            "captured_at": evidence.get("captured_at"), "trace_epoch_started_at": checkpoint.get("epoch_started_at"),
            "last_evaluation_at": checkpoint.get("last_evaluation_at"), "strategies": rows,
            "scope": "Trace epoch counters cumulative; latest-cycle counters replace; rejection counts overlap. Recent attempts last100, not independent validation events.",
            "trading_authority": False, "certified_authority": False}
