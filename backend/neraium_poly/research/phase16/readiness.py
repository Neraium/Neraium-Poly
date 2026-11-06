"""Explain research readiness without confusing marks, calibration or authority."""

from datetime import UTC, datetime
from math import isfinite


def _number(value):
    return type(value) in (int, float) and isfinite(value) and value >= 0


def _mapping(value):
    return value if isinstance(value, dict) else {}


def _freshness(value, now):
    try:
        at = value if isinstance(value, datetime) else datetime.fromisoformat(value)
        if at.tzinfo is None:
            return None, "unaware_history_timestamp"
        age = (now - at).total_seconds()
        if age < 0:
            return None, "future_history_timestamp"
        return age, None
    except (TypeError, ValueError):
        return None, "history_timestamp_unavailable"


def build_readiness(history_summary, *, execution=None, calibration=None, now):
    """A current observation of prerequisite sufficiency, never an admission gate.

    Mark-label counts describe a bounded causal quote cohort. They cannot satisfy
    the independent resolved-event requirements for terminal forecasting. A cost
    estimate is a conditional research estimate, not evidence of profitability.
    Missing scores and edge remain null, rather than acquiring synthetic zeros.
    """
    if not isinstance(now, datetime) or now.tzinfo is None:
        raise ValueError("aware_readiness_cutoff_required")
    now = now.astimezone(UTC)
    history, execution, calibration = map(_mapping, (history_summary, execution, calibration))
    missing, defects, market_conditions = [], [], []
    token_rows = history.get("per_token", [])
    if isinstance(token_rows, dict):
        token_rows = list(token_rows.values())
    if not isinstance(token_rows, list):
        token_rows = []
        defects.append("malformed_token_coverage")
    qualified_tokens = []
    source_times = [r.get("latest_source_at") for r in token_rows if isinstance(r, dict) and r.get("latest_source_at")]
    source_ages = [(value, _freshness(value, now)[0]) for value in source_times]
    valid_sources = [(value, age) for value, age in source_ages if age is not None]
    at = min(valid_sources, key=lambda pair: pair[1])[0] if valid_sources else history.get("last_observation_at", history.get("observed_at"))
    for token in token_rows:
        if not isinstance(token, dict):
            defects.append("malformed_token_coverage")
            continue
        source_age, source_error = _freshness(token.get("latest_source_at"), now)
        receipt_age, receipt_error = _freshness(token.get("latest_available_at"), now)
        if source_error in {"unaware_history_timestamp", "future_history_timestamp"}:
            defects.append("token_source_" + source_error)
        if receipt_error in {"unaware_history_timestamp", "future_history_timestamp"}:
            defects.append("token_receipt_" + receipt_error)
        identity = all(isinstance(token.get(k), str) and 0 < len(token[k]) <= 256
                       for k in ("token_id", "market_id", "event_id"))
        if not identity:
            defects.append("incomplete_token_coverage_identity")
        enough = (_number(token.get("observations")) and token["observations"] >= 40
            and _number(token.get("matured_labels")) and token["matured_labels"] >= 20
            and _number(token.get("span_seconds")) and token["span_seconds"] >= 60
            and _number(token.get("max_gap_seconds")) and token["max_gap_seconds"] <= 120)
        if (identity and enough and source_error is None and receipt_error is None and source_age <= 15
            and receipt_age <= 15 and token.get("execution_evidence_complete") is True):
            qualified_tokens.append(token.get("token_id"))
    if not qualified_tokens:
        missing.append("per_token_causal_depth_history_and_matured_marks_required")
    age, timestamp_error = _freshness(at, now)
    if timestamp_error in {"unaware_history_timestamp", "future_history_timestamp"}:
        defects.append(timestamp_error)
    elif timestamp_error:
        missing.append(timestamp_error)
    if age is not None and age > 15:
        missing.append("current_qualified_quote_stale")
    for key in ("tokens_tracked", "valid_observations", "current_observations", "span_seconds",
                "max_gap_seconds", "matured_labels", "current_matured_labels", "unique_parent_events"):
        value = history.get(key)
        integer_count = key not in {"span_seconds", "max_gap_seconds"}
        if value is not None and (not _number(value) or integer_count and type(value) is not int):
            defects.append("invalid_history_metric:" + key)
    observations = history.get("current_observations")
    if not _number(observations) or observations < 40:
        missing.append("forty_causal_quote_observations_required")
    labels = history.get("current_matured_labels", history.get("matured_labels"))
    if not _number(labels) or labels < 20:
        missing.append("twenty_matured_horizon_labels_required")
    span = history.get("span_seconds")
    if not _number(span) or span < 60:
        missing.append("causal_horizon_coverage_required")
    gap = history.get("max_gap_seconds")
    if not _number(gap):
        missing.append("history_gap_coverage_unavailable")
    elif gap > 120:
        missing.append("historical_data_gap_requires_rewarming")
    if history.get("integrity_status") in {"failed", "corrupt"} or history.get("checkpoint_error"):
        defects.append("history_integrity_verification_failed")
    edge = execution.get("estimated_net_edge_per_share", execution.get("estimated_net_edge", execution.get("net_edge_per_share")))
    if edge is not None and (type(edge) not in (int, float) or not isfinite(edge)):
        defects.append("invalid_executable_edge_metric")
        edge = None
    if edge is None:
        missing.append("depth_and_cost_adjusted_edge_unavailable")
    elif edge < .03:
        market_conditions.append("estimated_edge_below_unchanged_0_03_threshold")
    reasons = execution.get("reasons", [])
    if isinstance(reasons, (list, tuple)):
        for reason in reasons:
            if not isinstance(reason, str):
                defects.append("malformed_execution_reason")
            elif "edge" in reason and edge is not None:
                market_conditions.append(reason)
            else:
                missing.append(reason)
    elif reasons:
        defects.append("malformed_execution_reasons")
    train, heldout = calibration.get("training_events"), calibration.get("heldout_events")
    if type(train) is not int or train < 100:
        missing.append("fewer_than_100_independent_training_events")
    if type(heldout) is not int or heldout < 100:
        missing.append("fewer_than_100_independent_heldout_events")
    if calibration.get("cohort_sufficient") is not True or calibration.get("metrics") is None:
        missing.append("independent_terminal_calibration_unavailable")
    missing = sorted(set(missing))
    defects = sorted(set(defects))
    market_conditions = sorted(set(market_conditions))
    status = ("implementation_defect" if defects else "insufficient_evidence" if missing
              else "cost_threshold_not_met" if market_conditions else "research_prerequisites_observed")
    return {
        "schema_version": "phase16-readiness-v1", "observed_at": now.isoformat(),
        "status": status, "insufficient_evidence": missing, "implementation_defects": defects,
        "market_conditions": market_conditions,
        "freshness": {"last_observation_at": at.isoformat() if isinstance(at, datetime) else at,
                      "source_age_seconds": age, "fresh_limit_seconds": 15},
        "historical_coverage": {key: history.get(key) for key in (
            "tokens_tracked", "valid_observations", "current_observations", "span_seconds", "max_gap_seconds",
            "matured_labels", "current_matured_labels", "unique_parent_events")},
        "history_rejections": _mapping(history.get("rejections")),
        "eligible_mark_tokens": qualified_tokens,
        "token_coverage_scope": "per-token>=40causal points,>=20retained matured marks, source/receipt<=15s, full execution evidence",
        "mark_labels_are_independent_outcome_events": False,
        "calibration": {"status": calibration.get("calibration_status", "unavailable"),
                        "training_events": train, "heldout_events": heldout,
                        "required_training_events": 100, "required_heldout_events": 100,
                        "metrics": calibration.get("metrics"), "blockers": calibration.get("blockers", [])},
        "estimated_executable_edge": edge,
        "edge_semantics": "conditional USD per outcome share after modeled costs; no validated trading advantage",
        "minimum_net_edge": .03, "research_only": True,
        "experimental_admission_authority": False, "certification_authority": False,
        "model_promotion_authority": False,
    }
