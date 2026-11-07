"""Purged quote-mark comparisons with parent-cluster inference and no authority."""

import hashlib
import json
import random
from collections import Counter, defaultdict
from datetime import timedelta
from math import isfinite, sqrt
from statistics import mean, pstdev

from neraium_poly.research.phase17.models import CANDIDATES, MODEL_VERSION, _at

MIN_INFERENCE_GROUPS = 20
BOOTSTRAP_REPLICATES = 1999
PLANNED_HYPOTHESES = 8  # four paired accuracy and four economic hypotheses


def _number(value):
    return type(value) in (int, float) and isfinite(value)


def _sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    allow_nan=False).encode()).hexdigest()


def _holm(pvalues, family_size=PLANNED_HYPOTHESES):
    """Missing planned hypotheses remain in the family with p=1."""
    result, previous = {}, 0.
    for rank, (key, p) in enumerate(sorted(pvalues.items(), key=lambda row: (row[1], row[0]))):
        adjusted = min(1., max(previous, (family_size-rank)*p))
        result[key], previous = adjusted, adjusted
    return result


def _inference(values):
    """One value per independently reviewed parent: equal-cluster estimand.

    Bootstrap resamples entire parent means, not correlated quote rows. The
    one-sided cluster sign-randomization test also relies on exchangeability
    under the null; small/unreviewed cohorts are withheld before this function.
    """
    rng = random.Random(170017)
    n, observed = len(values), mean(values)
    samples, extreme = [], 0
    for _ in range(BOOTSTRAP_REPLICATES):
        samples.append(mean(rng.choices(values, k=n)))
        randomized = mean(v*(1 if rng.getrandbits(1) else -1) for v in values)
        extreme += randomized >= observed-1e-15
    samples.sort()
    return {"cluster_equal_mean": observed,
            "interval_95": [samples[int(.025*(len(samples)-1))], samples[int(.975*(len(samples)-1))]],
            "p_one_sided": (extreme+1)/(BOOTSTRAP_REPLICATES+1),
            "parent_clusters": n, "bootstrap_replicates": BOOTSTRAP_REPLICATES,
            "seed": 170017,
            "assumptions": "Reviewed independent parents; exchangeable signed cluster effects under null"}


def _drawdown(values):
    capital = peak = worst = 0.
    for value in values:
        capital += value
        peak = max(peak, capital)
        worst = max(worst, peak-capital)
    return worst


def _metric(rows, candidate):
    if not rows:
        return {"samples": 0, "parent_groups": 0, "mae": None, "baseline_mae": None,
                "paired_mae_improvement": None, "rmse": None, "mean_error": None,
                "modeled_execution": None, "forecast_accuracy_inference": None,
                "net_value_inference": None}
    error = [r["forecasts"][candidate]-r["actual_bid"] for r in rows]
    baseline_error = [r["baseline"]-r["actual_bid"] for r in rows]
    executable = [r for r in rows if isinstance(r.get("costs"), dict)
                  and r["costs"].get("executable") is True
                  and _number(r["costs"].get("net_per_share"))
                  and _number(r["costs"].get("gross_per_share"))]
    selected = [r for r in executable if isinstance(r.get("estimated_edge_by_candidate"), dict)
                and _number(r["estimated_edge_by_candidate"].get(candidate))
                and r["estimated_edge_by_candidate"][candidate] >= .03]
    net = [r["costs"]["net_per_share"] for r in selected]
    return {"samples": len(rows), "parent_groups": len({r["event_id"] for r in rows}),
            "mae": mean(abs(v) for v in error), "baseline_mae": mean(abs(v) for v in baseline_error),
            "paired_mae_improvement": mean(abs(b)-abs(v) for b, v in zip(baseline_error, error, strict=True)),
            "rmse": sqrt(mean(v*v for v in error)), "mean_error": mean(error),
            "forecast_accuracy_inference": None, "net_value_inference": None,
            "modeled_execution": {"observed_roundtrip_examples": len(executable),
                "unconditional_mean_net_per_share": mean(r["costs"]["net_per_share"] for r in executable) if executable else None,
                "policy": "frozen predicted net>=0.03 USD/share; no threshold optimization",
                "selected_examples": len(selected),
                "selected_parent_groups": len({r["event_id"] for r in selected}),
                "mean_projected_edge": mean(r["estimated_edge_by_candidate"][candidate] for r in selected) if selected else None,
                "mean_gross_per_share": mean(r["costs"]["gross_per_share"] for r in selected) if selected else None,
                "mean_net_per_share": mean(net) if net else None,
                "net_variability": pstdev(net) if len(net) > 1 else None,
                "sequential_unit_share_drawdown": _drawdown(net) if net else None,
                "semantics": "hypothetical quote mark, not actual fill, account P/L or portfolio simulation"}}


def evaluate_experiments(rows, *, training_end, validation_end, cutoff, verify_row=None):
    """Evaluate a predeclared fixed family, default-denying unverified evidence.

    Temporal diagnostics are explicitly separate from event-disjoint held-out
    metrics. Parents shared with training or validation are excluded from strict
    heldout. Sixty-second episodes are nonoverlapping across ALL tokens belonging
    to one parent. Shared feature history can still induce dependence; inferential
    calculations require twenty reviewed independent held-out parent clusters.
    """
    training_end, validation_end, cutoff = map(_at, (training_end, validation_end, cutoff))
    if not training_end < validation_end < cutoff:
        raise ValueError("ordered_training_validation_cutoff_required")
    if not isinstance(rows, (list, tuple)) or len(rows) > 20000:
        raise ValueError("bounded_research_rows_required")
    encoded = json.dumps(rows, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    if len(encoded) > 32*1024**2:
        raise ValueError("research_dataset_byte_budget_exceeded")
    accepted, seen, ambiguous, rejections = [], {}, set(), Counter()
    for raw in rows:
        try:
            if not callable(verify_row) or verify_row(raw) is not True:
                raise ValueError("independent_raw_source_replay_required")
            if any(not isinstance(raw.get(k), str) or not 0 < len(raw[k]) <= 256
                   for k in ("id", "event_id", "token_id")):
                raise ValueError("bounded_row_identity_required")
            decision, target, available = (_at(raw[k]) for k in ("decision_at", "target_at", "label_available_at"))
            if not decision < target <= available <= cutoff or (target-decision).total_seconds() != 60:
                raise ValueError("invalid_target_or_availability_window")
            if raw.get("label_at") is not None:
                source = _at(raw["label_at"])
                if not target <= source <= available or (source-target).total_seconds() > 30:
                    raise ValueError("label_source_outside_observed_horizon")
            known = available
            if raw.get("label_observed_at") is not None:
                known = _at(raw["label_observed_at"])
                if not available <= known <= cutoff:
                    raise ValueError("future_or_inconsistent_label_receipt")
            forecasts = raw.get("forecasts")
            if not isinstance(forecasts, dict) or set(forecasts) != set(CANDIDATES):
                raise ValueError("frozen_candidate_family_required")
            if not all(_number(v) and 0 <= v <= 1 for v in [raw.get("actual_bid"), raw.get("baseline"), *forecasts.values()]):
                raise ValueError("invalid_monetary_mark")
            if abs(forecasts["unchanged"]-raw["baseline"]) > 1e-12:
                raise ValueError("unchanged_baseline_binding_mismatch")
            fingerprint = _sha(raw)
            if raw["id"] in seen:
                if seen[raw["id"]] != fingerprint:
                    ambiguous.add(raw["id"])
                raise ValueError("duplicate_or_conflicting_row_identity")
            seen[raw["id"]] = fingerprint
            accepted.append({**raw, "_decision": decision, "_target": target, "_available": available, "_known": known})
        except (KeyError, TypeError, ValueError, OverflowError) as error:
            reason = str(error) if str(error) in {
                "independent_raw_source_replay_required", "bounded_row_identity_required",
                "invalid_target_or_availability_window", "label_source_outside_observed_horizon",
                "future_or_inconsistent_label_receipt", "frozen_candidate_family_required",
                "invalid_monetary_mark", "unchanged_baseline_binding_mismatch",
                "duplicate_or_conflicting_row_identity"} else "invalid_research_row"
            rejections[reason] += 1
        except Exception:  # noqa: BLE001 - verifier failures cannot qualify research
            rejections["raw_verifier_failed"] += 1
    rejections["conflicting_original_quarantined"] += sum(r["id"] in ambiguous for r in accepted)
    accepted = [r for r in accepted if r["id"] not in ambiguous]
    accepted.sort(key=lambda r: (r["_decision"], r["id"]))
    groups = {name: [] for name in ("training", "validation", "temporal_heldout")}
    watermark = {}
    for row in accepted:
        decision, available = row["_decision"], row["_known"]
        if row["event_id"] in watermark and decision < watermark[row["event_id"]]:
            rejections["overlapping_parent_episode"] += 1
            continue
        if available <= training_end:
            group = "training"
        elif decision >= training_end+timedelta(seconds=90) and available <= validation_end:
            group = "validation"
        elif decision >= validation_end+timedelta(seconds=90):
            group = "temporal_heldout"
        else:
            rejections["purged_boundary_or_crossing_label"] += 1
            continue
        groups[group].append(row)
        watermark[row["event_id"]] = max(row["_target"], row["_known"])
    fit_parents = {r["event_id"] for group in ("training", "validation") for r in groups[group]}
    strict = [r for r in groups["temporal_heldout"] if r["event_id"] not in fit_parents]
    held_parents = {r["event_id"] for r in groups["temporal_heldout"]}
    strict_parents = {r["event_id"] for r in strict}
    reviewed = {r["event_id"] for r in strict if r.get("independence_reviewed") is True
                and isinstance(r.get("independence_evidence_sha256"), str)
                and len(r["independence_evidence_sha256"]) == 64
                and all(c in "0123456789abcdef" for c in r["independence_evidence_sha256"])}
    # One unreviewed row invalidates the entire parent's inferential eligibility.
    reviewed -= {r["event_id"] for r in strict if r.get("independence_reviewed") is not True
                 or not isinstance(r.get("independence_evidence_sha256"), str)
                 or len(r["independence_evidence_sha256"]) != 64
                 or any(c not in "0123456789abcdef" for c in r.get("independence_evidence_sha256", ""))}
    comparisons, pvalues = {}, {}
    for candidate in CANDIDATES:
        metrics = {name: _metric(part, candidate) for name, part in groups.items()}
        metrics["strict_event_disjoint_heldout"] = _metric(strict, candidate)
        infer = metrics["strict_event_disjoint_heldout"]
        if len(reviewed) >= MIN_INFERENCE_GROUPS and reviewed == strict_parents:
            improvement, selected_net = defaultdict(list), defaultdict(list)
            for row in strict:
                improvement[row["event_id"]].append(abs(row["baseline"]-row["actual_bid"])
                    -abs(row["forecasts"][candidate]-row["actual_bid"]))
                costs, edges = row.get("costs", {}), row.get("estimated_edge_by_candidate", {})
                if (isinstance(costs, dict) and costs.get("executable") is True
                    and isinstance(edges, dict) and _number(edges.get(candidate)) and edges[candidate] >= .03
                    and _number(costs.get("net_per_share"))):
                    selected_net[row["event_id"]].append(costs["net_per_share"])
            infer["forecast_accuracy_inference"] = _inference([mean(v) for _, v in sorted(improvement.items())])
            pvalues[candidate+":accuracy"] = infer["forecast_accuracy_inference"]["p_one_sided"]
            if len(selected_net) >= MIN_INFERENCE_GROUPS:
                infer["net_value_inference"] = _inference([mean(v) for _, v in sorted(selected_net.items())])
                pvalues[candidate+":net"] = infer["net_value_inference"]["p_one_sided"]
        validation, heldout = metrics["validation"], metrics["temporal_heldout"]
        metrics["research_drift"] = {"status": "insufficient_evidence" if not validation["samples"] or not heldout["samples"]
            else "deterioration_observed" if heldout["paired_mae_improvement"] < validation["paired_mae_improvement"]
            else "no_relative_deterioration_observed", "automatic_suspension": False}
        comparisons[candidate] = metrics
    adjusted = _holm(pvalues)
    for candidate, metrics in comparisons.items():
        for kind, key in (("accuracy", "forecast_accuracy_inference"), ("net", "net_value_inference")):
            value = metrics["strict_event_disjoint_heldout"][key]
            if value:
                value["holm_adjusted_p"] = adjusted[candidate+":"+kind]
                value["supported_positive_effect"] = value["interval_95"][0] > 0 and value["holm_adjusted_p"] < .05
    return {"schema_version": "phase17-purged-mark-experiment-v1", "model_version": MODEL_VERSION,
            "dataset_sha256": hashlib.sha256(encoded).hexdigest(), "input_rows": len(rows),
            "verified_unique_rows": len(accepted), "rejections": {k: v for k, v in rejections.items() if v},
            "split": {"training_end": training_end.isoformat(), "validation_end": validation_end.isoformat(),
                      "cutoff": cutoff.isoformat(), "purge_seconds": 90, "parent_episode_seconds": 60},
            "samples": {name: len(part) for name, part in groups.items()},
            "strict_event_disjoint_heldout_samples": len(strict),
            "training_or_validation_parent_groups": len(fit_parents),
            "temporal_heldout_parent_groups": len(held_parents),
            "overlapping_parent_groups": len(fit_parents & held_parents),
            "strict_heldout_parent_groups": len(strict_parents), "reviewed_independent_groups": len(reviewed),
            "inference_minimum_reviewed_groups": MIN_INFERENCE_GROUPS,
            "comparisons": comparisons, "multiple_testing": {"method": "Holm", "planned_hypotheses": 8,
                "evaluated_hypotheses": len(pvalues), "alpha": .05},
            "inference_status": "reviewed_cluster_inference_available" if pvalues else "insufficient_independent_evidence",
            "brier": None, "log_loss": None,
            "probability_calibration_status": "not_applicable_to_monetary_bid_marks",
            "independent_terminal_outcomes": 0, "certification_training_events": 0, "certification_heldout_events": 0,
            "limitations": ["Reconstructed forecasts unless separately committed prospectively",
                "Temporal quote episodes are not independent events; strict holdout removes fit parents",
                "Shared feature windows induce dependence; inference resamples reviewed parent clusters",
                "Selected quote mark arithmetic is not actual fills, account P/L or portfolio execution",
                "No score, CI, p value or hypothesis automatically grants strategy authority"],
            "research_only": True, "trading_authority": False, "certification_authority": False,
            "model_promotion_authority": False}
