"""Bounded rejection diagnostics with default-deny retrospective comparisons."""

from collections import Counter
from itertools import islice
from math import isfinite

from neraium_poly.research.phase14.relationships import digest

CATEGORIES = {"BUG", "MISSING EVIDENCE", "MARKET CONDITION", "RISK REJECTION",
              "STRATEGY LIMITATION", "CERTIFICATION DEPENDENCY"}


def _category(reason):
    if any(word in reason for word in ("calibration", "verified_labels", "independent_context")):
        return "CERTIFICATION DEPENDENCY"
    if any(word in reason for word in ("unsupported", "not_supported", "queue_and_adverse", "response_model")):
        return "STRATEGY LIMITATION"
    if any(word in reason for word in ("risk", "exposure", "kill_switch", "already_owned", "drawdown", "capital")):
        return "RISK REJECTION"
    if any(word in reason for word in ("spread", "edge", "stale", "liquidity", "out_of_order")):
        return "MARKET CONDITION"
    return "MISSING EVIDENCE"


def summarize_rejections(rows, *, verify_row=None):
    """Count sampled candidate rows, not silently extrapolated population totals.

    Inputs carry id, decision_at, event_id, reasons and optional evaluate_roundtrip
    costs. A raw verifier must independently bind that decision and its later
    observed label before numeric counterfactuals are shown. Even then this is a
    retrospective quote model, never a claim that a rejected order would fill.
    """
    bounded = list(islice(iter(rows), 10001))
    if len(bounded) > 10000:
        raise ValueError("rejection_rows_limit_exceeded")
    grouped, invalid, ambiguous, duplicates = {}, Counter(), set(), 0
    for row in bounded:
        try:
            if not isinstance(row, dict) or not isinstance(row.get("id"), str) or not 1 <= len(row["id"]) <= 256:
                raise ValueError("row_identity_required")
            if len(str(row)) > 262144:
                raise ValueError("row_size_limit_exceeded")
            identity, content = row["id"], digest(row)
            prior = grouped.get(identity)
            if prior and prior[0] != content:
                ambiguous.add(identity)
            elif prior:
                duplicates += 1
            grouped[identity] = (content, row)
        except (ValueError, TypeError, OverflowError) as error:
            invalid[str(error)[:100]] += 1
    categories, reasons, matched, negative, positive, zero = Counter(), {}, 0, 0, 0, 0
    unmatched = Counter()
    for identity, (_hash, row) in grouped.items():
        if identity in ambiguous:
            continue
        values = row.get("reasons")
        if not isinstance(values, (list, tuple)) or not values or len(values) > 64 or any(
            not isinstance(r, str) or not 1 <= len(r) <= 160 for r in values
        ):
            invalid["bounded_rejection_reasons_required"] += 1
            continue
        costs, verified = row.get("costs", {}), False
        try:
            verified = callable(verify_row) and verify_row(row) is True
        except Exception:  # noqa: BLE001 - verifier failure must withhold comparisons
            unmatched["source_replay_failed"] += 1
        net = costs.get("net_per_share") if isinstance(costs, dict) else None
        provenance = costs.get("provenance", {}) if isinstance(costs, dict) else {}
        bound = (verified and costs.get("depth_supported") is True and costs.get("execution_certified") is False
                 and type(net) in (int, float) and isfinite(net)
                 and isinstance(provenance, dict) and provenance.get("event_id") == row.get("event_id")
                 and provenance.get("decision_at") == row.get("decision_at")
                 and all(provenance.get(k) for k in ("decision_point_id", "label_point_id",
                                                   "decision_book_sha256", "label_book_sha256")))
        if bound:
            matched += 1
            negative += net < -1e-9
            positive += net > 1e-9
            zero += abs(net) <= 1e-9
        else:
            unmatched["matched_raw_causal_execution_evidence_unavailable"] += 1
        for reason in set(values):
            declared = row.get("categories", {}).get(reason) if isinstance(row.get("categories"), dict) else None
            category = declared if declared in CATEGORIES else _category(reason)
            categories[category] += 1
            report = reasons.setdefault(reason, {"count": 0, "category": category, "matched_modeled_cases": 0,
                "negative_modeled_cases": 0, "positive_modeled_cases": 0, "net_mark_sum_per_share": None,
                "mean_net_mark_per_share": None, "representative_ids": []})
            report["count"] += 1
            if len(report["representative_ids"]) < 3:
                report["representative_ids"].append(identity)
            if bound:
                report["matched_modeled_cases"] += 1
                report["negative_modeled_cases"] += net < -1e-9
                report["positive_modeled_cases"] += net > 1e-9
                report["net_mark_sum_per_share"] = (report["net_mark_sum_per_share"] or 0)+net
                report["mean_net_mark_per_share"] = report["net_mark_sum_per_share"]/report["matched_modeled_cases"]
    return {"schema_version": "phase17-rejection-diagnostics-v1", "input_rows": len(bounded),
            "unique_ids": len(grouped), "ambiguous_ids_quarantined": len(ambiguous),
            "exact_duplicate_rows": duplicates,
            "invalid_rows": dict(invalid), "categories_nonexclusive": dict(categories), "reasons": reasons,
            "matched_modeled_cases": matched, "negative_matched_modeled_cases": negative,
            "positive_matched_modeled_cases": positive, "zero_matched_modeled_cases": zero,
            "counterfactual_unavailable": dict(unmatched), "orders_proven_prevented_loss": None,
            "scope": "unique supplied sampled rejection rows; nonexclusive reasons do not sum to rows",
            "limitations": ["Retrospective matched quote arithmetic is not a hypothetical fill or causal benefit of rejection",
                            "Positive hindsight marks do not prove a restriction should be relaxed",
                            "Missing labels, data-gate failures and unsupported execution cannot receive fabricated P/L"],
            "threshold_change_authority": False, "trading_authority": False, "certification_authority": False}
