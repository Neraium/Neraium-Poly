"""Controlled synthetic research assertions, never real validation or activation."""

import json
from datetime import UTC, datetime, timedelta
from hashlib import sha256

import pytest
from neraium_poly.contracts import (
    MarketRelationship,
    OrderBookSnapshot,
    PriceLevel,
    ProbabilityEstimate,
    RelationshipEvidence,
)
from neraium_poly.research.contracts import ResearchBundle, ResearchContext, ResearchEvent, ResearchPrice
from neraium_poly.research.evaluation import evaluate_bundle, write_report
from neraium_poly.research.strategies import (
    event_repricing_signal,
    independent_forecast_signal,
    logical_constraint_signal,
    maker_signal,
    microstructure_signal,
    persistent_relationship_signal,
    strategy_catalog,
)

BASE = datetime(2020, 1, 1, tzinfo=UTC)
NOW = datetime(2026, 1, 1, tzinfo=UTC)
HASH = sha256(b"explicit synthetic test provenance").hexdigest()


def make_book(at=NOW, market="m", token="t", bid=0.39, ask=0.4, sequence=0):
    return OrderBookSnapshot(
        id=f"book-{token}-{at.isoformat()}",
        timestamp=at,
        available_at=at,
        source="https://clob.polymarket.com",
        market_id=market,
        token_id=token,
        bids=(PriceLevel(price=bid, size=1000),),
        asks=(PriceLevel(price=ask, size=1000),),
        sequence=sequence,
    )


def context(at=NOW, **updates):
    values = {
        "id": "context",
        "timestamp": at,
        "available_at": at,
        "source": "https://independent.example",
        "event_id": "e",
        "kind": "probability_forecast",
        "value": 0.8,
        "reference": "controlled-test-ref",
        "independent": True,
        "availability_basis": "verified_archive",
        "raw_sha256": HASH,
    }
    values.update(updates)
    return ResearchContext(**values)


def estimate(at=NOW, ids=("context",)):
    return ProbabilityEstimate(
        id="forecast",
        timestamp=at,
        available_at=at,
        source="controlled-test-calibrator",
        market_id="m",
        token_id="t",
        probability=0.8,
        lower=0.7,
        upper=0.9,
        model_id="test-artifact",
        calibrated=True,
        evidence_ids=ids,
    )


def bundle(n=200, *, archive=False, books=False, independent=False, fees=False, correlated=False):
    events = []
    prices = []
    snapshots = []
    contexts = []
    basis = "verified_archive" if archive else "collected_now"
    for i in range(n):
        at = BASE + timedelta(days=i * 2)
        received = at + timedelta(seconds=1) if archive else NOW
        final = at + timedelta(days=1)
        observed = final + timedelta(seconds=1) if archive else NOW
        event_id = f"event{i // 2 if correlated else i}"
        market = f"market{i}"
        token = f"token{i}"
        feature = 0.8 if i % 5 < 4 else 0.2
        events.append(
            ResearchEvent(
                id=f"event-row{i}",
                timestamp=final,
                available_at=observed,
                source="https://data-api.polymarket.com/v2/resolutions",
                market_id=market,
                event_id=event_id,
                token_id=token,
                question="Controlled synthetic research assertion",
                category="A" if i % 2 else "B",
                created_at=at - timedelta(days=1),
                closed_at=final,
                outcome=int(feature > 0.5),
                outcome_verified=True,
                settlement_at=final,
                settlement_ref=f"controlled-final-{i}",
                availability_basis=basis,
                raw_sha256=HASH,
                raw_ref=f"test-{i}",
            )
        )
        prices.append(
            ResearchPrice(
                id=f"price{i}",
                timestamp=at,
                available_at=received,
                source="https://clob.polymarket.com/prices-history",
                market_id=market,
                event_id=event_id,
                token_id=token,
                probability=0.4,
                availability_basis=basis,
                raw_sha256=HASH,
                raw_ref=f"test-price-{i}",
            )
        )
        if books:
            snapshots.append(make_book(at, market, token))
        if independent:
            contexts.append(context(at, event_id=event_id, id=f"context{i}", value=feature))
        if fees:
            contexts.append(
                ResearchContext(
                    id=f"fee{i}",
                    timestamp=at,
                    available_at=at,
                    source="https://clob.polymarket.com",
                    event_id=event_id,
                    kind="protocol_fee_rate",
                    value=0.02,
                    reference=f"controlled-curve/{token}",
                    independent=False,
                    availability_basis="verified_archive",
                    raw_sha256=HASH,
                )
            )
    return ResearchBundle(
        id="test-bundle",
        timestamp=NOW,
        available_at=NOW,
        source="synthetic-unit-test",
        events=tuple(events),
        prices=tuple(prices),
        books=tuple(snapshots),
        context=tuple(contexts),
        manifest_sha256=HASH,
    )


def test_catalog_contains_six_complete_hypotheses():
    catalog = strategy_catalog()
    assert len(catalog) == 6 and len({s["id"] for s in catalog}) == 6
    assert all(
        s["entry"] and s["exit"] and s["value_model"] and s["failure_cases"] and s["risk_assumptions"]
        for s in catalog
    )


def test_empty_bundle_never_fabricates_metrics_or_profit():
    result = evaluate_bundle(bundle(0))
    assert result["certification"]["status"] == "blocked"
    assert len(result["candidates"]) == 6
    assert all(c["metrics"] is None and c["simulated_pnl"] is None for c in result["candidates"])
    assert all(m["metrics"] is None and m["execution_cost_analysis"] is None for m in result["models"])


def test_retrospective_real_shape_cannot_claim_point_in_time_execution():
    result = evaluate_bundle(bundle())
    assert result["analysis_mode"] == "retrospective_event_time_only"
    assert result["coverage"]["train_events"] == 100 and result["coverage"]["heldout_events"] == 100
    assert result["coverage"]["point_in_time_rows"] == 0
    assert "historical_point_in_time_availability_unverified" in result["certification"]["deficiencies"]
    assert "authentic_historical_order_books_missing" in result["certification"]["deficiencies"]
    assert result["models"][0]["metrics"]["events"] == 100
    assert result["models"][1]["metrics"]["brier_score"] < result["models"][0]["metrics"]["brier_score"]
    assert all(m["execution_cost_analysis"] is None for m in result["models"])


def test_correlated_legs_and_repeated_snapshots_cannot_reach200_independent_events():
    b = bundle(correlated=True)
    b = b.model_copy(update={"prices": b.prices * 3})
    result = evaluate_bundle(b)
    assert result["coverage"]["independent_verified_events"] == 100
    assert result["coverage"]["forecast_rows"] == 100
    assert result["coverage"]["heldout_events"] == 0
    assert "fewer_than100_independent_heldout_events" in result["certification"]["deficiencies"]


def test_all_metrics_reproducible_and_json_finite(tmp_path):
    b = bundle()
    report = write_report(b, tmp_path / "report.json")
    assert report == evaluate_bundle(b)
    assert report == json.loads((tmp_path / "report.json").read_text())
    reordered = b.model_copy(
        update={"prices": tuple(reversed(b.prices)), "events": tuple(reversed(b.events))}
    )
    assert evaluate_bundle(reordered) == report
    metrics = report["models"][1]["metrics"]
    assert metrics["brier_ci95"] and metrics["log_loss_ci95"]
    assert report["models"][1]["by_category"].keys() == {"A", "B"}


def test_point_in_time_context_model_is_comparison_only_even_if_strong():
    report = evaluate_bundle(bundle(archive=True, books=True, independent=True, fees=True))
    assert report["analysis_mode"] == "point_in_time_archive"
    logistic = next(m for m in report["models"] if m["id"] == "regularized_context_logistic")
    histogram = next(m for m in report["models"] if m["id"] == "histogram_calibration")
    assert logistic["metrics"]["brier_score"] < histogram["metrics"]["brier_score"]
    assert report["recommended_model"] == "regularized_context_logistic"
    assert report["certification"]["status"] == "blocked"
    assert report["certification"]["owner_approval_required"]
    assert histogram["execution_cost_analysis"]["actual_fills"] is None
    assert histogram["execution_cost_analysis"]["modeled_trades"] > 0
    assert histogram["execution_cost_analysis"]["max_drawdown"] >= 0


def test_missing_fees_cannot_produce_transaction_cost_profit():
    report = evaluate_bundle(bundle(archive=True, books=True))
    histogram = report["models"][1]
    assert histogram["execution_cost_analysis"] is None
    assert "point_in_time_fee_provenance_missing" in histogram["reasons"]


def test_future_data_and_contradictory_labels_are_excluded():
    b = bundle()
    future = b.events[0].model_copy(update={"available_at": NOW + timedelta(days=1)})
    report = evaluate_bundle(b.model_copy(update={"events": (future, *b.events[1:])}))
    assert report["coverage"]["independent_verified_events"] == 199
    assert "future_record_unavailable_as_of_bundle" in report["certification"]["deficiencies"]
    contradictory = b.events[0].model_copy(update={"id": "changed", "outcome": 1 - b.events[0].outcome})
    report = evaluate_bundle(b.model_copy(update={"events": (*b.events, contradictory)}))
    assert report["coverage"]["forecast_rows"] == 199
    assert "contradictory_verified_labels" in report["certification"]["deficiencies"]


def test_changed_record_id_prevents_model_fitting():
    b = bundle()
    bad = b.prices[0].model_copy(update={"probability": 0.9})
    report = evaluate_bundle(b.model_copy(update={"prices": (*b.prices, bad)}))
    assert report["coverage"]["forecast_rows"] == 0
    assert "conflicting_record_id" in report["certification"]["deficiencies"]


def test_training_labels_cannot_arrive_after_heldout_decision():
    b = bundle(archive=True)
    late = [e.model_copy(update={"available_at": NOW}) if i < 100 else e for i, e in enumerate(b.events)]
    report = evaluate_bundle(b.model_copy(update={"events": tuple(late)}))
    assert report["coverage"]["train_events"] == 0
    assert report["models"][1]["metrics"] is None


def test_prices_at_or_after_settlement_do_not_become_forecasts():
    b = bundle(1)
    after = b.prices[0].model_copy(update={"timestamp": b.events[0].settlement_at, "available_at": NOW})
    report = evaluate_bundle(b.model_copy(update={"prices": (after,)}))
    assert report["coverage"]["forecast_rows"] == 0


def test_no_advanced_model_without_independent_features():
    report = evaluate_bundle(bundle())
    advanced = report["models"][2]
    assert advanced["status"] == "not_evaluable"
    assert advanced["metrics"] is None
    assert report["recommended_model"] == "histogram_calibration"


def test_persistent_change_requires_separate_forecast_not_automatic_value():
    e = RelationshipEvidence(
        id="change",
        timestamp=NOW,
        available_at=NOW,
        source="test",
        relationship_id="r",
        sample_count=30,
        persistence=3,
        strength=4,
        confidence=0.9,
        qualified=True,
        observation_ids=("o1", "o2"),
    )
    result = persistent_relationship_signal(e, make_book(), None, NOW, 0.02)
    assert not result.qualified and "independent_calibrated_forecast_required" in result.reasons
    result = persistent_relationship_signal(e, make_book(), estimate(ids=("change",)), NOW, 0.02)
    assert result.qualified and not result.activation_eligible


def test_stale_or_future_inputs_cannot_qualify():
    old = make_book(NOW - timedelta(seconds=16))
    assert "stale_book" in independent_forecast_signal(context(), old, estimate(), NOW, 0.02).reasons
    future = context(NOW + timedelta(seconds=1))
    assert "future_context" in independent_forecast_signal(future, make_book(), estimate(), NOW, 0.02).reasons


def test_raw_market_context_is_not_an_independent_forecast():
    c = context(source="https://clob.polymarket.com")
    result = independent_forecast_signal(c, make_book(), estimate(), NOW, 0.02)
    assert not result.qualified and "independent_context_provenance_required" in result.reasons


def test_missing_fee_or_evidence_chain_withholds_forecast():
    assert not independent_forecast_signal(context(), make_book(), estimate(), NOW, None).qualified
    assert (
        "forecast_evidence_chain_mismatch"
        in independent_forecast_signal(context(), make_book(), estimate(ids=()), NOW, 0.02).reasons
    )


def test_correlation_is_not_logical_arbitrage():
    r = MarketRelationship(
        id="r",
        timestamp=NOW,
        available_at=NOW,
        source="test",
        market_ids=("m", "m2"),
        kind="statistical",
        confidence=0.99,
    )
    result = logical_constraint_signal(
        r, [make_book(), make_book(market="m2", token="t2")], NOW, {"t": 0, "t2": 0}
    )
    assert not result.qualified and "correlation_is_not_logical_arbitrage" in result.reasons


def test_reviewed_exhaustive_bundle_has_conditional_value_but_no_authority():
    r = MarketRelationship(
        id="r",
        timestamp=NOW,
        available_at=NOW,
        source="review",
        market_ids=("m", "m2"),
        kind="exhaustive",
        confidence=0.99,
        rule_verified=True,
        rule_description="Controlled complete exclusive payout proof",
    )
    books = [make_book(), make_book(market="m2", token="t2")]
    result = logical_constraint_signal(r, books, NOW, {"t": 0.02, "t2": 0.02}, settlement_reviewed=True)
    assert result.qualified and result.expected_net_value > 0
    assert result.estimated_probability is None and not result.activation_eligible
    assert not logical_constraint_signal(r, books, NOW, {"t": 0.02}, settlement_reviewed=True).qualified
    assert not logical_constraint_signal(
        r, books, NOW, {"t": 0, "t2": 0}, settlement_reviewed=True, quantity=101
    ).qualified


def test_maker_never_invents_queue_or_fills():
    b = make_book(bid=0.3, ask=0.5)
    result = maker_signal(b, NOW, maker_fee_rate=0, adverse_selection_bound=0.01)
    assert not result.qualified and "queue_position_and_fill_model_unvalidated" in result.reasons
    result = maker_signal(
        b,
        NOW,
        maker_fee_rate=0,
        adverse_selection_bound=0.01,
        supported_fill_probability=0.5,
        queue_reference="controlled-queue-study",
    )
    # max spread policy deliberately rejects this .20 book even if modeled edge exists.
    assert not result.qualified and "large_spread" in result.reasons
    result = maker_signal(
        make_book(bid=0.35, ask=0.44),
        NOW,
        maker_fee_rate=0,
        adverse_selection_bound=0.001,
        supported_fill_probability=0.9,
        queue_reference="controlled-queue-study",
    )
    assert result.qualified and not result.activation_eligible


def test_event_repricing_requires_actual_causal_publication_order():
    before = make_book(NOW - timedelta(seconds=3))
    c = context(NOW - timedelta(seconds=2))
    after = make_book(NOW - timedelta(seconds=1))
    forecast = estimate(ids=(c.id, before.id, after.id))
    assert event_repricing_signal(c, before, after, forecast, NOW, 0.02).qualified
    future = c.model_copy(update={"available_at": NOW + timedelta(seconds=1)})
    assert not event_repricing_signal(future, before, after, forecast, NOW, 0.02).qualified


def test_microstructure_imbalance_is_not_terminal_probability():
    books = [make_book(NOW - timedelta(seconds=19 - i), sequence=i + 1) for i in range(20)]
    signal = microstructure_signal(books, NOW)
    assert not signal.qualified and "calibrated_horizon_forecast_required" in signal.reasons
    signal = microstructure_signal(
        books,
        NOW,
        calibrated_up_probability=0.8,
        horizon_validation_ref="controlled-horizon-study",
        mean_up_move=0.1,
        mean_down_move=0.02,
        round_trip_cost=0.01,
    )
    assert signal.qualified and not signal.activation_eligible
    books[-1] = books[-1].model_copy(update={"sequence": 99})
    assert "unordered_or_gapped_source_books" in microstructure_signal(books, NOW).reasons


def test_naive_decision_time_rejects():
    with pytest.raises(ValueError, match="timezone"):
        maker_signal(make_book(), NOW.replace(tzinfo=None))
