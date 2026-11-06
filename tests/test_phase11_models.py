"""Controlled fixtures only; none are operational market observations."""

from datetime import UTC, datetime, timedelta

import pytest
from neraium_poly.contracts import MarketSnapshot, OrderBookSnapshot, PriceLevel
from neraium_poly.research.phase11.contracts import ResearchObservation
from neraium_poly.research.phase11.models import (
    chronological_split,
    fit_models,
    predict,
    probability_metrics,
    run_models,
    supervised_samples,
)
from neraium_poly.research.phase11.relationships import run_relationships

START = datetime(2026, 1, 1, tzinfo=UTC)
MANIFEST = {"dataset_sha256": "a" * 64}


def row(i, *, token="a", price=0.4, event="controlled-event"):
    at = START + timedelta(seconds=5 * i)
    market = MarketSnapshot(
        id="controlled-market-" + token,
        timestamp=START,
        available_at=START,
        source="controlled-test-only",
        market_id="market-" + token,
        token_id=token,
        event_id=event,
        question="CONTROLLED fixture",
        outcome="Yes",
        probability=0.5,
        status="active",
        resolution_rules="CONTROLLED rules",
        resolution_source="controlled",
    )
    book = OrderBookSnapshot(
        id=f"controlled-{token}-{i}",
        timestamp=at,
        available_at=at + timedelta(seconds=1),
        source="controlled-test-only",
        market_id=market.market_id,
        token_id=token,
        bids=(PriceLevel(price=price, size=100),),
        asks=(PriceLevel(price=price + 0.01, size=80),),
    )
    return ResearchObservation(book=book, market=market)


def fixture_rows(n=600):
    return [row(i, token=t, price=0.4 + (i % 20) * 0.0001) for i in range(n) for t in ("a", "b")]


def test_causal_features_never_depend_on_future_observations():
    rows = fixture_rows(100)
    samples, _ = supervised_samples(rows)
    early = samples[10]
    changed = [
        r
        if r.book.available_at <= early["decision_at"]
        else r.model_copy(
            update={
                "book": r.book.model_copy(
                    update={
                        "bids": (PriceLevel(price=0.6, size=5),),
                        "asks": (PriceLevel(price=0.61, size=8),),
                    }
                )
            }
        )
        for r in rows
    ]
    after, _ = supervised_samples(changed)
    same = next(r for r in after if r["id"] == early["id"])
    assert same["features"] == early["features"]
    assert same["operational_forecast_change"] == early["operational_forecast_change"]
    assert same["target_change"] != early["target_change"]
    assert all(r["source_at"] <= r["decision_at"] < r["label_available_at"] for r in samples)
    assert all(r["label_source_at"] >= r["decision_at"] + timedelta(seconds=60) for r in samples)


def test_split_purges_labels_before_next_partition():
    samples, _ = supervised_samples(fixture_rows(200))
    split = chronological_split(samples)
    first, second = map(datetime.fromisoformat, split["boundaries"])
    assert split["purged"] > 0
    assert all(r["label_available_at"] < first for r in split["train"])
    assert all(
        first <= r["decision_at"] < second and r["label_available_at"] < second for r in split["validation"]
    )
    assert all(r["decision_at"] >= second for r in split["heldout"])
    sets = [{r["id"] for r in split[k]} for k in ("train", "validation", "heldout")]
    assert not sets[0] & sets[1] and not sets[0] & sets[2] and not sets[1] & sets[2]


def test_scaling_and_fitting_use_only_explicit_training_partition():
    samples, _ = supervised_samples(fixture_rows(200))
    split = chronological_split(samples)
    model = fit_models(split["train"])
    original = predict(model, split["validation"])
    split["heldout"][0]["features"] = [1e10] * 6
    split["heldout"][0]["target_change"] = 99
    assert fit_models(split["train"]) == model
    assert predict(model, split["validation"]) == original


def test_probability_scores_are_for_bid_rise_and_terminal_metrics_stay_null():
    result = run_models(fixture_rows(), MANIFEST)
    assert result["status"] == "exploratory_evaluated"
    assert result["spec"]["grouping"]["train_heldout_event_overlap"] == 1
    assert result["spec"]["grouping"]["reviewed_independent_events"] == 0
    assert result["terminal_probability"]["brier"] is None
    assert result["confidence_interval"] is None
    assert result["promotion_allowed"] is False
    assert not result["credible_cost_adjusted_advantage"]
    selected = result["validation_selected_mark_model"]
    assert selected == min(
        result["results"]["validation"]["horizon_mark"],
        key=lambda k: result["results"]["validation"]["horizon_mark"][k]["mae"],
    )
    scores = result["results"]["heldout"]["directional_probability"]["logistic_bid_rise"]
    assert scores["target"] == "60_second_observed_bid_rise_not_settlement"
    assert 0 <= scores["brier"] <= 1 and scores["log_loss"] >= 0
    assert len(result["adaptive_comparisons"]) == 4


def test_missing_split_evidence_is_explicit_not_fabricated_scores():
    r = run_models([row(0)], MANIFEST)
    assert r["status"] == "insufficient_chronological_evidence"
    assert r["results"] is None and r["terminal_probability"]["calibration"] is None


def test_probability_validation_and_known_metrics():
    scores = probability_metrics([0.25, 0.75], [0, 1])
    assert scores["brier"] == pytest.approx(0.0625)
    assert scores["log_loss"] == pytest.approx(-__import__("math").log(0.75))
    for p, y in [([float("nan")], [0]), ([1.1], [1]), ([0.5], [2]), ([], [])]:
        with pytest.raises(ValueError):
            probability_metrics(p, y)


def test_duplicate_or_stale_sources_cannot_create_extra_training_evidence():
    rows = fixture_rows(100)
    base, _ = supervised_samples(rows)
    duplicate, _ = supervised_samples(rows + rows)
    assert duplicate == base
    first = rows[10]
    wrong = first.model_copy(
        update={"book": first.book.model_copy(update={"bids": (PriceLevel(price=0.2, size=5),)})}
    )
    with pytest.raises(ValueError, match="conflicting"):
        supervised_samples(rows + [wrong])


def test_future_metadata_or_fee_context_rejected():
    r = row(0)
    with pytest.raises(ValueError, match="future metadata"):
        ResearchObservation(
            book=r.book, market=r.market.model_copy(update={"available_at": START + timedelta(days=1)})
        )
    with pytest.raises(ValueError, match="future fee"):
        ResearchObservation(book=r.book, fee={"observed_at": (START + timedelta(days=1)).isoformat()})


def test_relationships_need_real_fresh_aligned_legs_and_persistent_changes():
    rows = []
    for i in range(35):
        rows.extend([row(i, token="a", price=0.4 if i < 23 else 0.5), row(i, token="b", price=0.4)])
    result = run_relationships(rows, MANIFEST)
    assert result["counts"]["paired_observations"] >= 25
    assert result["counts"]["persistent_findings"] == 1
    assert result["findings"][0]["persistence"] == 3
    assert result["findings"][0]["logical_constraint"] is False
    assert result["net_edge"] is None and result["logical_constraints_verified"] == 0
    assert result["false_positive_rate"] is None and result["promotion_allowed"] is False


def test_relationships_reject_missing_context_and_stale_leg():
    rows = [row(0, token="a"), row(10, token="b")]
    result = run_relationships(rows, MANIFEST)
    assert result["counts"]["stale_or_incomplete_pair"] == 1
    assert result["findings"] == []
    no_context = [ResearchObservation(book=r.book) for r in rows]
    result = run_relationships(no_context, MANIFEST)
    assert result["counts"]["missing_point_in_time_metadata"] == 2
    assert result["findings"] == []


def test_prediction_marks_stay_bounded_without_changing_probability_target():
    samples, _ = supervised_samples(fixture_rows(100))
    fitted = fit_models(samples[:50])
    extreme = dict(samples[60], features=[1e10] * 6, bid=0.99)
    predictions = predict(fitted, [extreme])
    assert 0 <= extreme["bid"] + predictions["ridge"][0] <= 1
    assert 0 <= predictions["logistic_bid_rise"][0] <= 1
    assert probability_metrics([0, 1], [0, 1])["brier"] == 0


def test_relationship_reused_source_time_cannot_inflate_persistence():
    rows = []
    for i in range(25):
        rows.extend([row(i, token="a"), row(i, token="b")])
    original = run_relationships(rows, MANIFEST)
    # Two later receipts with new IDs but old source stamps are actual stale
    # source evidence, not two independent relationship observations.
    for token in ("a", "b"):
        old = row(24, token=token)
        rows.append(
            old.model_copy(
                update={
                    "book": old.book.model_copy(
                        update={
                            "id": "controlled-reused-source-" + token,
                            "available_at": old.book.available_at + timedelta(seconds=2),
                        }
                    )
                }
            )
        )
    changed = run_relationships(rows, MANIFEST)
    assert changed["counts"]["paired_observations"] == original["counts"]["paired_observations"]
    assert changed["counts"]["out_of_order_or_reused_source_pair"] >= 1
