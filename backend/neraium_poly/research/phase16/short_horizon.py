"""Causal depth-mark challenger and purged temporal replay, without deployment authority.

Targets are monetary bid quotes for fixed shares. Reconstructed historical
forecasts are exploratory research, not immutable prospective forecasts, terminal
probabilities, actual orders, or event-independent strategy certification.
"""

import hashlib
import json
from bisect import bisect_left
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from math import isfinite
from statistics import mean, median

from neraium_poly.research.phase16.execution import PUBLIC_BOOK_SOURCES, _fee

MODEL_VERSION = "phase16-causal-depth-bid-median-v1"
FEATURE_VERSION = "fixed-shares-top3-quarter-depth-v1"


def _at(value):
    value = datetime.fromisoformat(value) if isinstance(value, str) else value
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError("aware research time required")
    return value.astimezone(UTC)


def _number(value):
    return not isinstance(value, bool) and isinstance(value, (int, float)) and isfinite(value)


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def replay_forecasts(points, *, cutoff, verify_point=None, horizon_seconds=60,
                     max_label_delay_seconds=30, min_prior=40, min_matured_errors=20):
    """Replay independently source-verified points under an unchanged causal policy.

    ``verify_point(point) is True`` must replay raw quote/context/fee provenance;
    supplied source URLs or self-asserted booleans are not that independent replay.
    Labels use first source observation at/after decision+horizon within tolerance.
    Training residuals must already have matured at each forecast's own cutoff.
    A 90-second purge separates the initial60% time interval from held-out marks.
    """
    cutoff = _at(cutoff)
    if (type(horizon_seconds) is not int or not 60 <= horizon_seconds <= 300
        or type(max_label_delay_seconds) is not int or not 0 <= max_label_delay_seconds <= 30
        or type(min_prior) is not int or not 40 <= min_prior <= 240
        or type(min_matured_errors) is not int or not 20 <= min_matured_errors <= 120
        or not isinstance(points, (list, tuple)) or len(points) > 20000):
        raise ValueError("bounded conservative replay policy required")
    dataset_sha = _digest(points)
    rejected, accepted, identities, ambiguous = Counter(), [], {}, set()
    for raw in points:
        try:
            if not callable(verify_point) or verify_point(raw) is not True:
                raise ValueError("raw_source_replay_required")
            at = _at(raw.get("source_at", raw.get("timestamp")))
            available, observed = _at(raw["available_at"]), _at(raw["observed_at"])
            if not at <= available <= observed <= cutoff or not 0 <= (observed-at).total_seconds() <= 15:
                raise ValueError("future_stale_or_unavailable_point")
            if raw.get("source") not in PUBLIC_BOOK_SOURCES:
                raise ValueError("unsupported_quote_source")
            for key in ("market_id", "token_id", "event_id", "book_id"):
                if not isinstance(raw.get(key), str) or not raw[key]:
                    raise ValueError("missing_market_parent_or_quote_identity")
            rules = raw.get("rules_sha256")
            if not isinstance(rules, str) or len(rules) != 64 or any(c not in "0123456789abcdef" for c in rules):
                raise ValueError("missing_contract_rule_identity")
            if raw.get("depth_scope") != "top3_observed" or raw.get("quantity") != 5.0:
                raise ValueError("incompatible_fixed_share_depth_semantics")
            bid, ask, bv, av = (raw.get(k) for k in ("bid", "ask", "bid_vwap", "ask_vwap"))
            if not all(_number(v) for v in (bid, ask, bv, av)) or not 0 < bv <= bid < ask <= av < 1:
                raise ValueError("insufficient_or_invalid_fixed_share_depth")
            identity = (raw["token_id"], raw["book_id"])
            fingerprint = _digest({k: raw.get(k) for k in ("source_at", "timestamp", "available_at", "bid", "ask",
                                  "bid_vwap", "ask_vwap", "market_id", "event_id", "rules_sha256", "quantity")})
            if identity in identities:
                if identities[identity] != fingerprint:
                    ambiguous.add(identity)
                raise ValueError("duplicate_quote_identity" if identities[identity] == fingerprint else "changed_quote_identity")
            identities[identity] = fingerprint
            accepted.append({**raw, "_source": at, "_available": available, "_observed": observed,
                             "_point_sha256": _digest(raw)})
        except (KeyError, TypeError, ValueError, OverflowError) as error:
            reason = str(error) if str(error) in {
                "raw_source_replay_required", "future_stale_or_unavailable_point", "unsupported_quote_source",
                "missing_market_parent_or_quote_identity", "missing_contract_rule_identity",
                "incompatible_fixed_share_depth_semantics", "insufficient_or_invalid_fixed_share_depth",
                "duplicate_quote_identity", "changed_quote_identity"} else "invalid_or_unverifiable_point"
            rejected[reason] += 1
        except Exception:  # noqa: BLE001 - an external verifier failure cannot become evidence
            rejected["raw_source_verifier_failed"] += 1
    if ambiguous:
        rejected["ambiguous_original_quote_quarantined"] += sum((p["token_id"],p["book_id"]) in ambiguous for p in accepted)
        accepted = [p for p in accepted if (p["token_id"],p["book_id"]) not in ambiguous]
    accepted.sort(key=lambda p: (p["_observed"], p["token_id"], p["book_id"]))
    report = {"schema_version": "phase16-depth-mark-replay-v1", "model_version": MODEL_VERSION,
              "feature_version": FEATURE_VERSION, "dataset_sha256": dataset_sha,
              "cutoff": cutoff.isoformat(), "input_points": len(points), "accepted_points": len(accepted),
              "rejected_points": dict(rejected), "records": [], "record_limit": 2000,
              "training_mark_examples": 0, "heldout_mark_examples": 0,
              "training_parent_groups": 0, "heldout_parent_groups": 0,
              "independent_training_events": 0, "independent_heldout_events": 0,
              "certification_eligible": False, "trading_authority": False,
              "calibration_brier": None, "calibration_log_loss": None,
              "paired_mae_improvement_95_interval": None,
              "model_mae": None, "unchanged_bid_baseline_mae": None,
              "model_mean_error": None, "cost_adjusted_quote_roundtrip_mean": None,
              "semantics": "USD_per_fixed_share_bid_mark_not_event_probability",
              "limitations": ["reconstructed exploratory replay, not a prospective forecast commitment",
                              "same-parent repeated quotes are dependent; temporal holdout is not event-independent certification",
                              "observed exit depth is a mark, not an actual future fill or profit",
                              "insufficient independent event groups for a superiority confidence interval"]}
    policy = {"horizon_seconds": horizon_seconds, "max_label_delay_seconds": max_label_delay_seconds,
              "min_prior": min_prior, "min_matured_errors": min_matured_errors,
              "training_fraction": .6, "purge_seconds": horizon_seconds+max_label_delay_seconds,
              "feature_window": 20, "max_error_window": 60, "envelope_floor": .01,
              "uncertainty_width_ceiling": .35, "minimum_net_edge": .03,
              "roundtrip_slippage_per_share": .02, "quantity": 5.0,
              "calibration_policy": "frozen_training_residuals_for_heldout"}
    report["policy"], report["policy_sha256"] = policy, _digest(policy)
    if len(accepted) < 2:
        report["status"] = "insufficient_evidence"
        return report
    split_at = accepted[int((len(accepted)-1)*.6)]["_observed"]
    heldout_start = split_at + timedelta(seconds=policy["purge_seconds"])
    report.update(training_interval={"start": accepted[0]["_observed"].isoformat(), "end": split_at.isoformat()},
                  heldout_interval={"start": heldout_start.isoformat(), "end": cutoff.isoformat()})
    cohorts = defaultdict(list)
    for point in accepted:
        cohorts[(point["token_id"], point["rules_sha256"])].append(point)
    predictions, train_groups, heldout_groups = [], set(), set()
    decision_rejections = Counter()
    for rows in cohorts.values():
        rows.sort(key=lambda p: (p["_source"], p["_observed"], p["book_id"]))
        times = [p["_source"].timestamp() for p in rows]
        residuals, segment_start = [], 0
        for i, point in enumerate(rows):
            if i and (point["_source"]-rows[i-1]["_source"]).total_seconds() > 120:
                residuals, segment_start = [], i
            decision = point["_observed"]
            prior = [p for p in rows[segment_start:i] if p["_available"] <= decision and p["_observed"] <= decision]
            if len(prior) < 20:
                continue
            if (decision-prior[-1]["_observed"]).total_seconds() > 120:
                decision_rejections["causal_history_gap"] += 1
                continue
            target = decision + timedelta(seconds=horizon_seconds)
            j = bisect_left(times, target.timestamp(), lo=i+1)
            label = rows[j] if j < len(rows) else None
            label_eligible = (label is not None and label["_source"] <= target+timedelta(seconds=max_label_delay_seconds)
                              and label["_available"] <= cutoff and label["_observed"] <= cutoff)
            trailing = median(p["bid_vwap"] for p in prior[-20:])
            # Every historical residual is a past forecast of a matured target.
            matured = [p for p in residuals if p["label_available_at"] <= decision
                       and p["label_observed_at"] <= decision
                       and (decision < heldout_start or (p["label_available_at"] <= split_at
                            and p["label_observed_at"] <= split_at))]
            if len(prior) >= min_prior and len(matured) >= min_matured_errors and label_eligible:
                errors = [p["error"] for p in matured[-60:]]
                bias = median(errors)
                centered = sorted(abs(value-bias) for value in errors)
                envelope = max(.01, centered[min(len(centered)-1, int(.9*len(centered)))])
                forecast = min(1., max(0., trailing+bias))
                lower, upper = max(0., forecast-envelope), min(1., forecast+envelope)
                is_train = label["_available"] <= split_at and label["_observed"] <= split_at
                is_heldout = decision >= heldout_start
                if is_train:
                    train_groups.add(point["event_id"])
                    report["training_mark_examples"] += 1
                if is_heldout:
                    heldout_groups.add(point["event_id"])
                    entry_fee, _ = _fee(point.get("fee_observation"), point["token_id"], decision)
                    exit_fee, _ = _fee(label.get("fee_observation"), label["token_id"], label["_observed"])
                    roundtrip = (label["bid_vwap"]*(1-exit_fee)-point["ask_vwap"]*(1+entry_fee)-.02
                                 if entry_fee is not None and exit_fee is not None else None)
                    projected = (lower*(1-entry_fee)-point["ask_vwap"]*(1+entry_fee)-.02
                                 if entry_fee is not None else None)
                    predictions.append({"decision_at": decision.isoformat(), "evidence_cutoff": decision.isoformat(),
                        "event_id": point["event_id"], "market_id": point["market_id"], "token_id": point["token_id"],
                        "book_id": point["book_id"], "label_book_id": label["book_id"],
                        "source_at": point["_source"].isoformat(), "available_at": point["_available"].isoformat(),
                        "target_at": target.isoformat(), "label_source_at": label["_source"].isoformat(),
                        "label_available_at": label["_available"].isoformat(),
                        "point_sha256": point["_point_sha256"], "label_sha256": label["_point_sha256"],
                        "feature_ids": [p["book_id"] for p in prior[-20:]],
                        "matured_error_count": len(errors), "max_training_label_available_at": max(p["label_available_at"] for p in matured[-60:]).isoformat(),
                        "forecast_bid_mark": forecast, "lower_bid_mark": lower, "upper_bid_mark": upper,
                        "uncertainty_calibration": "unvalidated empirical mark residual envelope",
                        "actual_bid_mark": label["bid_vwap"], "unchanged_bid_baseline": point["bid_vwap"],
                        "model_error": forecast-label["bid_vwap"],
                        "baseline_error": point["bid_vwap"]-label["bid_vwap"],
                        "estimated_net_mark_edge_per_share": projected,
                        "positive_projection_before_other_qualification": projected is not None and projected >= .03 and upper-lower <= .35,
                        "observed_quote_roundtrip_after_modeled_costs": roundtrip,
                        "execution_certified": False, "prospectively_recorded_forecast": False})
            elif len(prior) >= min_prior:
                decision_rejections["unmatured_target" if not label_eligible else "insufficient_matured_errors"] += 1
            if label_eligible:
                residuals.append({"error": label["bid_vwap"]-trailing,
                                  "label_available_at": label["_available"], "label_observed_at": label["_observed"]})
    predictions.sort(key=lambda p: (p["decision_at"], p["token_id"], p["book_id"]))
    report.update(heldout_mark_examples=len(predictions), training_parent_groups=len(train_groups),
                  heldout_parent_groups=len(heldout_groups),
                  overlapping_parent_groups=len(train_groups & heldout_groups),
                  decision_rejections=dict(decision_rejections), records=predictions[:2000],
                  records_truncated=len(predictions)>2000)
    if predictions:
        costs = [p["observed_quote_roundtrip_after_modeled_costs"] for p in predictions
                 if p["observed_quote_roundtrip_after_modeled_costs"] is not None]
        selected = [p["observed_quote_roundtrip_after_modeled_costs"] for p in predictions
                    if p["positive_projection_before_other_qualification"] and p["observed_quote_roundtrip_after_modeled_costs"] is not None]
        report.update(positive_projected_mark_examples=sum(p["positive_projection_before_other_qualification"] for p in predictions),
                      positive_projected_cost_supported_examples=len(selected),
                      selected_observed_quote_roundtrip_mean=mean(selected) if selected else None,
                      status="exploratory_temporal_mark_validation", model_mae=mean(abs(p["model_error"]) for p in predictions),
                      unchanged_bid_baseline_mae=mean(abs(p["baseline_error"]) for p in predictions),
                      model_mean_error=mean(p["model_error"] for p in predictions),
                      cost_adjusted_quote_roundtrip_mean=mean(costs) if costs else None,
                      cost_supported_mark_examples=len(costs))
    else:
        report["status"] = "insufficient_evidence"
    return report
