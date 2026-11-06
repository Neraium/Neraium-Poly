"""Current read-only operational summaries; no approval or reset capability."""

from neraium_poly.research.phase15.budgets import capacity_status
from neraium_poly.research.phase15.readiness import STRATEGIES


def add_capacity(state, *, service, now):
    state["capacity"] = capacity_status(state.get("archive", {}), service=service,
                                        now=now, generated_at=state.get("generated_at"))
    return state


def experimental_research(runtime):
    event = runtime._event_summary()
    stop = runtime.account.risk.snapshot(now=runtime.clock())["kill_switch"]
    return {
        "domains": event.get("domains", {"status": "unavailable"}),
        "phase16_execution": runtime.phase16_execution_status(),
        "phase16": runtime.phase16.summary() if runtime.phase16 else {
            "status": "unavailable" if runtime.phase16_error else "disabled",
            "last_error": runtime.phase16_error, "trading_authority": False},
        "relationships": runtime.phase16.relationships.summary() if runtime.phase16 else (
            runtime.phase15_relationships.summary() if runtime.phase15_relationships else {"status": "disabled"}),
        "historical_qualification": event.get("historical_qualification", runtime._qualification()),
        "readiness_snapshot": {
            "generated_at": runtime.clock().isoformat(), "scope": "capability prerequisites, not model certification",
            "strategies": [{"strategy_id": name, "order_admission_supported": row["supported"],
                            "missing_prerequisites": row["missing"], "forecast_calibration": None,
                            "estimated_net_edge": None, "emergency_stop": stop}
                           for name, row in STRATEGIES.items()],
            "assessment": {"reset_authorized": False, "owner_approval_required": True,
                           "current_blocker": "emergency_stop_latched" if stop else "qualified_signal_required"},
        },
        "certification_authority": False, "trading_authority": False,
    }
