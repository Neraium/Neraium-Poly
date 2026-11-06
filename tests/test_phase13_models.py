from datetime import UTC, datetime, timedelta

import pytest
from neraium_poly.research.phase13.contracts import SportsGame
from neraium_poly.research.phase13.models import (
    historical_diagnostic,
    predict_game,
    training_games,
    verify_prediction,
)

NOW = datetime(2026, 11, 6, 6, tzinfo=UTC)


def corpus(league="NBA"):
    games = []
    for i in range(60):
        games.append(SportsGame(
            provider="fixture-official", game_id=str(i), league=league,
            home_id="A" if i % 2 else "B", away_id="B" if i % 2 else "A",
            home_name="Team A" if i % 2 else "Team B", away_name="Team B" if i % 2 else "Team A",
            starts_at=NOW - timedelta(days=100 - i), status="final",
            home_score=100 if i % 3 else 90, away_score=95,
            result_observed_at=NOW - timedelta(days=1), available_at=NOW - timedelta(days=1),
            artifact_sha256="a" * 64,
        ))
    target = SportsGame(
        provider="fixture-official", game_id="target", league=league,
        home_id="A", away_id="B", home_name="Team A", away_name="Team B",
        starts_at=NOW + timedelta(days=1), status="scheduled",
        artifact_sha256="b" * 64, available_at=NOW - timedelta(seconds=10),
    )
    return games, target


def test_reproducible_model_and_exact_replay():
    games, target = corpus()
    a = predict_game(games, target, "A", NOW)
    b = predict_game(reversed(games), target, "A", NOW)
    assert a == b
    assert verify_prediction(a, games, target) is True
    assert a.lower_probability < a.probability < a.upper_probability
    assert a.uncertainty["confidence_interval"] is False
    assert a.research_only and a.calibration_status == "unvalidated_prospective_research"
    assert not verify_prediction(a.model_copy(update={"probability": 0.99}), games, target)


def test_no_future_results_or_market_input():
    games, target = corpus()
    a = predict_game(games, target, "A", NOW)
    future = games[0].model_copy(update={"game_id": "future-observation", "available_at": NOW + timedelta(days=2)})
    assert predict_game(games + [future], target, "A", NOW) == a
    unsupported = target.model_dump()
    unsupported["market_probability"] = 0.99
    with pytest.raises(ValueError):
        predict_game(games, unsupported, "A", NOW)


def test_forecast_must_precede_start_and_observed_status():
    games, target = corpus()
    with pytest.raises(ValueError, match="upcoming"):
        predict_game(games, target.model_copy(update={"starts_at": NOW}), "A", NOW)
    with pytest.raises(ValueError, match="contradictory"):
        predict_game(games + [target.model_copy(update={"status": "postponed"})], target, "A", NOW)
    with pytest.raises(ValueError, match="upcoming"):
        predict_game(games, target.model_copy(update={"status": "canceled"}), "A", NOW)


def test_nba_frequency_is_independent_and_symmetric():
    games, target = corpus()
    a = predict_game(games, target, "A", NOW, method="frequency")
    b = predict_game(games, target, "B", NOW, method="frequency")
    assert a.probability + b.probability == pytest.approx(1)
    assert a.model_sha256 != predict_game(games, target, "A", NOW).model_sha256
    assert a.uncertainty["outcome_probabilities"] is None


def test_nfl_preserves_ties_unconditional_estimand():
    games, target = corpus("NFL")
    games[0] = games[0].model_copy(update={"home_score": 17, "away_score": 17})
    with pytest.raises(ValueError, match="expected score"):
        predict_game(games, target, "A", NOW)
    p = predict_game(games, target, "A", NOW, method="frequency")
    probabilities = p.uncertainty["outcome_probabilities"]
    assert sum(probabilities.values()) == pytest.approx(1)
    assert probabilities["tie"] > 0
    assert probabilities["win"] == p.probability
    assert p.uncertainty["expected_payout"] == pytest.approx(p.probability + 0.5 * probabilities["tie"])
    assert p.uncertainty["expected_payout_is_not_win_probability"]
    assert p.uncertainty["fractional_tie_contract_market_comparison_supported"] is False
    assert verify_prediction(p, games, target)


def test_duplicate_results_do_not_inflate_and_conflicts_reject():
    games, target = corpus()
    assert len(training_games(games + [games[0]], target, NOW)) == 60
    with pytest.raises(ValueError, match="ambiguous historical"):
        predict_game(games + [games[0].model_copy(update={"home_score": 200})], target, "A", NOW)
    with pytest.raises(ValueError, match="conflicting historical"):
        predict_game(games + [games[0].model_copy(update={"home_id": "C"})], target, "A", NOW)


def test_sample_requirements_and_unsupported_parameters():
    games, target = corpus()
    with pytest.raises(ValueError, match="league training"):
        predict_game(games[:49], target, "A", NOW)
    with pytest.raises(ValueError, match="participant training"):
        predict_game(games, target.model_copy(update={"home_id": "C"}), "C", NOW)
    with pytest.raises(ValueError, match="minimum research"):
        predict_game(games, target, "A", NOW, min_training_games=1)
    with pytest.raises(ValueError, match="bounded training"):
        predict_game(games, target, "A", NOW, max_age_days=3650)
    with pytest.raises(ValueError, match="selected participant"):
        predict_game(games, target, "C", NOW)


def test_available_results_are_not_retrospective_forecast_evidence():
    games, _ = corpus()
    report = historical_diagnostic(games, NOW)
    assert report["observed_final_games"] == 60
    assert report["qualified_historical_forecast_pairs"] == 0
    assert report["brier"] is report["log_loss"] is None
    assert report["certification_authority"] is False
