"""Reproducible event-purged research, never a strategy activation mechanism.

Retrospective source event-time analysis is explicitly separated from proven
point-in-time availability. Missing books, fees or labels produce null metrics.
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from hashlib import sha256
from math import exp, isfinite, log, sqrt
from pathlib import Path
from statistics import mean, stdev
from urllib.parse import urlparse

from neraium_poly.research.contracts import ResearchBundle, ResearchContext, ResearchEvent, ResearchPrice
from neraium_poly.research.strategies import strategy_catalog
from neraium_poly.validation import ValidationPolicy


@dataclass(frozen=True)
class _Row:
    event: ResearchEvent
    price: ResearchPrice
    context: ResearchContext | None

    @property
    def decision_at(self):
        return (
            self.price.available_at
            if self.price.availability_basis == "verified_archive"
            else self.price.timestamp
        )


def _canonical(bundle):
    data = {
        key: sorted(
            (r.model_dump(mode="json") for r in getattr(bundle, key)), key=lambda r: (r["timestamp"], r["id"])
        )
        for key in ("events", "prices", "books", "context")
    }
    data.update(manifest_sha256=bundle.manifest_sha256, deficiencies=sorted(bundle.deficiencies))
    return sha256(json.dumps(data, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _independent_context(context, at):
    return (
        context.independent
        and context.value is not None
        and isfinite(context.value)
        and context.kind in {"numeric_predictor", "probability_forecast"}
        and context.source.startswith("https://")
        and "polymarket.com" not in context.source
        and context.reference
        and len(context.raw_sha256) == 64
        and context.timestamp <= at
        and context.available_at <= at
        and context.availability_basis == "verified_archive"
    )


def _rows(bundle):
    by_event = defaultdict(list)
    unavailable = any(
        record.available_at > bundle.available_at
        for kind in ("events", "prices", "books", "context")
        for record in getattr(bundle, kind)
    )
    for event in bundle.events:
        if event.available_at <= bundle.available_at:
            by_event[event.event_id].append(event)
    rows = []
    reasons = set()
    verified_count = 0
    if unavailable:
        reasons.add("future_record_unavailable_as_of_bundle")
    for event_id, events in sorted(by_event.items()):
        valid = [
            e
            for e in events
            if e.outcome_verified
            and e.outcome in (0, 1)
            and e.settlement_at is not None
            and e.settlement_ref
            and e.available_at >= e.settlement_at
        ]
        if not valid:
            if any(e.outcome_verified and e.settlement_at is None for e in events):
                reasons.add("verified_outcome_missing_exact_settlement_time")
            continue
        by_token = defaultdict(set)
        for event in valid:
            by_token[(event.market_id, event.token_id)].add(event.outcome)
        if any(len(outcomes) > 1 for outcomes in by_token.values()):
            reasons.add("contradictory_verified_labels")
            continue
        verified_count += 1
        # One deterministic market/outcome per event. Related legs cannot inflate n.
        first_key = min((e.market_id, e.token_id) for e in valid)
        event = max(
            (e for e in valid if (e.market_id, e.token_id) == first_key), key=lambda e: (e.available_at, e.id)
        )
        eligible = [
            p
            for p in bundle.prices
            if p.available_at <= bundle.available_at
            and (p.event_id, p.market_id, p.token_id) == (event_id, event.market_id, event.token_id)
            and p.timestamp < event.settlement_at
            and (event.created_at is None or p.timestamp >= event.created_at)
        ]
        if not eligible:
            reasons.add("missing_pre_resolution_price_history")
            continue
        # First observed source quote is fixed without choosing a profitable lead time
        # relative to the subsequently known resolution time.
        price = min(eligible, key=lambda p: (p.timestamp, p.available_at, p.id))
        at = price.available_at if price.availability_basis == "verified_archive" else price.timestamp
        contexts = [c for c in bundle.context if c.event_id == event_id and _independent_context(c, at)]
        context = max(contexts, key=lambda c: (c.available_at, c.id)) if contexts else None
        rows.append(_Row(event, price, context))
    return sorted(rows, key=lambda r: (r.decision_at, r.event.event_id)), verified_count, reasons


def _ci(values, low=None, high=None):
    if len(values) < 2:
        return None
    center = mean(values)
    margin = 1.96 * stdev(values) / sqrt(len(values))
    return [
        max(low, center - margin) if low is not None else center - margin,
        min(high, center + margin) if high is not None else center + margin,
    ]


def _metrics(predictions, rows):
    if not predictions:
        return None
    errors = [(p - r.event.outcome) ** 2 for p, r in zip(predictions, rows)]
    losses = [
        -(
            r.event.outcome * log(max(1e-12, min(1 - 1e-12, p)))
            + (1 - r.event.outcome) * log(max(1e-12, min(1 - 1e-12, 1 - p)))
        )
        for p, r in zip(predictions, rows)
    ]
    bins = []
    ece = 0.0
    for b in range(5):
        indices = [i for i, p in enumerate(predictions) if min(4, int(p * 5)) == b]
        if not indices:
            continue
        avg = mean(predictions[i] for i in indices)
        freq = mean(rows[i].event.outcome for i in indices)
        ece += len(indices) / len(rows) * abs(avg - freq)
        bins.append({"bin": b, "events": len(indices), "mean_forecast": avg, "outcome_frequency": freq})
    return {
        "events": len(rows),
        "brier_score": mean(errors),
        "brier_ci95": _ci(errors, 0, 1),
        "log_loss": mean(losses),
        "log_loss_ci95": _ci(losses, 0),
        "expected_calibration_error": ece,
        "calibration_bins": bins,
        "interval_method": "event-level normal approximation; exploratory, not certification",
    }


def _group_metrics(predictions, rows, key):
    groups = defaultdict(list)
    for i, row in enumerate(rows):
        groups[key(row)].append(i)
    return {
        name: _metrics([predictions[i] for i in indices], [rows[i] for i in indices])
        for name, indices in sorted(groups.items())
    }


def _bucket(p):
    return min(4, int(p * 5))


def _histogram(train, test):
    counts = [0] * 5
    wins = [0] * 5
    for row in train:
        b = _bucket(row.price.probability)
        counts[b] += 1
        wins[b] += row.event.outcome
    predictions = []
    lowers = []
    for row in test:
        b = _bucket(row.price.probability)
        n = counts[b]
        if n < 30:
            return None, None, "insufficient_per_bin_calibration_samples"
        p = (wins[b] + 1) / (n + 2)
        z = 1.96
        den = 1 + z * z / (n + 2)
        center = (p + z * z / (2 * (n + 2))) / den
        radius = z * sqrt(p * (1 - p) / (n + 2) + z * z / (4 * (n + 2) ** 2)) / den
        predictions.append(p)
        lowers.append(max(0, min(p, center - radius)))
    return predictions, lowers, None


def _sigmoid(v):
    if v >= 0:
        return 1 / (1 + exp(-min(v, 700)))
    e = exp(max(v, -700))
    return e / (1 + e)


def _logistic(train, test):
    # Three coefficients, regularized gradient descent; no heavyweight ML dependency.
    if any(row.context is None for row in (*train, *test)):
        return None, "independent_point_in_time_numeric_context_missing"
    context_mean = mean(row.context.value for row in train)
    context_scale = stdev(row.context.value for row in train) if len(train) > 1 else 0
    if context_scale < 1e-12:
        return None, "independent_context_has_no_training_variation"

    def features(row):
        p = max(0.001, min(0.999, row.price.probability))
        return (1.0, log(p / (1 - p)), (row.context.value - context_mean) / context_scale)

    weights = [0.0] * 3
    for _ in range(250):
        gradient = [0.0] * 3
        for row in train:
            x = features(row)
            error = _sigmoid(sum(w * v for w, v in zip(weights, x))) - row.event.outcome
            for j in range(3):
                gradient[j] += error * x[j] / len(train)
        for j in range(3):
            weights[j] -= 0.05 * (gradient[j] + (0.01 * weights[j] if j else 0))
    return [_sigmoid(sum(w * v for w, v in zip(weights, features(row)))) for row in test], None


def _archive_book(row, bundle):
    at = row.decision_at
    matching = [
        b
        for b in bundle.books
        if (b.market_id, b.token_id) == (row.event.market_id, row.event.token_id)
        and b.source == "https://clob.polymarket.com"
        and b.complete
        and b.bids
        and b.asks
        and b.available_at <= at
        and 0 <= (at - b.timestamp).total_seconds() <= 15
    ]
    return max(matching, key=lambda b: (b.available_at, b.id)) if matching else None


def _fee(row, bundle):
    matching = [
        c
        for c in bundle.context
        if c.event_id == row.event.event_id
        and c.kind == "protocol_fee_rate"
        and c.value is not None
        and 0 <= c.value <= 1
        and urlparse(c.source).hostname == "clob.polymarket.com"
        and urlparse(c.source).scheme == "https"
        and row.event.token_id in c.reference
        and len(c.raw_sha256) == 64
        and c.available_at <= row.decision_at
        and c.availability_basis == "verified_archive"
    ]
    return max(matching, key=lambda c: (c.available_at, c.id)).value if matching else None


def _cost_analysis(bundle, rows, lowers):
    # Never generate historical fills from historical prices or current depth.
    if not rows:
        return None, ["no_heldout_execution_rows"]
    if any(
        r.price.availability_basis != "verified_archive" or r.event.availability_basis != "verified_archive"
        for r in rows
    ):
        return None, ["point_in_time_execution_availability_unverified"]
    books = [_archive_book(row, bundle) for row in rows]
    if any(b is None for b in books):
        return None, ["authentic_historical_order_books_missing"]
    fees = [_fee(row, bundle) for row in rows]
    if any(fee is None for fee in fees):
        return None, ["point_in_time_fee_provenance_missing"]
    if lowers is None:
        return None, ["calibrated_lower_probability_missing"]
    decisions = []
    cash = 500.0
    pending = []
    settlements = []
    for row, book, fee, lower in zip(rows, books, fees, lowers):
        at = row.decision_at
        matured = [p for p in pending if p["settlement_at"] <= at]
        for trade in matured:
            cash += trade["payout"]
            settlements.append(trade)
        pending = [p for p in pending if p["settlement_at"] > at]
        price = book.asks[0].price
        cost = price * (1 + fee) + 0.01
        if lower - cost < 0.03:
            continue
        quantity = min(2 / price, book.asks[0].size * 0.1)
        principal = quantity * cost
        if (
            quantity * price < 2 - 1e-8
            or cash < principal
            or sum(p["cost"] for p in pending) + principal > 100
        ):
            continue
        cash -= principal
        trade = {
            "event_id": row.event.event_id,
            "decision_at": at.isoformat(),
            "settlement_at": max(row.event.settlement_at, row.event.available_at),
            "cost": principal,
            "payout": quantity * row.event.outcome,
            "pnl": quantity * row.event.outcome - principal,
            "entry_book_id": book.id,
            "quantity": quantity,
        }
        pending.append(trade)
        decisions.append(trade)
    settlements.extend(pending)
    settlements.sort(key=lambda t: (t["settlement_at"], t["event_id"]))
    cumulative = peak = drawdown = 0.0
    for trade in settlements:
        cumulative += trade["pnl"]
        peak = max(peak, cumulative)
        drawdown = max(drawdown, peak - cumulative)
    pnls = [t["pnl"] for t in decisions]
    return {
        "conditional_simulated_pnl": sum(pnls),
        "modeled_trades": len(decisions),
        "actual_fills": None,
        "per_trade_pnl_ci95": _ci(pnls),
        "max_drawdown": drawdown,
        "initial_bankroll": 500,
        "aggregate_cost_cap": 100,
        "fill_assumption": "Conditional immediate taker fill, capped at10% of supplied best ask; not observed historical fills",
        "cost_assumption": "Global conservative notional fee bound plus $.01/share latency/slippage",
        "additional_cost_per_share_sensitivity": {
            str(extra): sum(t["pnl"] - t["quantity"] * extra for t in decisions)
            for extra in (0.0, 0.005, 0.01)
        },
        "trade_event_ids": [t["event_id"] for t in decisions],
    }, []


def evaluate_bundle(bundle: ResearchBundle) -> dict:
    """Compare six candidates and baseline models without relaxing certification.

    The evaluator cannot issue a certificate. A separate exact strategy package
    must pass ValidationStore and explicit owner approval before any activation.
    """
    dataset_hash = _canonical(bundle)
    rows, verified_count, reasons = _rows(bundle)
    reasons.update(bundle.deficiencies)
    reasons.add("cross_event_dependency_review_required")
    contradictory = False
    for kind in ("events", "prices", "books", "context"):
        seen = {}
        for record in getattr(bundle, kind):
            previous = seen.setdefault(record.id, record.model_dump_json())
            if previous != record.model_dump_json():
                contradictory = True
    if contradictory:
        reasons.add("conflicting_record_id")
        rows = []
    archive_mode = bool(rows) and all(
        r.price.availability_basis == "verified_archive" and r.event.availability_basis == "verified_archive"
        for r in rows
    )
    split = max(100, len(rows) // 2) if len(rows) >= 200 else min(100, len(rows))
    train, test = rows[:split], rows[split:]
    if test:
        first_decision = test[0].decision_at
        # Retrospective event-time filtering is not an assertion that the labels
        # were publicly available then. The analysis_mode makes that distinction.
        train = [
            r
            for r in train
            if (r.event.available_at if archive_mode else r.event.settlement_at) < first_decision
        ]
    if len(train) < 100:
        reasons.add("fewer_than100_independent_training_events")
    if len(test) < 100:
        reasons.add("fewer_than100_independent_heldout_events")
    if not archive_mode:
        reasons.add("historical_point_in_time_availability_unverified")
    if not bundle.books or any(_archive_book(row, bundle) is None for row in rows):
        reasons.add("authentic_historical_order_books_missing")
    if rows and any(_fee(row, bundle) is None for row in rows):
        reasons.add("point_in_time_fee_provenance_missing")
    if sum(r.context is not None for r in rows) < 200:
        reasons.add("independent_point_in_time_context_missing")
    models = []

    def record_model(name, predictions, lowers=None, model_reason=None, independent=False):
        if predictions is None:
            models.append(
                {
                    "id": name,
                    "status": "not_evaluable",
                    "reasons": [model_reason],
                    "metrics": None,
                    "calibration": None,
                    "by_category": {},
                    "by_regime": {},
                    "execution_cost_analysis": None,
                }
            )
            return
        metrics = _metrics(predictions, test)
        cost, cost_reasons = _cost_analysis(bundle, test, lowers)
        models.append(
            {
                "id": name,
                "status": "exploratory_only",
                "independent_forecast": independent,
                "reasons": cost_reasons,
                "metrics": metrics,
                "calibration": metrics["calibration_bins"] if metrics else None,
                "by_category": _group_metrics(predictions, test, lambda r: r.event.category),
                "by_regime": _group_metrics(
                    predictions,
                    test,
                    lambda r: (
                        "extreme_price"
                        if r.price.probability < 0.1 or r.price.probability > 0.9
                        else "central_price"
                    ),
                ),
                "execution_cost_analysis": cost,
            }
        )

    record_model(
        "raw_market_price",
        [r.price.probability for r in test] if test else None,
        model_reason="no_chronological_heldout_rows",
    )
    if len(train) >= 100 and len(test) >= 100:
        histogram, lowers, error = _histogram(train, test)
        record_model("histogram_calibration", histogram, lowers, error)
        logistic, error = _logistic(train, test)
        record_model("regularized_context_logistic", logistic, model_reason=error, independent=True)
        independent = (
            [r.context.value for r in test]
            if all(
                r.context and r.context.kind == "probability_forecast" and 0 <= r.context.value <= 1
                for r in (*train, *test)
            )
            else None
        )
        record_model(
            "independent_context_probability",
            independent,
            model_reason="independent_probability_forecast_archive_missing",
            independent=True,
        )
    else:
        for name in (
            "histogram_calibration",
            "regularized_context_logistic",
            "independent_context_probability",
        ):
            record_model(name, None, model_reason="independent100_train100_heldout_gate_not_met")
    # Choose simplicity, and require confidence-bounded measured improvement
    # before even recommending the more complex research model.
    recommended = None
    modelmap = {m["id"]: m for m in models}
    hist = modelmap["histogram_calibration"]
    logistic = modelmap["regularized_context_logistic"]
    if hist["metrics"]:
        recommended = "histogram_calibration"
    if logistic["metrics"] and hist["metrics"]:
        # Aggregate CI overlap is conservative; no unsupported paired improvement
        # claim is derived when raw per-event prediction output is unavailable.
        hi = hist["metrics"]["brier_ci95"]
        lo = logistic["metrics"]["brier_ci95"]
        if hi and lo and lo[1] < hi[0]:
            recommended = "regularized_context_logistic"
    candidates = []
    for spec in strategy_catalog():
        deficits = set(reasons)
        if spec["id"] == "persistent_relationship":
            deficits.add("qualified_causal_relationship_findings_and_scope_required")
        elif spec["id"] == "logical_constraints":
            deficits.update(
                (
                    "reviewed_exhaustive_payoff_constraints_missing",
                    "atomic_or_hedged_bundle_execution_unvalidated",
                )
            )
        elif spec["id"] == "independent_forecast" and not modelmap["regularized_context_logistic"]["metrics"]:
            deficits.add("independent_calibrated_forecast_not_evaluable")
        elif spec["id"] == "liquidity_maker":
            deficits.update(
                (
                    "historical_queue_and_trade_events_missing",
                    "maker_fill_and_inventory_exit_model_unvalidated",
                )
            )
        elif spec["id"] == "event_repricing":
            deficits.add("causal_pre_and_post_publication_quote_archives_required")
        elif spec["id"] == "microstructure":
            deficits.update(
                ("horizon_return_and_exit_depth_labels_required", "short_horizon_calibration_required")
            )
        deficits.update(("strict_strategy_validation_package_required", "explicit_owner_approval_required"))
        relevant = (
            modelmap["histogram_calibration"]
            if spec["id"] == "persistent_relationship"
            else modelmap["regularized_context_logistic"]
            if spec["id"] in {"independent_forecast", "event_repricing"}
            else None
        )
        candidates.append(
            {
                **spec,
                "data_requirements": spec["required_data"],
                "status": "exploratory_only"
                if spec["id"] == "independent_forecast" and relevant and relevant["metrics"]
                else "not_evaluable",
                "required_data_deficits": sorted(deficits),
                "metrics": relevant["metrics"] if spec["id"] == "independent_forecast" and relevant else None,
                "metric_scope": "independent_forecast_quality_only"
                if spec["id"] == "independent_forecast" and relevant and relevant["metrics"]
                else None,
                "supporting_model": {"id": relevant["id"], "metrics": relevant["metrics"]}
                if relevant
                else None,
                "certification_status": "blocked",
                "simulated_pnl": None,
            }
        )
    return {
        "schema_version": "1.0",
        "dataset_hash": dataset_hash,
        "evaluation_as_of": bundle.available_at.isoformat(),
        "analysis_mode": "point_in_time_archive" if archive_mode else "retrospective_event_time_only",
        "uncertainty_basis": "Nominal event-level intervals assume independence; cross-event dependency review is missing",
        "coverage": {
            "events": len(bundle.events),
            "distinct_verified_outcome_groups": verified_count,
            "reported_verified_outcome_groups": len(
                {
                    e.event_id
                    for e in bundle.events
                    if e.outcome_verified and e.available_at <= bundle.available_at
                }
            ),
            "causally_usable_verified_outcome_groups": verified_count,
            "independent_verified_events": 0,
            "independence_basis": "Event/parent-ID deduplication only; asset/series and overlapping-window dependence not reviewed",
            "forecast_rows": len(rows),
            "train_events": len(train),
            "heldout_events": len(test),
            "point_in_time_rows": sum(
                r.price.availability_basis == "verified_archive"
                and r.event.availability_basis == "verified_archive"
                for r in rows
            ),
            "books": len(bundle.books),
            "independent_context": sum(r.context is not None for r in rows),
            "related_legs_not_independent": len(bundle.events) - len({e.event_id for e in bundle.events}),
        },
        "split": {
            "method": "one deterministic earliest-source forecast per event; chronological event purge",
            "train_event_ids": [r.event.event_id for r in train],
            "heldout_event_ids": [r.event.event_id for r in test],
            "forecast_record_ids": [r.price.id for r in rows],
            "training_label_time_basis": "verified_available_at"
            if archive_mode
            else "retrospective_settlement_event_time_only",
        },
        "models": models,
        "candidates": candidates,
        "recommended_model": recommended,
        "certification": {
            "status": "blocked",
            "thresholds": ValidationPolicy().model_dump(mode="json"),
            "deficiencies": sorted(
                reasons | {"strict_strategy_validation_package_required", "explicit_owner_approval_required"}
            ),
            "owner_approval_required": True,
        },
        "limitations": [
            "No report in this module activates a strategy or creates an order/fill.",
            "Retrospective metrics do not establish contemporaneous public availability or executable performance.",
            "Normal-approximation event confidence intervals and candidate comparisons do not correct undisclosed repeated holdout selection.",
            "Price regimes describe fixed price bands, not a learned economic market regime.",
        ],
    }


def write_report(bundle: ResearchBundle, path: str | Path) -> dict:
    report = evaluate_bundle(bundle)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n")
    return report
