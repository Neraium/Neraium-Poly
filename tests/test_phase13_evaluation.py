"""Scoring fixtures only, never authentic prospective market results."""

from datetime import timedelta

import pytest
from neraium_poly.contracts import OrderBookSnapshot, PriceLevel
from neraium_poly.research.phase12.contracts import EventForecast, VerifiedEventOutcome
from neraium_poly.research.phase12.ledger import content_sha256
from neraium_poly.research.phase13.contracts import SportsMapping
from neraium_poly.research.phase13.evaluation import (
    evaluate_forecasts,
    evaluate_sports_forecasts,
    score_sports_prediction,
)
from neraium_poly.research.phase13.models import predict_game
from test_phase13_models import NOW, corpus


def binary_pair(i=0):
    f = EventForecast(
        id=f"f{i}", timestamp=NOW, available_at=NOW, source="CONTROLLED FIXTURE",
        event_id=f"e{i}", market_id=f"m{i}", token_id=f"t{i}", dependency_group=f"group{i}",
        independence_reviewed=True, category="Sports", kind="independent_model",
        probability=0.7, market_probability=0.5, evidence_cutoff=NOW,
        model_version="fixture-v1", feature_version="fixture-v1", model_sha256="a" * 64,
        dataset_sha256="b" * 64, resolution_rules_sha256="c" * 64,
        evidence_ids=("fixture",), uncertainty={"type": "fixture"},
        lower_probability=0.2, upper_probability=0.9, horizon_seconds=86400,
    )
    proof = {"fixture": True}
    o = VerifiedEventOutcome(
        id=f"o{i}", timestamp=NOW + timedelta(days=2), available_at=NOW + timedelta(days=3),
        source="CONTROLLED FIXTURE", event_id=f.event_id, market_id=f.market_id, token_id=f.token_id,
        payout=1, resolution_rules_sha256=f.resolution_rules_sha256, settled_at=NOW + timedelta(days=2),
        verification_source="CONTROLLED FIXTURE", proof_sha256=content_sha256(proof), verification=proof,
    )
    return f, o


def ternary_pair():
    games, target = corpus("NFL")
    p = predict_game(games, target, "A", NOW, method="frequency")
    mapping = SportsMapping(
        event_id="e", market_id="m", token_id="t", game_id=target.game_id, league="NFL",
        provider=target.provider, selected_team_id="A", opponent_team_id="B", event_start=target.starts_at,
        rules_sha256="c" * 64, mapping_sha256="d" * 64, artifact_sha256=target.artifact_sha256,
    )
    book = OrderBookSnapshot(
        id="b", timestamp=NOW, available_at=NOW, source="https://clob.polymarket.com",
        market_id="m", token_id="t", bids=(PriceLevel(price=0.49, size=100),),
        asks=(PriceLevel(price=0.51, size=100),),
    )
    result = target.model_copy(update={
        "status": "final", "home_score": 20, "away_score": 17,
        "result_observed_at": NOW + timedelta(days=2), "available_at": NOW + timedelta(days=2),
    })
    _, exchange = binary_pair()
    exchange = exchange.model_copy(update={"event_id": "e", "market_id": "m", "token_id": "t"})
    record = {"id": "f", "timestamp": NOW.isoformat(), "prediction": p.model_dump(mode="json"),
              "mapping": mapping.model_dump(mode="json"), "book": book.model_dump(mode="json"),
              "market_expected_payout_baseline": 0.5, "independence_reviewed": False,
              "dependency_group": "game-target"}
    outcome = {"forecast_id": "f", "sports_result": result.model_dump(mode="json"),
               "exchange_outcome": exchange.model_dump(mode="json")}
    return record, outcome, p, result


def test_binary_callbacks_deny_default_and_one_event_is_not_skill():
    f, o = binary_pair()
    blocked = evaluate_forecasts([f], [o])
    assert not blocked["models"]
    accepted = evaluate_forecasts([f], [o], outcome_validator=lambda _: True,
                                  independence_validator=lambda _: True)
    model = accepted["models"][0]
    assert model["metrics"]["brier"] is None
    assert model["descriptive_paired_scores"]["brier"] == pytest.approx(0.09)
    assert model["descriptive_paired_scores"]["market_brier"] == pytest.approx(0.25)
    assert model["paired_brier_difference_95_bound"] is None


def test_binary_event_dedup_and_timestamp_pairing():
    f, o = binary_pair()
    later = f.model_copy(update={"id": "later", "timestamp": NOW + timedelta(hours=1),
                                 "available_at": NOW + timedelta(hours=1),
                                 "probability": 0.9, "market_probability": 0.99})
    report = evaluate_forecasts([later, f], [o], outcome_validator=lambda _: True,
                                independence_validator=lambda _: True)
    assert report["models"][0]["independent_event_groups"] == 1
    assert report["models"][0]["descriptive_paired_scores"]["market_brier"] == 0.25
    assert report["rejections"]["repeated_forecast_or_correlated_event_group"] == 1


def test_binary_rejects_ternary_estimand_and_future_label():
    f, o = binary_pair()
    f = f.model_copy(update={"uncertainty": {"fractional_tie_contract_market_comparison_supported": False}})
    report = evaluate_forecasts([f], [o], outcome_validator=lambda _: True, independence_validator=lambda _: True)
    assert report["rejections"]["unmatched_win_probability_and_fractional_payout_estimands"] == 1
    f, _ = binary_pair()
    o = o.model_copy(update={"settled_at": NOW})
    report = evaluate_forecasts([f], [o], outcome_validator=lambda _: True, independence_validator=lambda _: True)
    assert report["rejections"]["noncausal_or_mismatched_outcome"] == 1


def test_binary_sufficient_events_have_bounded_paired_comparison():
    pairs = [binary_pair(i) for i in range(20)]
    report = evaluate_forecasts([f for f, _ in pairs], [o for _, o in pairs],
                                outcome_validator=lambda _: True, independence_validator=lambda _: True)
    model = report["models"][0]
    assert model["metrics"]["count"] == 20
    assert model["paired_brier_difference"] == pytest.approx(-0.16)
    assert model["paired_brier_difference_95_bound"][0] <= -0.16 <= model["paired_brier_difference_95_bound"][1]
    assert model["superior_forecasting_evidence"] is False
    assert model["executable_trading_advantage"] is None


def test_ternary_score_does_not_invent_market_probability_distribution():
    _, _, p, result = ternary_pair()
    scores = score_sports_prediction(p, result, market_expected_payout=0.5)
    assert scores["actual"] == "win"
    assert scores["market_multiclass_brier"] is scores["market_win_brier"] is None
    assert scores["market_expected_payout_mse"] == 0.25
    tie = result.model_copy(update={"home_score": 17})
    tied = score_sports_prediction(p, tie, market_expected_payout=0.5)
    assert tied["actual"] == "tie" and tied["actual_fractional_payout"] == 0.5
    assert tied["market_expected_payout_mse"] == 0


def test_ternary_evaluation_proof_and_group_gates():
    record, result, _, _ = ternary_pair()
    blocked = evaluate_sports_forecasts([record], [result])
    assert blocked["matched_verified_forecasts"] == 0
    report = evaluate_sports_forecasts([record], [result], result_validator=lambda _: True)
    assert report["matched_verified_forecasts"] == 1
    assert not report["models"]
    assert report["rejections"]["sports_event_independence_not_reviewed"] == 1
    record["independence_reviewed"] = True
    report = evaluate_sports_forecasts([record], [result], result_validator=lambda _: True,
                                       independence_validator=lambda _: True)
    assert report["models"][0]["independent_event_groups"] == 1
    assert report["models"][0]["multiclass_brier"] is None
    assert report["models"][0]["paired_expected_payout_mse_difference_95_bound"] is None


def test_ternary_market_baseline_is_original_book_and_tie_unresolved():
    record, result, _, final = ternary_pair()
    record["market_expected_payout_baseline"] = 0.7
    report = evaluate_sports_forecasts([record], [result], result_validator=lambda _: True)
    assert report["rejections"]["original_book_midpoint_baseline_mismatch"] == 1
    record["market_expected_payout_baseline"] = 0.5
    result["sports_result"] = final.model_copy(update={"home_score": 17}).model_dump(mode="json")
    report = evaluate_sports_forecasts([record], [result], result_validator=lambda _: True)
    assert report["rejections"]["fractional_or_conflicting_exchange_settlement_unresolved"] == 1
