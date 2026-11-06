"""Fair, event-grouped prospective scoring; no result or group self-attestation."""

from collections import Counter, defaultdict
from math import log, sqrt
from statistics import mean

from neraium_poly.research.phase12.contracts import EventForecast, VerifiedEventOutcome
from neraium_poly.research.phase12.ledger import content_sha256
from neraium_poly.research.phase13.models import log_loss


def _metrics(rows):
    if not rows:
        return {"count": 0, "brier": None, "log_loss": None, "market_brier": None,
                "market_log_loss": None, "ece": None, "reliability": [], "discrimination_auc": None}
    reliability = []
    for i in range(10):
        bucket = [r for r in rows if min(9, int(r["p"] * 10)) == i]
        if bucket:
            reliability.append({"lower": i / 10, "upper": (i + 1) / 10, "count": len(bucket),
                                "forecast_mean": mean(r["p"] for r in bucket),
                                "outcome_mean": mean(r["y"] for r in bucket)})
    positive, negative = [r["p"] for r in rows if r["y"]], [r["p"] for r in rows if not r["y"]]
    auc = None
    if positive and negative:
        negatives_before, concordant = 0, 0.0
        ranked = sorted((r["p"], r["y"]) for r in rows)
        position = 0
        while position < len(ranked):
            end = position + 1
            while end < len(ranked) and ranked[end][0] == ranked[position][0]:
                end += 1
            positives_tied = sum(y for _, y in ranked[position:end])
            negatives_tied = end - position - positives_tied
            concordant += positives_tied * (negatives_before + 0.5 * negatives_tied)
            negatives_before += negatives_tied
            position = end
        auc = concordant / (len(positive) * len(negative))
    return {
        "count": len(rows), "brier": mean((r["p"] - r["y"]) ** 2 for r in rows),
        "log_loss": mean(log_loss(r["p"], r["y"]) for r in rows),
        "market_brier": mean((r["market"] - r["y"]) ** 2 for r in rows),
        "market_log_loss": mean(log_loss(r["market"], r["y"]) for r in rows),
        "ece": sum(b["count"] * abs(b["forecast_mean"] - b["outcome_mean"]) for b in reliability) / len(rows),
        "reliability": reliability, "discrimination_auc": auc,
    }


def evaluate_forecasts(
    forecasts, outcomes, *, outcome_validator=None, independence_validator=None, min_events=20,
):
    """Evaluate the first prospectively recorded forecast per reviewed event/model.

    Validators must replay evidence at the integration boundary and return True.
    Forecast calibration skill, causal superiority, execution edge and paper P/L
    are deliberately separate. Grouping does not establish iid sampling by itself.
    """
    if type(min_events) is not int or not 20 <= min_events <= 100000:
        raise ValueError("at least 20 reviewed events required for headline research metrics")
    parsed = [EventForecast.model_validate(f.model_dump() if isinstance(f, EventForecast) else f)
              for f in forecasts]
    if len(parsed) > 20000:
        raise ValueError("bounded prospective evaluation required")
    verified, rejections = {}, Counter()
    for value in outcomes:
        o = VerifiedEventOutcome.model_validate(
            value.model_dump() if isinstance(value, VerifiedEventOutcome) else value
        )
        if (
            outcome_validator is None or outcome_validator(o) is not True
            or content_sha256(o.verification) != o.proof_sha256
        ):
            rejections["outcome_verification_not_accepted"] += 1
            continue
        key = (o.event_id, o.market_id, o.token_id)
        if key in verified and verified[key] != o:
            raise ValueError("conflicting final outcome requires manual correction review")
        verified[key] = o
    paired, used = defaultdict(list), set()
    pending = 0
    for f in sorted(parsed, key=lambda x: (x.timestamp, x.id)):
        if f.kind != "independent_model":
            continue
        identity = (f.model_version, f.model_sha256, f.feature_version)
        outcome = verified.get((f.event_id, f.market_id, f.token_id))
        if outcome is None:
            pending += 1
            continue
        if (
            f.timestamp >= outcome.settled_at or f.evidence_cutoff > f.timestamp
            or f.resolution_rules_sha256 != outcome.resolution_rules_sha256
        ):
            rejections["noncausal_or_mismatched_outcome"] += 1
            continue
        if (
            f.uncertainty.get("fractional_tie_contract_market_comparison_supported") is False
            or f.uncertainty.get("sports_prediction", {}).get("uncertainty", {}).get(
                "fractional_tie_contract_market_comparison_supported"
            ) is False
        ):
            rejections["unmatched_win_probability_and_fractional_payout_estimands"] += 1
            continue
        if (
            not f.independence_reviewed or independence_validator is None
            or independence_validator(f) is not True
        ):
            rejections["independent_event_group_not_reviewed"] += 1
            continue
        key = (identity, f.dependency_group)
        if key in used:
            rejections["repeated_forecast_or_correlated_event_group"] += 1
            continue
        used.add(key)
        paired[identity].append({"p": f.probability, "market": f.market_probability, "y": outcome.payout,
                                 "category": f.category, "horizon": f.horizon_seconds})
    reports = []
    for identity, rows in sorted(paired.items()):
        diagnostic = _metrics(rows)
        sufficient = len(rows) >= min_events
        headline = diagnostic if sufficient else _metrics([])
        delta = mean((r["p"] - r["y"]) ** 2 - (r["market"] - r["y"]) ** 2 for r in rows)
        # Loss difference is bounded in [-1,1]. This conservative bound requires
        # independent groups; it is not a guarantee under shared-driver dependence.
        radius = sqrt(2 * log(40) / len(rows)) if sufficient else None
        interval = [max(-1.0, delta - radius), min(1.0, delta + radius)] if sufficient else None
        categories = {category: _metrics([r for r in rows if r["category"] == category])
                      for category in sorted({r["category"] for r in rows})}
        horizons = {}
        for name, lo, hi in (("under_24h", 0, 86400), ("1_to_7_days", 86400, 604800),
                             ("over_7_days", 604800, float("inf"))):
            subset = [r for r in rows if r["horizon"] is not None and lo <= r["horizon"] < hi]
            if subset:
                horizons[name] = _metrics(subset)
        reports.append({
            "model_version": identity[0], "model_sha256": identity[1], "feature_version": identity[2],
            "independent_event_groups": len(rows), "metrics": headline,
            "descriptive_paired_scores": diagnostic, "category_descriptive_scores": categories,
            "horizon_descriptive_scores": horizons,
            "paired_brier_difference": delta if sufficient else None,
            "paired_brier_difference_95_bound": interval,
            "bound_assumption": "independent reviewed event groups; shared-driver dependence can invalidate bound",
            "comparison": "same forecast's recorded contemporaneous market probability, never a later quote",
            "status": "research_scores_only" if sufficient else "insufficient_independent_events",
            "superior_forecasting_evidence": bool(interval and interval[1] < 0),
            "executable_trading_advantage": None, "simulated_trading_performance": None,
        })
    return {
        "schema_version": "1.0", "models": reports, "pending_independent_forecasts": pending,
        "rejections": dict(rejections), "headline_minimum_independent_events": min_events,
        "first_forecast_selection": "earliest prospectively recorded forecast per model identity and reviewed group",
        "baseline_pairing": "exact original forecast.market_probability",
        "coverage": {"independent_records": sum(f.kind == "independent_model" for f in parsed),
                     "verified_paired_groups_by_model": {r["model_sha256"]: r["independent_event_groups"] for r in reports}},
        "certification_authority": False, "automatic_promotion": False,
        "limitations": ["Research sufficiency is not 100/100 strategy certification",
                        "Brier improvement alone does not establish trading profit",
                        "Outcome verification and event grouping require independent review"],
    }


def score_sports_prediction(prediction, result, *, market_expected_payout=None):
    """Descriptive ternary score, conditional on caller-verifying a final result.

    A price for a contract paying 0.5 on a tie is not a complete market-implied
    win/tie/loss distribution. Its expected-payout MSE is separately labelled.
    """
    from neraium_poly.research.phase13.contracts import SportsGame, SportsPrediction

    prediction = SportsPrediction.model_validate(
        prediction.model_dump() if isinstance(prediction, SportsPrediction) else prediction
    )
    result = SportsGame.model_validate(result.model_dump() if isinstance(result, SportsGame) else result)
    probabilities = prediction.uncertainty.get("outcome_probabilities")
    if (
        result.status != "final" or result.game_id != prediction.game_id
        or result.starts_at <= prediction.cutoff or result.result_observed_at <= prediction.cutoff
        or prediction.selected_team_id not in (result.home_id, result.away_id)
        or not isinstance(probabilities, dict) or set(probabilities) != {"win", "tie", "loss"}
        or any(not isinstance(p, (int, float)) or not 0 <= p <= 1 for p in probabilities.values())
        or abs(sum(probabilities.values()) - 1) > 1e-12
        or abs(probabilities["win"] - prediction.probability) > 1e-12
    ):
        raise ValueError("matching causal ternary prediction and final sports result required")
    if result.home_score == result.away_score:
        actual = "tie"
    else:
        winner = result.home_id if result.home_score > result.away_score else result.away_id
        actual = "win" if prediction.selected_team_id == winner else "loss"
    payout = {"win": 1.0, "tie": 0.5, "loss": 0.0}[actual]
    expected_payout = probabilities["win"] + 0.5 * probabilities["tie"]
    if market_expected_payout is not None and (
        not isinstance(market_expected_payout, (int, float)) or isinstance(market_expected_payout, bool)
        or not 0 <= market_expected_payout <= 1
    ):
        raise ValueError("valid contemporaneous market expected-payout baseline required")
    return {
        "actual": actual, "multiclass_brier": sum((p - int(k == actual)) ** 2 for k, p in probabilities.items()),
        "log_loss": -log(max(1e-12, probabilities[actual])),
        "unconditional_win_brier": (probabilities["win"] - int(actual == "win")) ** 2,
        "market_win_brier": None, "market_multiclass_brier": None,
        "market_probability_reason": "fractional-payout quote does not identify market win/tie/loss probabilities",
        "actual_fractional_payout": payout, "expected_payout_mse": (expected_payout - payout) ** 2,
        "market_expected_payout_mse": (market_expected_payout - payout) ** 2
        if market_expected_payout is not None else None,
        "expected_payout_mse_is_not_multiclass_forecast_skill": True,
        "profitability": None, "execution_adjusted_return": None,
    }


def evaluate_sports_forecasts(
    records, results, *, result_validator=None, independence_validator=None, min_events=20,
):
    """Score immutable ternary-journal records without making binary conversions.

    Primary scores require an independent grouping review. Repeated forecasts of
    the same real game cannot inflate independent sample counts. Unreviewed
    matched results may expose descriptive scores, never inferential claims.
    """
    from datetime import datetime

    from neraium_poly.contracts import OrderBookSnapshot
    from neraium_poly.research.phase13.contracts import SportsMapping, SportsPrediction

    if type(min_events) is not int or not 20 <= min_events <= 100000:
        raise ValueError("at least 20 reviewed events required for headline research metrics")
    if len(records) > 20000 or len(results) > 20000:
        raise ValueError("bounded sports evaluation required")
    by_id, rejections = {}, Counter()
    for result in results:
        if result_validator is None or result_validator(result) is not True:
            rejections["sports_and_exchange_result_verification_required"] += 1
            continue
        key = result["forecast_id"]
        if key in by_id and by_id[key] != result:
            raise ValueError("conflicting sports result evidence requires correction review")
        by_id[key] = result
    models, seen_events, descriptive = defaultdict(list), set(), []
    for record in sorted(records, key=lambda r: (r["timestamp"], r["id"])):
        result = by_id.get(record["id"])
        if result is None:
            continue
        prediction = SportsPrediction.model_validate(record["prediction"])
        mapping = SportsMapping.model_validate(record["mapping"])
        book = OrderBookSnapshot.model_validate(record["book"])
        timestamp = datetime.fromisoformat(record["timestamp"])
        if (
            timestamp.tzinfo is None or prediction.cutoff > timestamp
            or timestamp >= mapping.event_start or mapping.game_id != prediction.game_id
            or mapping.selected_team_id != prediction.selected_team_id
            or (book.market_id, book.token_id) != (mapping.market_id, mapping.token_id)
            or book.timestamp > timestamp or book.available_at > timestamp
            or (timestamp - book.timestamp).total_seconds() > 15
            or not book.bids or not book.asks or book.bids[0].price >= book.asks[0].price
        ):
            rejections["noncausal_or_mismatched_forecast_baseline"] += 1
            continue
        baseline = record["market_expected_payout_baseline"]
        if abs((book.bids[0].price + book.asks[0].price) / 2 - baseline) > 1e-12:
            rejections["original_book_midpoint_baseline_mismatch"] += 1
            continue
        try:
            scores = score_sports_prediction(prediction, result["sports_result"], market_expected_payout=baseline)
        except ValueError:
            rejections["matching_causal_sports_result_required"] += 1
            continue
        # A future fractional-settlement proof schema is needed for ties; current
        # exchange proofs are binary, so a tied sports result remains unresolved.
        exchange = VerifiedEventOutcome.model_validate(result["exchange_outcome"])
        expected_binary = 1 if scores["actual"] == "win" else 0
        if (
            scores["actual"] == "tie" or exchange.payout != expected_binary
            or (exchange.event_id, exchange.market_id, exchange.token_id)
            != (mapping.event_id, mapping.market_id, mapping.token_id)
            or exchange.resolution_rules_sha256 != mapping.rules_sha256
            or timestamp >= exchange.settled_at
        ):
            rejections["fractional_or_conflicting_exchange_settlement_unresolved"] += 1
            continue
        descriptive.append({"forecast_id": record["id"], "scores": scores,
                            "statistical_evidence_of_superiority": False})
        if (
            record.get("independence_reviewed") is not True or independence_validator is None
            or independence_validator(record) is not True
        ):
            rejections["sports_event_independence_not_reviewed"] += 1
            continue
        identity = (prediction.model_version, prediction.model_sha256, prediction.feature_version)
        event_key = (identity, mapping.league, mapping.game_id)
        group_key = (identity, record["dependency_group"])
        if event_key in seen_events or group_key in seen_events:
            rejections["repeated_or_correlated_sports_event"] += 1
            continue
        seen_events.update((event_key, group_key))
        models[identity].append(scores)
    reports = []
    for identity, rows in sorted(models.items()):
        enough = len(rows) >= min_events
        delta = mean(r["expected_payout_mse"] - r["market_expected_payout_mse"] for r in rows)
        radius = sqrt(2 * log(40) / len(rows)) if enough else None
        reports.append({
            "model_version": identity[0], "model_sha256": identity[1], "feature_version": identity[2],
            "independent_event_groups": len(rows), "multiclass_brier": mean(r["multiclass_brier"] for r in rows)
            if enough else None, "log_loss": mean(r["log_loss"] for r in rows) if enough else None,
            "market_multiclass_brier": None, "market_win_brier": None,
            "expected_payout_mse": mean(r["expected_payout_mse"] for r in rows) if enough else None,
            "market_expected_payout_mse": mean(r["market_expected_payout_mse"] for r in rows) if enough else None,
            "paired_expected_payout_mse_difference": delta if enough else None,
            "paired_expected_payout_mse_difference_95_bound": [max(-1, delta - radius), min(1, delta + radius)]
            if enough else None,
            "bound_assumption": "independent reviewed sports event groups; shared-driver dependence is not excluded",
            "forecast_skill_vs_market": None, "executable_trading_advantage": None, "profitability": None,
            "calibration_status": "insufficient_independent_events" if not enough else "research_evaluation_only",
        })
    return {
        "schema_version": "1.0", "models": reports, "descriptive_matched_forecasts": descriptive,
        "independent_forecasts": len(records), "matched_verified_forecasts": len(descriptive),
        "rejections": dict(rejections), "headline_minimum_independent_events": min_events,
        "market_baseline": "original same-record contemporaneous expected-payout quote, not unconditional win probability",
        "market_win_probability": None, "certification_authority": False, "automatic_promotion": False,
        "limitations": ["Canceled/postponed/disputed/fractional or conflicting results remain unresolved",
                        "Expected-payout MSE is distinct from win-probability skill and trading profitability",
                        "Repeated tokens/forecasts of the same sports game are not independent samples"],
    }
