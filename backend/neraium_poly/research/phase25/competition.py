"""Same-cohort challenger disagreement and guarded research-only edge diagnostics."""

import math
from collections import Counter, defaultdict

from neraium_poly.contracts import OrderBookSnapshot
from neraium_poly.data import assess_book
from neraium_poly.experimental.account import PUBLIC_BOOK_SOURCES
from neraium_poly.research.phase14.relationships import digest
from neraium_poly.research.phase18.capacity import capacity_scenarios
from neraium_poly.research.phase24.evaluation import evaluate

from .dependencies import AUTHORITY, at, bound_forecasts, review_events


def _number(value, low=0, high=1):
    return type(value) in (int, float) and math.isfinite(value) and low <= value <= high


def cohort_key(forecast, canonical_group):
    """Different target/timestamp/cutoff/book/conditioning is not a fair A/B pair."""
    f = forecast
    if not _number(f["probability"]):
        raise ValueError("finite_probability_required")
    return digest([canonical_group, f["market_id"], f["token_id"], f["rules_sha256"],
                   f["probability_semantics"], f.get("target_conditioning"), f.get("conditioning"),
                   f.get("unconditional_contract_probability"), at(f["timestamp"]).isoformat(),
                   at(f["evidence_cutoff"]).isoformat(), f["book_sha256"],
                   sorted(f.get("outcome_probabilities", {}))])


def executable_diagnostic(forecast, *, evaluated_at, forecast_verified=False, cost_evidence=None, cost_verifier=None):
    """Evaluate genuine bound depth; never turn uncalibrated estimates into edge.

    Costs must be independently supplied from native versioned evidence and bind
    this exact decision/market/book. A numerical forecast or recorded 'verified'
    flag never supplies calibration, fee, slippage or strategy admission.
    """
    f = forecast
    result = {"forecast_id": f.get("id"), "status": "withheld", "reasons": [],
              "estimated_net_edge": None, "capacity": None, "execution_authorized": False, **AUTHORITY}
    try:
        when = at(evaluated_at)
        if forecast_verified is not True:
            raise ValueError("independent_original_source_model_replay_required")
        book = OrderBookSnapshot.model_validate(f["book"])
        if (book.source not in PUBLIC_BOOK_SOURCES or book.exchange != "polymarket"
                or book.id != f["book_id"] or digest(book.model_dump(mode="json")) != f["book_sha256"]
                or book.market_id != f["market_id"] or book.token_id != f["token_id"]
                or not assess_book(book, when, max_spread=.05, expected_token=f["token_id"]).healthy
                or not at(f["timestamp"]) <= when < at(f["event_end_time"])):
            raise ValueError("causal_fresh_exact_executable_book_required")
        op = {"market_id": f["market_id"], "token_id": f["token_id"], "book_id": book.id,
              "book_sha256": f["book_sha256"], "evaluated_at": when.isoformat(),
              "end_time": None, "research_qualified": False}
        result["capacity"] = capacity_scenarios(op, book)
        result["capacity"]["time_to_forecast_cutoff_seconds"] = (at(f["event_end_time"])-when).total_seconds()
        result["capacity"]["capital_lockup_status"] = "settlement_and_redemption_timing_unverified"
        if (f.get("target_conditioning") or f.get("conditioning")
                or f.get("unconditional_contract_probability") is False
                or f.get("probability_semantics") != "binary_event_probability"
                or f.get("market_baseline_comparable") is False):
            raise ValueError("conditional_or_ternary_probability_not_unconditional_token_value")
        costs = cost_evidence
        if not isinstance(costs, dict) or not callable(cost_verifier):
            raise TypeError("independently_verified_decision_cost_and_calibration_evidence_required")
        cost_proof = cost_verifier(costs, f, as_of=when)
        if not isinstance(cost_proof, dict) or cost_proof.get("verified") is not True:
            raise TypeError("independently_verified_decision_cost_and_calibration_evidence_required")
        if (costs.get("forecast_id") != f["id"] or costs.get("book_sha256") != f["book_sha256"]
                or at(costs["available_at"]) > when or at(costs["calibration_cutoff"]) > at(f["timestamp"])
                or not isinstance(costs.get("calibration_artifact_sha256"), str)
                or len(costs["calibration_artifact_sha256"]) != 64
                or costs.get("calibration_verified") is not True
                or costs.get("event_disjoint_calibration_verified") is not True):
            raise ValueError("exact_causal_event_disjoint_calibration_and_cost_binding_required")
        lower, upper = f["lower_probability"], f["upper_probability"]
        fee, slippage, latency = (costs[k] for k in ("fee_rate", "slippage_per_share", "latency_adverse_selection_per_share"))
        if (not _number(lower) or not _number(upper) or not lower <= f["probability"] <= upper
                or not _number(fee) or not _number(slippage) or not _number(latency)
                or not _number(costs.get("capital_lockup_cost_per_share"))
                or not _number(costs.get("settlement_risk_cost_per_share"))):
            raise ValueError("finite_bounded_probability_and_all_cost_components_required")
        edge = lower * (1 - fee) - book.asks[0].price * (1 + fee) - slippage - latency
        edge -= costs["capital_lockup_cost_per_share"] + costs["settlement_risk_cost_per_share"]
        result["estimated_net_edge"] = edge
        if edge < .03:
            raise ValueError("conservative_after_cost_edge_below_existing_threshold")
        # Capacity's conservative fixed .02/share cost must cover all supplied
        # non-fee costs; otherwise its 'qualified' projection would overstate edge.
        if slippage + latency + costs["capital_lockup_cost_per_share"] + costs["settlement_risk_cost_per_share"] > .02:
            raise ValueError("native_capacity_fixed_cost_model_not_conservative_for_inputs")
        minimum = f["market"].get("min_order_size")
        if not _number(minimum, 1e-9, 1e9):
            raise ValueError("native_executable_minimum_order_size_required")
        op.update(research_qualified=True, fee_rate=fee, lower_probability=lower,
                  qualified_net_edge=edge, min_order_size=minimum)
        result["capacity"] = capacity_scenarios(op, book)
        result["capacity"]["time_to_forecast_cutoff_seconds"] = (at(f["event_end_time"])-when).total_seconds()
        result["capacity"]["capital_lockup_status"] = "settlement_and_redemption_timing_unverified"
        result["status"] = "qualified_research_diagnostic"
    except (ValueError, KeyError, TypeError, OverflowError, OSError, StopIteration) as error:
        result["reasons"].append(str(error)[:160])
    return result


def competition_report(studies, outcomes=(), *, as_of, forecast_verifier=None,
                       outcome_verifier=None, sii_pair_verifier=None):
    """Separate prospective disagreement from independently replayed performance."""
    now = at(as_of)
    reviews = review_events(studies, as_of=now, forecast_verifier=forecast_verifier)
    found, rejected = bound_forecasts(studies, as_of=now)
    byid = {r["forecast_id"]: r for r in reviews["reviews"]}
    cohorts = defaultdict(list)
    for identity, row in found.items():
        if identity not in byid:
            continue
        try:
            key = cohort_key(row["forecast"], byid[identity]["canonical_group_id"])
            cohorts[key].append(row["forecast"])
        except (ValueError, KeyError, TypeError, OSError, StopIteration) as error:
            rejected[str(error)[:120]] += 1
    disagreement, potential_pairs, pairs = [], [], []
    pair_rejections = Counter()
    for key, forecasts in sorted(cohorts.items()):
        model_ids = [f.get("model_id", f.get("model_version")) for f in forecasts]
        if len(set(model_ids)) != len(model_ids):
            rejected["duplicate_model_in_comparison_cohort"] += 1
            continue
        if len(forecasts) >= 2:
            probabilities = [f["probability"] for f in forecasts]
            lineages = sorted({p for f in forecasts for p in f.get("source_lineages", [])})
            disagreement.append({"cohort_id": key, "canonical_group_id": byid[forecasts[0]["id"]]["canonical_group_id"],
                                 "forecast_ids": sorted(f["id"] for f in forecasts), "model_ids": sorted(model_ids),
                                 "probability_range": max(probabilities) - min(probabilities),
                                 "declared_source_lineages": lineages, "independent_confirmation_count": None,
                                 "ensemble_probability": None, "ensemble_weights": None,
                                 "scope": "same prospective target/time/cutoff/native book; disagreement is not skill"})
        for challenger in forecasts:
            experiment = challenger.get("sii_experiment", {})
            if experiment.get("variant") != "with_sii":
                continue
            baseline = [f for f in forecasts if f.get("model_id") == experiment.get("baseline_model_id")
                        and f.get("model_sha256") == experiment.get("baseline_model_sha256")
                        and f.get("sii_experiment", {}).get("variant") == "without_sii"
                        and f.get("sii_experiment", {}).get("experiment_id") == experiment.get("experiment_id")]
            if len(baseline) != 1:
                pair_rejections["exact_same_cohort_sii_control_required"] += 1
                continue
            pair = {"cohort_id": key, "baseline": baseline[0], "challenger": challenger,
                    "experiment_id": experiment.get("experiment_id")}
            potential_pairs.append(pair)
            try:
                if not callable(sii_pair_verifier):
                    raise TypeError("independent_persistent_causal_sii_feature_replay_required")
                proof = sii_pair_verifier(pair, as_of=now)
                if not isinstance(proof, dict) or proof.get("verified") is not True:
                    raise TypeError("independent_persistent_causal_sii_feature_replay_required")
                pairs.append({"cohort_id": key, "experiment_id": pair["experiment_id"],
                              "baseline_forecast_id": baseline[0]["id"], "challenger_forecast_id": challenger["id"],
                              "feature_proof_sha256": digest(proof)})
            except (ValueError, KeyError, TypeError, OSError, StopIteration) as error:
                pair_rejections[str(error)[:120]] += 1
    accepted_ids = set(byid)
    validated_studies = [{**s, "forecasts": [f for f in s.get("forecasts", []) if f["id"] in accepted_ids]} for s in studies]
    performance = evaluate(validated_studies, outcomes, as_of=now, outcome_verifier=outcome_verifier)
    scores = {v["forecast_id"]: v for m in performance["leaderboard"] for v in m["descriptive_verified_scores"]}
    resolved_pairs = []
    for pair in pairs:
        left, right = scores.get(pair["baseline_forecast_id"]), scores.get(pair["challenger_forecast_id"])
        if left and right and _number(left.get("brier")) and _number(right.get("brier")):
            resolved_pairs.append({**pair, "baseline_brier": left["brier"], "challenger_brier": right["brier"],
                                   "incremental_brier_improvement": left["brier"] - right["brier"]})
    return {"schema_version": "phase25-competition-v1", "as_of": now.isoformat(),
            "event_review": reviews, "same_cohort_disagreements": disagreement,
            "performance": performance, "rejections": dict(rejected),
            "sii": {"candidate_exact_pairs": len(potential_pairs), "qualified_pairs": len(pairs),
                    "resolved_pairs": resolved_pairs, "pair_rejections": dict(pair_rejections),
                    "incremental_predictive_value": None, "after_cost_incremental_value": None,
                    "reason": "qualified causal features, independently verified paired outcomes and event-disjoint uncertainty required"},
            "ensemble": {"weights": None, "probabilities": None, "reason": "no qualified chronological event-disjoint calibration cohort"},
            "ranking_policy": "unresolved and exploratory models never receive profitability ranks", **AUTHORITY}
