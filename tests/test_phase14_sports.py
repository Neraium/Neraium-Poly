"""Controlled projection fixtures; never new genuine forecasts or research results."""
from copy import deepcopy
from datetime import UTC, datetime, timedelta

import pytest
from neraium_poly.research.phase12.ledger import content_sha256
from neraium_poly.research.phase13.contracts import SportsMapping, SportsPrediction
from neraium_poly.research.phase13.runtime import TernarySportsForecast
from neraium_poly.research.phase14.sports import project_sports_forecast
from test_experimental_account import book, market

NOW = datetime(2026, 11, 6, 12, tzinfo=UTC)


def legacy():
    import hashlib
    m, b = market(NOW), book(NOW)
    rules = hashlib.sha256(m.resolution_rules.encode()).hexdigest()
    mapping = SportsMapping(event_id=m.event_id, market_id=m.market_id, token_id=m.token_id,
        game_id="CONTROLLED_GAME", league="NFL", provider="CONTROLLED", selected_team_id="a",
        opponent_team_id="b", event_start=NOW+timedelta(days=1), rules_sha256=rules,
        mapping_sha256="a"*64, artifact_sha256="b"*64)
    prediction = SportsPrediction(game_id=mapping.game_id, selected_team_id="a", probability=.6,
        lower_probability=.3, upper_probability=.8, cutoff=NOW, model_version="CONTROLLED_v1",
        model_sha256="c"*64, feature_version="CONTROLLED_features", dataset_sha256="d"*64,
        training_games=50, participant_games={"a":20,"b":20}, uncertainty={
            "outcome_probabilities":{"win":.6,"tie":.02,"loss":.38}, "expected_payout":.61,
            "confidence_interval":False, "CONTROLLED_fixture":True})
    return TernarySportsForecast(id="e"*64, kind="independent_ternary_research", timestamp=NOW,
        evidence_cutoff=NOW, mapping=mapping, prediction=prediction, market=m, book=b,
        snapshot="sources/CONTROLLED", source_dataset_sha256="f"*64,
        market_expected_payout_baseline=(b.bids[0].price+b.asks[0].price)/2,
        baseline_comparison="Expected payout, not Pwin", dependency_group="CONTROLLED_group").model_dump(mode="json")


def test_projection_preserves_original_identity_times_probabilities_and_source_references():
    record = legacy()
    before = deepcopy(record)
    projected = project_sports_forecast(record)
    f = projected["forecast"]
    assert projected["projection_only"] is True and projected["count_as_new_forecast"] is False
    assert projected["admissible_to_new_journal"] is False and projected["source_integrity_replayed"] is False
    assert record == before and projected["original_record_sha256"] == content_sha256(record)
    assert f.id == record["id"] and f.domain == "sports"
    assert f.timestamp == f.available_at == f.evidence_cutoff == NOW
    assert f.probability is None and f.probability_semantics == "outcome_distribution"
    assert f.outcome_probabilities == {"win":.6,"tie":.02,"loss":.38}
    assert f.uncertainty == record["prediction"]["uncertainty"]
    assert f.evidence_ids == (record["source_dataset_sha256"],)
    assert f.model_sha256 == record["prediction"]["model_sha256"]
    assert f.rules_sha256 == record["mapping"]["rules_sha256"]
    assert f.contemporaneous_market["book"] == record["book"]
    assert f.contemporaneous_market["market"] == record["market"]
    assert f.contemporaneous_market["market_win_probability"] is None
    assert f.trading_authority is f.certification_authority is False


def test_projection_detaches_mutable_view_from_append_only_original():
    record = legacy()
    projected = project_sports_forecast(record)
    projected["forecast"].uncertainty["CONTROLLED_fixture"] = "view-only mutation"
    projected["forecast"].outcome_probabilities["win"] = .7
    assert record["prediction"]["uncertainty"]["CONTROLLED_fixture"] is True
    assert record["prediction"]["uncertainty"]["outcome_probabilities"]["win"] == .6


@pytest.mark.parametrize("change", ["future_quote", "wrong_rules", "missing_depth", "vector_probability_mismatch"])
def test_inconsistent_original_fails_schema_projection(change):
    record = legacy()
    if change == "future_quote":
        record["book"]["timestamp"] = (NOW+timedelta(seconds=1)).isoformat()
    elif change == "wrong_rules":
        record["mapping"]["rules_sha256"] = "0"*64
    elif change == "missing_depth":
        record["book"]["bids"] = []
    else:
        record["prediction"]["probability"] = .7
    with pytest.raises(ValueError):
        project_sports_forecast(record)


def test_model_copy_cannot_bypass_full_original_validation():
    original = TernarySportsForecast.model_validate(legacy())
    with pytest.raises(ValueError):
        project_sports_forecast(original.model_copy(update={"market_expected_payout_baseline":.99}))
