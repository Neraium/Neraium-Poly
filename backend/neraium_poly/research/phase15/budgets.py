"""Measured, finite capacity planning; projections never grant retention authority."""

import math
from datetime import UTC, datetime

GIB = 1024**3
ALLOCATIONS = {
    "collector": {"active": GIB // 2, "warm": 16 * GIB, "cold": 32 * GIB,
                  "catalog_state": 15 * GIB // 2, "protected": 8 * GIB},
    "experimental": {"active": GIB // 4, "warm": 4 * GIB, "cold": 6 * GIB,
                     "catalog_state": 15 * GIB // 4, "protected": 2 * GIB},
}


def _number(value):
    return (not isinstance(value, bool) and isinstance(value, (int, float))
            and math.isfinite(value) and value >= 0)


def capacity_status(archive, *, service, now, generated_at=None, allocations=None):
    """Soft tier/horizon warnings, independent hard budget/free-space backpressure."""
    if service not in ALLOCATIONS or now.tzinfo is None:
        raise ValueError("known service and aware capacity cutoff required")
    usage, budget, free, floor = (archive.get(k) for k in
                                  ("usage_bytes", "budget_bytes", "free_bytes", "global_floor_bytes"))
    unavailable = not all(_number(v) for v in (usage, budget, free, floor)) or not budget
    stale = False
    if generated_at is not None:
        try:
            at = datetime.fromisoformat(generated_at) if isinstance(generated_at, str) else generated_at
            stale = at.tzinfo is None or not 0 <= (now - at).total_seconds() <= 60
        except (ValueError, TypeError, AttributeError):
            stale = True
    alerts = []
    if stale:
        alerts.append("stale_capacity_observation")
    if unavailable:
        alerts.append("capacity_observation_unavailable")
    blocked = unavailable or stale or archive.get("health") != "ok"
    if not unavailable:
        if usage >= budget:
            alerts.append("service_budget_exhausted")
            blocked = True
        elif usage >= budget * .9:
            alerts.append("service_usage_above_90_percent")
        elif usage >= budget * .75:
            alerts.append("service_usage_above_75_percent")
        if free < max(8 * GIB, floor):
            alerts.append("global_free_space_backpressure")
            blocked = True
    rate = archive.get("growth_bytes_per_second")
    horizon = None
    if not unavailable and _number(rate) and rate > 0:
        horizon = min(max(0, budget - usage), max(0, free - max(floor, 8 * GIB))) / rate
        if horizon < 48 * 3600:
            alerts.append("capacity_horizon_below_48_hours")
        elif horizon < 7 * 86400:
            alerts.append("capacity_horizon_below_7_days")
    else:
        alerts.append("growth_horizon_insufficient_evidence")
    allocations = ALLOCATIONS[service] if allocations is None else allocations
    if (not isinstance(allocations, dict) or set(allocations) != set(ALLOCATIONS[service])
        or not all(_number(v) for v in allocations.values())):
        raise ValueError("known finite soft tier allocations required")
    expected_budget = sum(allocations.values())
    if budget != expected_budget:
        alerts.append("tier_allocation_requires_budget_review")
    tiers = archive.get("tier_usage_bytes", {})
    for name, limit in allocations.items():
        used = tiers.get(name)
        if _number(used) and used >= limit:
            alerts.append(f"{name}_soft_allocation_saturated")
    return {
        "schema_version": "1.0", "observed_at": now.astimezone(UTC).isoformat(),
        "service": service, "status": "blocked" if blocked else "warning" if alerts else "ok",
        "backpressure": blocked, "alerts": alerts, "seconds_to_capacity": horizon,
        "tier_allocations_bytes": allocations, "tier_allocations_are_soft": True,
        "budget_increase_authorized": False, "retirement_authorized": False,
        "forecast_scope": "measured net retained bytes; variable workload and shared filesystem",
    }


def project_retention(*, current_usage, budget, daily_raw, daily_gzip, daily_catalog_state,
                      warm_days=1, days=90, proposed_original_removal=False):
    values = (current_usage, budget, daily_raw, daily_gzip, daily_catalog_state, warm_days, days)
    if not all(_number(v) for v in values) or not budget or not 1 <= days <= 366 or not 0 < warm_days <= days:
        raise ValueError("finite nonnegative measured retention inputs required")
    retain_raw = daily_raw * (warm_days if proposed_original_removal else days)
    projected = current_usage + retain_raw + days * (daily_gzip + daily_catalog_state)
    return {
        "days": days, "projected_usage_bytes": math.ceil(projected),
        "budget_bytes": budget, "fits_budget": projected <= budget,
        "warm_days": warm_days, "removal_assumption": proposed_original_removal,
        "scenario_only": proposed_original_removal, "removal_authorized": False,
        "catalog_growth_included": True, "months_guaranteed": False,
        "reason": "An approved original-removal policy is not assumed; forecasts require measured component rates",
    }
