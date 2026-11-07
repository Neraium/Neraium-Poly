"""Current read-only operational summaries; no approval or reset capability."""

from neraium_poly.research.phase15.budgets import capacity_status
from neraium_poly.research.phase15.readiness import STRATEGIES


def add_capacity(state, *, service, now):
    budget = state.get("archive", {}).get("budget_bytes")
    allocations = None
    if (service == "collector" and budget == 200*1024**3
        or service == "experimental" and budget == 100*1024**3):
        from neraium_poly.research.phase18.operations import tier_allocations

        allocations = tier_allocations(service)
    state["capacity"] = capacity_status(state.get("archive", {}), service=service,
                                        now=now, generated_at=state.get("generated_at"), allocations=allocations)
    return state


def experimental_research(runtime):
    event = runtime._event_summary()
    stop = runtime.account.risk.snapshot(now=runtime.clock())["kill_switch"]
    return {
        "domains": event.get("domains", {"status": "unavailable"}),
        "phase16_execution": runtime.phase16_execution_status(),
        "phase20": ({**runtime.phase20.summary(), "runtime_error": runtime.phase20_error}
                    if getattr(runtime, "phase20", None) else {"status": "unavailable" if getattr(runtime, "phase20_error", None) else "disabled",
                        "last_error": getattr(runtime, "phase20_error", None), "trading_authority": False}),
        "phase18": ({**runtime.phase18.summary(), "runtime_error": runtime.phase18_error}
                    if runtime.phase18 else {"status": "unavailable" if runtime.phase18_error else "disabled",
                        "last_error": runtime.phase18_error, "trading_authority": False}),
        "phase17": ({**runtime.phase17.summary(), "runtime_error": runtime.phase17_error}
                    if runtime.phase17 else {"status": "unavailable" if runtime.phase17_error else "disabled",
                        "last_error": runtime.phase17_error, "trading_authority": False}),
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
