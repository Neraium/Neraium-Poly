"""Purged chronological challenger research; no terminal-probability authority."""

from bisect import bisect_left
from collections import defaultdict, deque
from datetime import timedelta
from math import exp, isfinite, log, sqrt
from statistics import mean

from neraium_poly.data import assess_book
from neraium_poly.experimental.strategies import ExperimentalStrategyEngine
from neraium_poly.research.phase11.contracts import ExperimentSpec, ResearchObservation

HORIZON = 60
FEATURES = (
    "spread",
    "top_five_imbalance",
    "last_bid_change",
    "last_five_bid_change",
    "log_depth",
    "bid_level",
)


def _observations(rows):
    parsed = [
        r if isinstance(r, ResearchObservation) else ResearchObservation.model_validate(r) for r in rows
    ]
    parsed.sort(key=lambda r: (r.book.available_at, r.book.timestamp, r.book.id))
    ids = {}
    for row in parsed:
        if row.book.id in ids and ids[row.book.id] != row:
            raise ValueError("conflicting research observation identity")
        ids[row.book.id] = row
    return list(ids.values())


def supervised_samples(observations, *, horizon=HORIZON):
    """Features use only receipt-time past; labels are separately future-available.

    The binary target is a future BID RISE. It is never a settlement outcome.
    Repeated timestamps do not become extra observed labels or new features.
    """
    rows = _observations(observations)
    by_token = defaultdict(list)
    for row in rows:
        b = row.book
        if assess_book(b, b.available_at, max_spread=0.05).healthy:
            by_token[b.token_id].append(row)
    samples, skipped = [], defaultdict(int)
    for token_rows in by_token.values():
        times = [r.book.available_at for r in token_rows]
        history = deque(maxlen=6)
        last_source = None
        operational = ExperimentalStrategyEngine(enabled=("short_horizon",))
        for i, row in enumerate(token_rows):
            b = row.book
            if last_source is not None and b.timestamp <= last_source:
                skipped["reused_or_out_of_order_source"] += 1
                continue
            if history and (b.available_at - history[-1].book.available_at).total_seconds() > 120:
                history.clear()
            last_source = b.timestamp
            operational._remember(b.token_id, b)
            horizon_reference, _ = operational._horizon(b.token_id, b.available_at)
            target = b.available_at + timedelta(seconds=horizon)
            j = bisect_left(times, target, lo=i + 1)
            while j < len(token_rows) and token_rows[j].book.available_at <= target + timedelta(seconds=30):
                if token_rows[j].book.timestamp >= target:
                    break
                j += 1
            if j >= len(token_rows) or token_rows[j].book.available_at > target + timedelta(seconds=30):
                skipped["future_label_missing_or_not_source_matured"] += 1
                history.append(row)
                continue
            if len(history) < 5:
                skipped["causal_warmup"] += 1
                history.append(row)
                continue
            label = token_rows[j]
            bid, ask = b.bids[0].price, b.asks[0].price
            bd = sum(p.size for p in b.bids[:5])
            ad = sum(p.size for p in b.asks[:5])
            features = [
                ask - bid,
                (bd - ad) / (bd + ad),
                bid - history[-1].book.bids[0].price,
                bid - history[0].book.bids[0].price,
                log(1 + bd + ad),
                bid,
            ]
            future_bid = label.book.bids[0].price
            samples.append(
                {
                    "id": b.id,
                    "label_id": label.book.id,
                    "token_id": b.token_id,
                    "market_id": b.market_id,
                    "event_id": row.market.event_id if row.market else None,
                    "decision_at": b.available_at,
                    "source_at": b.timestamp,
                    "label_available_at": label.book.available_at,
                    "label_source_at": label.book.timestamp,
                    "features": features,
                    "bid": bid,
                    "ask": ask,
                    "future_bid": future_bid,
                    "target_change": future_bid - bid,
                    "target_bid_rise": int(future_bid > bid + 1e-12),
                    "fee_rate": row.fee.get("fee_rate") if row.fee else None,
                    "operational_forecast_change": horizon_reference["forecast"] - bid
                    if horizon_reference
                    else None,
                }
            )
            history.append(row)
    samples.sort(key=lambda r: (r["decision_at"], r["id"]))
    return samples, dict(skipped)


def chronological_split(samples):
    """60/20/20 unique decision times; purge labels at train/validation ends."""
    times = sorted({r["decision_at"] for r in samples})
    if len(times) < 10:
        return {"train": [], "validation": [], "heldout": [], "purged": len(samples), "boundaries": []}
    first, second = times[int(len(times) * 0.6)], times[int(len(times) * 0.8)]
    result = {
        "train": [],
        "validation": [],
        "heldout": [],
        "purged": 0,
        "boundaries": [first.isoformat(), second.isoformat()],
    }
    for row in samples:
        at, label = row["decision_at"], row["label_available_at"]
        if at < first:
            if label < first:
                result["train"].append(row)
            else:
                result["purged"] += 1
        elif at < second:
            if label < second:
                result["validation"].append(row)
            else:
                result["purged"] += 1
        else:
            result["heldout"].append(row)
    return result


def _scale(train):
    centers = [mean(r["features"][j] for r in train) for j in range(len(FEATURES))]
    scales = [
        max(1e-8, sqrt(mean((r["features"][j] - centers[j]) ** 2 for r in train)))
        for j in range(len(FEATURES))
    ]
    return centers, scales


def _design(rows, centers, scales):
    return [
        [1.0, *((v - c) / s for v, c, s in zip(r["features"], centers, scales, strict=True))] for r in rows
    ]


def _dot(a, b):
    return sum(x * y for x, y in zip(a, b, strict=True))


def _sigmoid(value):
    return 1 / (1 + exp(-max(-35, min(35, value))))


def _solve(matrix, target):
    a = [list(row) + [v] for row, v in zip(matrix, target, strict=True)]
    n = len(a)
    for i in range(n):
        pivot = max(range(i, n), key=lambda j: abs(a[j][i]))
        if abs(a[pivot][i]) < 1e-12:
            raise ValueError("singular research design")
        a[i], a[pivot] = a[pivot], a[i]
        divisor = a[i][i]
        a[i] = [v / divisor for v in a[i]]
        for j in range(n):
            if j != i:
                factor = a[j][i]
                a[j] = [x - factor * y for x, y in zip(a[j], a[i], strict=True)]
    return [r[-1] for r in a]


def fit_models(train):
    """All scaling and fit parameters depend on training rows only."""
    if not train:
        raise ValueError("training observations required")
    centers, scales = _scale(train)
    x = _design(train, centers, scales)
    n, p = len(x), len(x[0])
    a = [
        [sum(row[i] * row[j] for row in x) / n + (0.1 if i == j and i else 0) for j in range(p)]
        for i in range(p)
    ]
    y = [sum(row[j] * r["target_change"] for row, r in zip(x, train, strict=True)) / n for j in range(p)]
    ridge = _solve(a, y)
    # Fixed training-only optimization schedule and regularization, no test tuning.
    rises = sum(r["target_bid_rise"] for r in train)
    prior = (rises + 1) / (n + 2)
    weights = [log(prior / (1 - prior)), *([0.0] * (p - 1))]
    for _ in range(60):
        gradient = [0.0] * p
        for row, sample in zip(x, train, strict=True):
            error = _sigmoid(_dot(row, weights)) - sample["target_bid_rise"]
            for j in range(p):
                gradient[j] += row[j] * error / n
        weights = [
            w - 0.15 * (g + (0.1 * w if j else 0))
            for j, (w, g) in enumerate(zip(weights, gradient, strict=True))
        ]
    rises = sum(r["target_bid_rise"] for r in train)
    return {
        "centers": centers,
        "scales": scales,
        "ridge": ridge,
        "logistic": weights,
        "frequency": rises / n,
        "bayesian_frequency": (rises + 1) / (n + 2),
        "mean_change": mean(r["target_change"] for r in train),
        "training_count": n,
    }


def predict(model, rows):
    x = _design(rows, model["centers"], model["scales"])
    return {
        "unchanged_bid": [0.0] * len(rows),
        "midpoint": [(r["ask"] - r["bid"]) / 2 for r in rows],
        "training_mean_change": [max(-r["bid"], min(1 - r["bid"], model["mean_change"])) for r in rows],
        "ridge": [
            max(-r["bid"], min(1 - r["bid"], _dot(v, model["ridge"]))) for r, v in zip(rows, x, strict=True)
        ],
        "logistic_bid_rise": [_sigmoid(_dot(v, model["logistic"])) for v in x],
        "historical_frequency_bid_rise": [model["frequency"]] * len(rows),
        "bayesian_frequency_bid_rise": [model["bayesian_frequency"]] * len(rows),
    }


def probability_metrics(probabilities, labels):
    if len(probabilities) != len(labels) or not labels:
        raise ValueError("paired nonempty probabilities and binary labels required")
    if any(not isfinite(p) or not 0 <= p <= 1 for p in probabilities) or any(y not in (0, 1) for y in labels):
        raise ValueError("invalid probability evaluation")
    pairs = list(zip(probabilities, labels, strict=True))
    log_pairs = [(max(1e-8, min(1 - 1e-8, p)), y) for p, y in pairs]
    bins = []
    for i in range(10):
        selected = [(p, y) for p, y in pairs if min(9, int(p * 10)) == i]
        if selected:
            bins.append(
                {
                    "bin": i,
                    "count": len(selected),
                    "mean_probability": mean(p for p, _ in selected),
                    "observed_rate": mean(y for _, y in selected),
                }
            )
    return {
        "brier": mean((p - y) ** 2 for p, y in pairs),
        "log_loss": -mean(y * log(p) + (1 - y) * log(1 - p) for p, y in log_pairs),
        "ece": sum(r["count"] * abs(r["mean_probability"] - r["observed_rate"]) for r in bins) / len(pairs),
        "reliability_bins": bins,
        "target": "60_second_observed_bid_rise_not_settlement",
        "calibration_status": "exploratory_correlated_labels_not_independently_certified",
    }


def _metrics(model, rows, temperature):
    predictions = predict(model, rows)
    labels = [r["target_bid_rise"] for r in rows]
    marks = {
        name: {"mae": mean(abs(r["target_change"] - p) for r, p in zip(rows, values, strict=True))}
        for name, values in predictions.items()
        if not name.endswith("bid_rise")
    }
    direction = {
        name: probability_metrics(values, labels)
        for name, values in predictions.items()
        if name.endswith("bid_rise")
    }
    raw = predictions["logistic_bid_rise"]
    calibrated = [_sigmoid(log(max(1e-8, p) / max(1e-8, 1 - p)) / temperature) for p in raw]
    direction["validation_temperature_logistic_bid_rise"] = probability_metrics(calibrated, labels)
    return {"count": len(rows), "horizon_mark": marks, "directional_probability": direction}


def run_models(observations, dataset_manifest):
    samples, skipped = supervised_samples(observations)
    split = chronological_split(samples)
    train, validation, heldout = (split[k] for k in ("train", "validation", "heldout"))
    event_sets = {
        k: {r["event_id"] for r in split[k] if r["event_id"]} for k in ("train", "validation", "heldout")
    }
    intervals = {
        k: (split[k][0]["decision_at"].isoformat(), split[k][-1]["decision_at"].isoformat())
        if split[k]
        else None
        for k in ("train", "validation", "heldout")
    }
    spec = ExperimentSpec(
        experiment_id="phase11-chronological-challengers-v1",
        hypothesis="Causal book imbalance and lagged bids improve future bid marks or bid-rise probabilities over simple baselines",
        dataset_sha256=dataset_manifest["dataset_sha256"],
        model_version="standard-library-ridge-logistic-v1",
        feature_definitions={
            k: "Current book or receipt-time past only; scaling fitted on training only" for k in FEATURES
        },
        target_definitions={
            "mark": "First actually observed bid source+receipt at least60s after decision, receipt within90s",
            "direction": "future_bid > current_bid; not final resolution outcome",
        },
        split_policy="60/20/20 unique global decision times; labels purged across train/validation boundaries",
        training_interval=intervals["train"],
        validation_interval=intervals["validation"],
        heldout_interval=intervals["heldout"],
        grouping={
            "reported_events": {k: len(v) for k, v in event_sets.items()},
            "train_heldout_event_overlap": len(event_sets["train"] & event_sets["heldout"]),
            "reviewed_independent_events": 0,
        },
        transaction_cost_assumptions={
            "forecast_scores_are_not_execution_returns": True,
            "executable_returns": None,
            "reason": "Separate depth/cost study required",
        },
        failure_conditions=(
            "Insufficient purged labels",
            "Heldout baseline improvement absent",
            "Unreviewed event dependence",
        ),
        limitations=(
            "Single captured live-data window; repeated market events are dependent",
            "No terminal-outcome calibration authority",
            "No independent external context",
            "Selection is exploratory and cannot certify a strategy",
        ),
    )
    report = {
        "spec": spec.model_dump(mode="json"),
        "samples": len(samples),
        "skipped": skipped,
        "split_counts": {k: len(split[k]) for k in ("train", "validation", "heldout")},
        "purged_labels": split["purged"],
        "boundaries": split["boundaries"],
        "terminal_probability": {
            "brier": None,
            "log_loss": None,
            "calibration": None,
            "reason": "No qualified point-in-time verified independent final-outcome dataset",
        },
        "confidence_interval": None,
        "confidence_interval_reason": "Overlapping labels and unreviewed inter-event dependence prevent independent inference",
        "gradient_boosting": "deferred: simple models must establish repeatable heldout improvement first",
        "promotion_allowed": False,
        "adaptive_comparisons": [],
        "model_selection_scope": "validation_only; heldout scores never choose fitted model or temperature",
    }
    if len(train) < 100 or len(validation) < 50 or len(heldout) < 50:
        return {**report, "status": "insufficient_chronological_evidence", "results": None}
    model = fit_models(train)
    valid_prediction = predict(model, validation)["logistic_bid_rise"]
    labels = [r["target_bid_rise"] for r in validation]
    temperature = min(
        (0.5, 1.0, 2.0),
        key=lambda t: probability_metrics(
            [_sigmoid(log(max(1e-8, p) / max(1e-8, 1 - p)) / t) for p in valid_prediction], labels
        )["brier"],
    )
    results = {k: _metrics(model, split[k], temperature) for k in ("train", "validation", "heldout")}
    selected = min(
        results["validation"]["horizon_mark"], key=lambda k: results["validation"]["horizon_mark"][k]["mae"]
    )
    base = results["heldout"]["horizon_mark"]["unchanged_bid"]["mae"]
    selected_mae = results["heldout"]["horizon_mark"][selected]["mae"]
    operational_comparison = {}
    for partition in ("train", "validation", "heldout"):
        subset = [r for r in split[partition] if r["operational_forecast_change"] is not None]
        operational_comparison[partition] = {
            "count": len(subset),
            "operational_horizon_mae": mean(
                abs(r["target_change"] - r["operational_forecast_change"]) for r in subset
            )
            if subset
            else None,
            "unchanged_bid_mae_same_rows": mean(abs(r["target_change"]) for r in subset) if subset else None,
        }
    by_token = defaultdict(list)
    for row in heldout:
        by_token[row["token_id"]].append(row)
    category_comparison = {
        token: {
            "event_ids": sorted({r["event_id"] for r in token_rows if r["event_id"]}),
            "count": len(token_rows),
            "metrics": _metrics(model, token_rows, temperature),
        }
        for token, token_rows in by_token.items()
    }
    temporal = []
    for i in range(3):
        block = heldout[len(heldout) * i // 3 : len(heldout) * (i + 1) // 3]
        temporal.append(_metrics(model, block, temperature))
    return {
        **report,
        "status": "exploratory_evaluated",
        "results": results,
        "operational_reference_comparison": operational_comparison,
        "operational_reference_note": "Exact existing horizon forecast helper on sequential actual books; no fee/risk/admission bypass; compared on same available subset and not selected as challenger",
        "training_parameters": model,
        "validation_only_temperature": temperature,
        "adaptive_comparisons": [
            {
                "model": name,
                "metric": "heldout_mae",
                "value": value["mae"],
                "baseline_value": base,
                "sample_count": len(heldout),
                "independent_events": 0,
            }
            for name, value in results["heldout"]["horizon_mark"].items()
        ],
        "validation_selected_mark_model": selected,
        "heldout_mae_improvement": base - selected_mae,
        "overfit_warning": selected != "unchanged_bid" and selected_mae >= base,
        "heldout_temporal_blocks": temporal,
        "heldout_by_token": category_comparison,
        "ensemble": "deferred: no independent validation gain demonstrated over the selected simple baseline",
        "credible_cost_adjusted_advantage": False,
        "conclusion": "Forecast improvements alone are not evidence of executable cost-adjusted edge",
    }
