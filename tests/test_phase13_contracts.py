"""Controlled contract boundary tests, not external sporting observations."""
from datetime import UTC, datetime, timedelta

import pytest
from neraium_poly.research.phase13.contracts import SourceArtifact, SportsGame, SportsMapping
from pydantic import ValidationError

NOW = datetime(2026, 11, 6, tzinfo=UTC)
SHA = "a" * 64


def test_source_never_backdates_retrieved_evidence():
    fields = {"provider": "fixture", "source_id": "x", "source_url": "https://example.org",
                  "retrieved_at": NOW, "available_at": NOW, "content_sha256": SHA,
                  "raw_path": "fixture.json", "quality": "qualified"}
    assert SourceArtifact(**fields).source_timestamp is None
    for changes in ({"available_at": NOW-timedelta(seconds=1)},
                    {"source_timestamp": NOW+timedelta(seconds=1)},
                    {"retrieved_at": NOW.replace(tzinfo=None)}):
        with pytest.raises(ValidationError):
            SourceArtifact(**{**fields, **changes})


def test_final_game_requires_observed_scores_and_past_start():
    fields = {"provider": "fixture", "game_id": "g", "league": "NFL", "home_id": "a", "away_id": "b",
                  "home_name": "A", "away_name": "B", "starts_at": NOW-timedelta(days=1),
                  "status": "final", "artifact_sha256": SHA, "available_at": NOW,
                  "home_score": 2, "away_score": 1, "result_observed_at": NOW}
    assert SportsGame(**fields).home_score == 2
    for changes in ({"home_id": "b"}, {"home_score": None}, {"result_observed_at": None},
                    {"starts_at": NOW+timedelta(hours=1)}):
        with pytest.raises(ValidationError):
            SportsGame(**{**fields, **changes})


def test_mapping_requires_aware_unique_participants():
    fields = {"event_id": "e", "market_id": "m", "token_id": "t", "game_id": "g", "league": "NFL",
                  "provider": "fixture", "selected_team_id": "a", "opponent_team_id": "b",
                  "event_start": NOW, "rules_sha256": SHA, "mapping_sha256": SHA, "artifact_sha256": SHA}
    assert SportsMapping(**fields).event_start == NOW
    for changes in ({"event_start": NOW.replace(tzinfo=None)}, {"opponent_team_id": "a"},
                    {"token_id": ""}):
        with pytest.raises(ValidationError):
            SportsMapping(**{**fields, **changes})
