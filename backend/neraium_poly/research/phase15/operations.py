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


def experimental_research(runtime, *, for_operations=False):
    event = runtime.event_operations_summary() if for_operations and hasattr(runtime,"event_operations_summary") else runtime._event_summary()
    stop = runtime.account.risk.snapshot(now=runtime.clock())["kill_switch"]
    challenger = None
    if getattr(runtime, "phase23", None):
        challenger = runtime.phase23.status()
        outcome = runtime.phase23_outcomes.status() if runtime.phase23_outcomes else {}
        challenger["outcome_verification"] = outcome
        challenger["pending_forecasts"] = max(0, challenger["forecasts"]-outcome.get("verified_forecasts", 0))
        challenger["verified_forecast_outcomes"] = outcome.get("verified_forecasts", 0)
        challenger["resolved_events_scope"] = "reviewed independent events; individual verified forecast outcomes are separate"
        for model_id, count in outcome.get("verified_by_model", {}).items():
            if model_id in challenger.get("models", {}):
                challenger["models"][model_id]["resolved"] = count
        challenger["competition"] = runtime.phase23_competition.status() if runtime.phase23_competition else None
        challenger["runtime_error"] = runtime.phase23_error
    domain = None
    if getattr(runtime, "phase24", None):
        domain = runtime.phase24.status()
        outcomes = runtime.phase24_outcomes.status()
        domain["outcome_verification"] = outcomes
        resolved = 0
        for model_id, count in outcomes.get("verified_by_model", {}).items():
            if model_id in domain["models"]:
                domain["models"][model_id]["resolved"] = count
                resolved += count
        domain["pending_forecasts"] = max(0, domain["forecasts"]-resolved)
        domain["leaderboard"] = runtime.phase24_report
        domain["runtime_error"] = runtime.phase24_error
    expansion = {"status": "disabled", "trading_authority": False}
    if getattr(runtime, "phase25", None):
        expansion = runtime.phase25.status()
        verification = runtime.phase25_outcomes.status()
        expansion["outcome_verification"] = verification
        expansion["leaderboard"] = runtime.phase25_report
        expansion["runtime_error"] = runtime.phase25_error
        expansion["discovery"] = runtime.phase25_universe.status()
        for name, count in verification.get("verified_by_model", {}).items():
            if name in expansion["models"]:
                expansion["models"][name]["resolved"] = count
    elif getattr(runtime, "phase25_error", None):
        expansion = {"status": "unavailable", "runtime_error": runtime.phase25_error, "trading_authority": False}
    intelligence = {"status": "disabled", "trading_authority": False}
    if getattr(runtime, "phase26_enabled", False):
        intelligence = {"status": "source_anchored_research", "inputs": runtime.phase26_inputs.status() if runtime.phase26_inputs else None,
            "projection": runtime.phase26_report, "runtime_error": runtime.phase26_error, "trading_authority": False,
            "scope": "stable full declared-model registry projection; original legacy journals separately reconciled"}
    findings = getattr(runtime, "phase27", None)
    return {
        "phase28": runtime.phase28.status() if getattr(runtime,"phase28",None) else {"status":"unavailable" if getattr(runtime,"phase28_error",None) else "disabled","runtime_error":getattr(runtime,"phase28_error",None),"trading_authority":False},
        "phase27": findings.status() if findings else {"status": "unavailable" if getattr(runtime, "phase27_error", None) else "disabled", "runtime_error": getattr(runtime, "phase27_error", None), "trading_authority": False},
        "phase26": intelligence,
        "phase25": expansion,
        "phase24": domain if domain is not None else {"status": "unavailable" if getattr(runtime, "phase24_error", None) else "disabled",
                        "runtime_error": getattr(runtime, "phase24_error", None), "trading_authority": False},
        "domains": event.get("domains", {"status": "unavailable"}),
        "event_summary_verification": {k:event.get(k) for k in (
            "summary_status","summary_verified_completed_at","summary_age_seconds","summary_max_age_seconds",
            "summary_refresh_error","summary_scope")},
        "phase16_execution": runtime.phase16_execution_status(for_operations=True) if for_operations else runtime.phase16_execution_status(),
        "phase23": challenger if challenger is not None else {"status": "unavailable" if getattr(runtime, "phase23_error", None) else "disabled",
                        "last_error": getattr(runtime, "phase23_error", None), "trading_authority": False},
        "phase21": ({**runtime.phase21.summary(), "runtime_error": runtime.phase21_error}
                    if getattr(runtime, "phase21", None) else {"status": "unavailable" if getattr(runtime, "phase21_error", None) else "disabled",
                        "last_error": getattr(runtime, "phase21_error", None), "trading_authority": False}),
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
        "historical_qualification": (event["historical_qualification"] if "historical_qualification" in event else {"status":"pending_verified_background_summary"} if for_operations else runtime._qualification()),
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
