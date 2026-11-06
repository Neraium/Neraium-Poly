"""Causal event-outcome baselines and research-only independent challengers.

A historical price acquired after resolution is not a historical decision input.
Current market prices alone never become independently estimated probabilities.
"""

import hashlib
import json
from collections import Counter, defaultdict
from datetime import datetime
from math import exp, isfinite, log, sqrt
from pathlib import Path
from statistics import mean

from neraium_poly.research.phase11.contracts import ExperimentSpec
from neraium_poly.research.phase12.contracts import CanonicalEvent, EventEvidence, VerifiedEventOutcome


def _parse(dataset):
    if isinstance(dataset, (str, Path)):
        from neraium_poly.research.phase12.dataset import load_dataset

        dataset = load_dataset(dataset)
    events = [
        x if isinstance(x, CanonicalEvent) else CanonicalEvent.model_validate(x) for x in dataset["events"]
    ]
    evidence = [
        x if isinstance(x, EventEvidence) else EventEvidence.model_validate(x) for x in dataset["evidence"]
    ]
    outcomes = [
        x if isinstance(x, VerifiedEventOutcome) else VerifiedEventOutcome.model_validate(x)
        for x in dataset["outcomes"]
    ]
    if len({(x.event_id, x.market_id) for x in events}) != len(events):
        raise ValueError("ambiguous canonical event identity")
    if len({x.id for x in evidence}) != len(evidence):
        raise ValueError("duplicate evidence identity")
    for x in evidence:
        digest = hashlib.sha256(
            json.dumps(x.payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        ).hexdigest()
        if digest != x.content_sha256:
            raise ValueError("event evidence payload integrity failed")
    for outcome in outcomes:
        proof = json.dumps(outcome.verification, sort_keys=True, separators=(",", ":"), allow_nan=False)
        if hashlib.sha256(proof.encode()).hexdigest() != outcome.proof_sha256:
            raise ValueError("outcome verification integrity failed")
    return dataset.get("manifest", {}), events, evidence, outcomes


def build_samples(dataset):
    manifest, events, evidence, outcomes = _parse(dataset)
    emap = {(x.event_id, x.market_id): x for x in events}
    omap = {}
    for x in outcomes:
        key = (x.event_id, x.market_id, x.token_id)
        if key in omap and omap[key] != x:
            raise ValueError("conflicting verified outcomes require correction review")
        omap[key] = x
    external = defaultdict(list)
    for x in evidence:
        if x.kind == "external_context":
            external[(x.event_id, x.market_id)].append(x)
    rejects = Counter()
    market_rows = []
    independent_rows = []
    for e in sorted(evidence, key=lambda x: (x.timestamp, x.available_at, x.id)):
        if e.kind != "market_price":
            continue
        event = emap.get((e.event_id, e.market_id))
        p = e.payload.get("probability")
        token = e.payload.get("token_id")
        try:
            decision = datetime.fromisoformat(e.payload.get("prediction_at", e.timestamp.isoformat()))
        except (ValueError, TypeError):
            rejects["invalid_decision_time"] += 1
            continue
        if decision.tzinfo is None or e.available_at > decision or e.timestamp > decision:
            rejects["market_observation_not_available_at_decision"] += 1
            continue
        if isinstance(p, bool) or not isinstance(p, (int, float)) or not isfinite(p) or not 0 <= p <= 1:
            rejects["invalid_market_probability"] += 1
            continue
        if event is None or token not in event.token_ids or event.available_at > decision:
            rejects["point_in_time_event_metadata_missing"] += 1
            continue
        if not event.resolution_rules or not event.resolution_source:
            rejects["resolution_rules_missing"] += 1
            continue
        rules_hash = hashlib.sha256(event.resolution_rules.encode()).hexdigest()
        outcome = omap.get((event.event_id, event.market_id, token))
        if outcome is None:
            rejects["verified_outcome_missing"] += 1
            continue
        if outcome.resolution_rules_sha256 != rules_hash:
            rejects["resolution_rules_outcome_mismatch"] += 1
            continue
        if outcome.settled_at <= decision:
            rejects["outcome_already_resolved_at_decision"] += 1
            continue
        if not event.provenance.get(
            "historical_rules_verified", event.provenance.get("rules_point_in_time_verified", False)
        ):
            rejects["point_in_time_rule_version_unverified"] += 1
            continue
        row = {
            "id": e.id,
            "event_id": event.event_id,
            "market_id": event.market_id,
            "token_id": token,
            "dependency_group": event.dependency_group,
            "category": event.category,
            "decision_at": decision,
            "label_available_at": outcome.available_at,
            "settled_at": outcome.settled_at,
            "horizon_seconds": (outcome.settled_at - decision).total_seconds(),
            "market_probability": float(p),
            "outcome": outcome.payout,
            "evidence_ids": [e.id, outcome.id],
            "features": None,
        }
        market_rows.append(row)
        if not event.independence_reviewed:
            rejects["event_independence_unreviewed"] += 1
            continue
        contexts = []
        for context in external[(event.event_id, event.market_id)]:
            f = context.payload.get("features")
            if (
                context.independent_of_market_price
                and context.available_at <= decision
                and context.timestamp <= decision
                and context.payload.get("feature_provenance_reviewed") is True
                and isinstance(f, dict)
                and not {str(k).casefold() for k in f}
                & {"outcome", "payout", "settled_at", "label", "market_probability", "final_outcome"}
                and f
                and all(
                    isinstance(v, (int, float)) and not isinstance(v, bool) and isfinite(v)
                    for v in f.values()
                )
            ):
                contexts.append(context)
        if not contexts:
            rejects["independent_predecision_numeric_context_missing"] += 1
            continue
        context = max(contexts, key=lambda x: (x.available_at, x.id))
        row = {
            **row,
            "features": dict(context.payload["features"]),
            "evidence_ids": row["evidence_ids"] + [context.id],
        }
        independent_rows.append(row)

    # First forecast per reviewed dependency group is fixed before observing labels.
    def unique(rows):
        result = []
        seen = set()
        for row in rows:
            key = row["dependency_group"]
            if key in seen:
                rejects["repeated_dependency_group_excluded"] += 1
                continue
            seen.add(key)
            result.append(row)
        return result

    return (
        manifest,
        unique(independent_rows),
        market_rows,
        {
            "canonical_events": len(events),
            "verified_token_outcomes": len(outcomes),
            "market_price_observations": sum(x.kind == "market_price" for x in evidence),
            "point_in_time_market_comparison_rows": len(market_rows),
            "independent_context_rows_before_group_dedup": len(independent_rows),
            "rejections": dict(rejects),
        },
    )


def chronological_split(rows):
    rows = sorted(rows, key=lambda x: (x["decision_at"], x["id"]))
    n = len(rows)
    a = int(0.6 * n)
    b = int(0.8 * n)
    if not a or b <= a or b >= n:
        return [], [], [], 0
    validation_at, heldout_at = rows[a]["decision_at"], rows[b]["decision_at"]
    train = [r for r in rows[:a] if r["label_available_at"] < validation_at]
    validation = [r for r in rows[a:b] if r["label_available_at"] < heldout_at]
    heldout = rows[b:]
    groups = [{r["dependency_group"] for r in s} for s in (train, validation, heldout)]
    if groups[0] & groups[1] or groups[0] & groups[2] or groups[1] & groups[2]:
        raise ValueError("dependency groups overlap chronological partitions")
    return train, validation, heldout, n - len(train) - len(validation) - len(heldout)


def probability_metrics(probabilities, outcomes):
    if len(probabilities) != len(outcomes):
        raise ValueError("probability/target length mismatch")
    if not outcomes:
        return {"count": 0, "brier": None, "log_loss": None, "ece": None, "auc": None, "reliability": []}
    if any(not isfinite(p) or not 0 <= p <= 1 for p in probabilities) or any(
        type(y) is not int or y not in (0, 1) for y in outcomes
    ):
        raise ValueError("finite probabilities and binary final outcomes required")
    bins = []
    ece = 0
    for i in range(10):
        pairs = [(p, y) for p, y in zip(probabilities, outcomes, strict=True) if min(9, int(p * 10)) == i]
        if pairs:
            p = mean(v[0] for v in pairs)
            y = mean(v[1] for v in pairs)
            bins.append({"bin": i, "count": len(pairs), "mean_probability": p, "observed_frequency": y})
            ece += len(pairs) / len(outcomes) * abs(p - y)
    positive = [p for p, y in zip(probabilities, outcomes, strict=True) if y == 1]
    negative = [p for p, y in zip(probabilities, outcomes, strict=True) if y == 0]
    auc = (
        (sum((p > q) + 0.5 * (p == q) for p in positive for q in negative) / (len(positive) * len(negative)))
        if positive and negative
        else None
    )
    return {
        "count": len(outcomes),
        "brier": mean((p - y) ** 2 for p, y in zip(probabilities, outcomes, strict=True)),
        "log_loss": -mean(
            y * log(max(1e-12, p)) + (1 - y) * log(max(1e-12, 1 - p))
            for p, y in zip(probabilities, outcomes, strict=True)
        ),
        "ece": ece,
        "auc": auc,
        "reliability": bins,
    }


def fit_models(train):
    if not train or any(r["features"] is None for r in train):
        raise ValueError("independent training context required")
    names = sorted(train[0]["features"])
    if any(sorted(r["features"]) != names for r in train):
        raise ValueError("feature schema mismatch")
    means = [mean(r["features"][k] for r in train) for k in names]
    scales = [
        max(1e-8, sqrt(mean((r["features"][k] - means[i]) ** 2 for r in train))) for i, k in enumerate(names)
    ]
    xs = [[1] + [(r["features"][k] - means[i]) / scales[i] for i, k in enumerate(names)] for r in train]
    weights = [0.0] * (len(names) + 1)
    for _ in range(200):
        gradient = [0.0] * len(weights)
        for x, r in zip(xs, train, strict=True):
            p = 1 / (1 + exp(-max(-30, min(30, sum(a * b for a, b in zip(weights, x, strict=True))))))
            for j, v in enumerate(x):
                gradient[j] += (p - r["outcome"]) * v / len(train)
        weights = [
            w - 0.1 * (g + (0.01 * w if j else 0))
            for j, (w, g) in enumerate(zip(weights, gradient, strict=True))
        ]
    successes = sum(r["outcome"] for r in train)
    return {
        "feature_names": names,
        "means": means,
        "scales": scales,
        "weights": weights,
        "frequency": successes / len(train),
        "bayesian_frequency": (successes + 1) / (len(train) + 2),
        "training_count": len(train),
        "model_version": "event-independent-logistic-l2-v1",
    }


def predict(model, row):
    if sorted(row["features"]) != model["feature_names"]:
        raise ValueError("feature schema mismatch")
    x = [1] + [
        (row["features"][k] - model["means"][i]) / model["scales"][i]
        for i, k in enumerate(model["feature_names"])
    ]
    logistic = 1 / (1 + exp(-max(-30, min(30, sum(a * b for a, b in zip(model["weights"], x, strict=True))))))
    temperature = model.get("validation_temperature", 1)
    calibrated = 1 / (
        1 + exp(-max(-30, min(30, log(max(1e-12, logistic) / max(1e-12, 1 - logistic)) / temperature)))
    )
    return {
        "calibrated_independent_logistic": calibrated,
        "market_implied": row["market_probability"],
        "historical_frequency": model["frequency"],
        "bayesian_frequency": model["bayesian_frequency"],
        "independent_logistic": logistic,
    }


def _score(model, rows):
    predictions = [predict(model, r) for r in rows]
    return {
        name: probability_metrics([p[name] for p in predictions], [r["outcome"] for r in rows])
        for name in (
            "market_implied",
            "historical_frequency",
            "bayesian_frequency",
            "independent_logistic",
            "calibrated_independent_logistic",
        )
    }


def run_event_models(dataset):
    manifest, rows, market_rows, funnel = build_samples(dataset)
    train, validation, heldout, purged = chronological_split(rows)
    digest = (
        manifest.get("dataset_sha256")
        or hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()
    )
    interval = lambda part: (
        (part[0]["decision_at"].isoformat(), part[-1]["decision_at"].isoformat()) if part else None
    )
    spec = ExperimentSpec(
        experiment_id="phase12-terminal-outcome-v1",
        hypothesis="Independent predecision external context may improve terminal-event probabilities over contemporaneous market baselines",
        dataset_sha256=digest,
        model_version="event-independent-logistic-l2-v1",
        feature_definitions={
            "external": "Reviewed numeric independent context available before decision; train-only scaling"
        },
        target_definitions={
            "terminal": "Verified binary final token payout; actual settlement time after original forecast"
        },
        split_policy="First forecast per reviewed dependency group; chronological60/20/20; labels matured before next split; no group overlap",
        training_interval=interval(train),
        validation_interval=interval(validation),
        heldout_interval=interval(heldout),
        grouping={
            "unit": "reviewed dependency group",
            "training": len(train),
            "validation": len(validation),
            "heldout": len(heldout),
            "purged": purged,
        },
        transaction_cost_assumptions={
            "executable_returns": None,
            "reason": "Independent forecasting skill and executable depth/fees are separate requirements",
        },
        failure_conditions=(
            "Collected-after-decision data",
            "Unverified outcomes or rule versions",
            "Unreviewed dependence",
            "Missing independent features",
            "Insufficient chronological labels",
        ),
        limitations=(
            "Market-only forecasts are baselines, not independent models",
            "No strategy certification or promotion",
            "No fabricated historical books or profits",
        ),
    )
    report = {
        "spec": spec.model_dump(mode="json"),
        "funnel": funnel,
        "split_counts": {
            "train": len(train),
            "validation": len(validation),
            "heldout": len(heldout),
            "purged": purged,
        },
        "certification_minimum": {"training": 100, "heldout": 100},
        "terminal_probability": {"brier": None, "log_loss": None, "calibration": None},
        "results": None,
        "confidence_interval": None,
        "confidence_interval_reason": "Insufficient independent point-in-time terminal labels",
        "cost_adjusted_performance": None,
        "independent_forecasting_skill_established": False,
        "certification_authority": False,
        "automatic_promotion": False,
        "status": "insufficient_evidence",
        "deferred": [
            "Gradient boosting and ensembles require independent held-out improvement and adequate data"
        ],
        "market_comparison_sample_count": len(market_rows),
        "feature_version": "independent-numeric-context-v1",
    }
    if min(len(train), len(validation), len(heldout)) < 5:
        return report
    model = fit_models(train)
    choices = []
    for temperature in (0.5, 1, 2):
        candidate = {**model, "validation_temperature": temperature}
        score = _score(candidate, validation)["calibrated_independent_logistic"]["log_loss"]
        choices.append((score, abs(temperature - 1), temperature))
    model["validation_temperature"] = min(choices)[2]
    results = {
        name: _score(model, part)
        for name, part in [("train", train), ("validation", validation), ("heldout", heldout)]
    }
    selected = min(
        (
            "historical_frequency",
            "bayesian_frequency",
            "independent_logistic",
            "calibrated_independent_logistic",
        ),
        key=lambda k: results["validation"][k]["brier"],
    )
    differences = [
        (predict(model, r)[selected] - r["outcome"]) ** 2 - (r["market_probability"] - r["outcome"]) ** 2
        for r in heldout
    ]
    # Hoeffding bounded-loss difference interval: independent reviewed groups only.
    radius = sqrt(2 * log(40) / len(differences))
    ci = [max(-1, mean(differences) - radius), min(1, mean(differences) + radius)]
    category = {}
    horizon = {}
    for cat in sorted({r["category"] for r in heldout}):
        category[cat] = _score(model, [r for r in heldout if r["category"] == cat])
    for name, predicate in [("under_24h", lambda h: h < 86400), ("24h_or_more", lambda h: h >= 86400)]:
        horizon[name] = _score(model, [r for r in heldout if predicate(r["horizon_seconds"])])
    return {
        **report,
        "status": "exploratory_evaluated",
        "results": results,
        "validation_selected_model": selected,
        "training_parameters": model,
        "confidence_interval": ci,
        "confidence_interval_reason": "Distribution-free95% Hoeffding interval of selected-minus-market Brier loss, conditional on reviewed independent groups",
        "by_category": category,
        "by_horizon": horizon,
        "independent_forecasting_skill_established": False,
        "terminal_probability": {
            "brier": results["heldout"][selected]["brier"],
            "log_loss": results["heldout"][selected]["log_loss"],
            "calibration": results["heldout"][selected]["ece"],
        },
    }
