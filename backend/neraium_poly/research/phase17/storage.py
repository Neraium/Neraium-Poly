"""Pure bounded capacity forecasts; no deletion, retention or budget authority."""

import math
from datetime import UTC, datetime

GIB = 1024**3
CLASSES = {
    "active": "ACTIVE: open databases/WAL; append only; never compress or move",
    "warm": "WARM: immutable original segments; retain originals",
    "cold": "COLD: verified additional compressed representations; originals retained",
    "protected": "PROTECTED: account/forecast/audit and legacy evidence; preserve",
    "catalog_state": "PROTECTED: append-only source identity/catalog and restart state",
    "derived_cache": "DERIVED: existing verified cold cache; reproducible only with retained source proof",
    "segment_metadata": "PROTECTED: manifests/hash/provenance; preserve",
}


def _number(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def _time(value):
    at = value if isinstance(value, datetime) else datetime.fromisoformat(value)
    if at.tzinfo is None or at.utcoffset() is None:
        raise ValueError("aware storage time required")
    return at.astimezone(UTC)


def storage_growth(samples, *, now, budget_bytes, free_bytes, min_free_bytes=8 * GIB,
                   proposed_bytes=0, additional_bytes_per_second=0):
    """Restart-safe caller-owned observations, with allocation-jump uncertainty.

    Samples are ordered {at,usage_bytes,tier_usage_bytes?} records. At least five
    minutes are required for a provisional forecast. No finite interval proves
    indefinite operation, and missing/negative growth never means infinite runway.
    """
    now = _time(now)
    if not isinstance(samples, (list, tuple)) or len(samples) > 1008:
        raise ValueError("bounded storage samples required")
    if not all(_number(v) for v in (budget_bytes, free_bytes, min_free_bytes, proposed_bytes,
                                    additional_bytes_per_second)) or budget_bytes == 0:
        raise ValueError("finite known storage budgets required")
    floor = max(8 * GIB, min_free_bytes)
    valid, errors = [], []
    for row in samples:
        try:
            at = _time(row["at"])
            if at > now or not _number(row.get("usage_bytes")):
                raise ValueError("future or invalid capacity sample")
            if valid and at <= valid[-1][0]:
                raise ValueError("nonincreasing capacity samples")
            valid.append((at, row["usage_bytes"], row.get("tier_usage_bytes", {})))
        except (KeyError, TypeError, ValueError) as error:
            errors.append(str(error)[:100])
    alerts, rate, seconds = [], None, 0
    usage = valid[-1][1] if valid else None
    blocked = bool(errors) or usage is None or free_bytes < floor
    if errors:
        alerts.append("invalid_capacity_evidence")
    if usage is None:
        alerts.append("capacity_observation_unavailable")
    if free_bytes < floor:
        alerts.append("global_filesystem_floor")
    if valid and (now-valid[-1][0]).total_seconds() > 60:
        blocked = True
        alerts.append("stale_capacity_observation")
    headroom = None
    if usage is not None:
        headroom = max(0, min(budget_bytes-usage-proposed_bytes, free_bytes-floor-proposed_bytes))
        if usage+proposed_bytes >= budget_bytes:
            blocked = True
            alerts.append("service_budget_backpressure")
        elif usage >= .9*budget_bytes:
            alerts.append("service_usage_above90percent")
        if free_bytes-proposed_bytes < floor:
            blocked = True
            alerts.append("proposed_write_crosses_filesystem_floor")
    if len(valid) >= 2:
        seconds = (valid[-1][0]-valid[0][0]).total_seconds()
        delta = valid[-1][1]-valid[0][1]
        if delta < 0:
            alerts.append("net_usage_decreased_no_positive_growth_inference")
        elif seconds >= 300 and delta > 0:
            rate = delta/seconds
    if rate is None:
        alerts.append("growth_rate_insufficient_evidence")
    forecast_rate = rate+additional_bytes_per_second if rate is not None else None
    horizon = headroom/forecast_rate if headroom is not None and forecast_rate else None
    if horizon is not None and horizon < 48*3600:
        alerts.append("capacity_below48hours")
    elif horizon is not None and horizon < 7*86400:
        alerts.append("capacity_below7days")
    tiers = {}
    if valid:
        for key, description in CLASSES.items():
            amount = valid[-1][2].get(key) if isinstance(valid[-1][2], dict) else None
            tiers[key] = {"usage_bytes": amount if _number(amount) else None, "retention_class": description,
                          "original_removal_authorized": False}
    return {"schema_version": "phase17-capacity-v1", "observed_at": now.isoformat(),
            "status": "blocked" if blocked else "warning" if alerts else "ok", "backpressure": blocked,
            "alerts": alerts, "sample_errors": errors, "samples": len(valid), "window_seconds": seconds,
            "usage_bytes": usage, "budget_bytes": budget_bytes, "free_bytes": free_bytes,
            "global_floor_bytes": floor, "proposed_bytes": proposed_bytes, "headroom_bytes": headroom,
            "net_retained_growth_bytes_per_second": rate,
            "forecast_growth_bytes_per_second": forecast_rate, "seconds_to_capacity": horizon,
            "span_at_least24h": seconds >= 86400, "representative24h": False, "tier_classes": tiers,
            "missing_growth_is_not_zero": True, "indefinite_operation_proven": False,
            "budget_increase_authorized": False, "retention_change_authorized": False,
            "original_removal_authorized": False,
            "limitations": ["Net allocation includes WAL/cache/rotation changes; measure24h and7days",
                            "Compression adds verified copies; originals retained means no reclaimed bytes",
                            "Append-only catalogs grow even if a future original-retirement batch is approved"]}


def retention_proposal(archive, *, verified_cold_bytes=0, derived_cache_proof=False):
    """Reviewable non-executable classification; filenames never prove disposal safety."""
    if not isinstance(archive, dict) or not _number(verified_cold_bytes) or type(derived_cache_proof) is not bool:
        raise ValueError("known archive and verified nonnegative bytes required")
    usage, budget = archive.get("usage_bytes"), archive.get("budget_bytes")
    if not _number(usage) or not _number(budget) or budget <= 0:
        raise ValueError("known archive capacity required")
    tiers = archive.get("tier_usage_bytes", {})
    cache = tiers.get("derived_cache") if isinstance(tiers, dict) else None
    return {"schema_version": "phase17-retention-proposal-v1", "usage_bytes": usage,
            "budget_bytes": budget, "retention_classes": CLASSES,
            "verified_additional_cold_bytes": verified_cold_bytes,
            "derived_cache_bytes": cache if _number(cache) else None,
            "derived_cache_regeneration_proof_available": derived_cache_proof,
            "cache_note": "Existing cache is bounded64MiB; eviction requires its documented source/inode checks",
            "original_retirement_prerequisites": ["exact batch/path/hash manifest", "lossless verified cold copy",
                "successful independent recovery", "no active inode/process reference",
                "approved retention class", "separate explicit owner authorization"],
            "current_policy": "retain_original", "policy_changed": False, "removal_authorized": False,
            "budget_increase_authorized": False, "spending_authorized": False,
            "recommendation": "Preserve originals; bound new derived research/checkpoints; measure growth before owner-reviewed capacity decision"}
