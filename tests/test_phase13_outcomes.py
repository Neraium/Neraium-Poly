"""Controlled result fixtures; not authentic outcomes or measured forecast skill."""

import hashlib
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from neraium_poly.research.phase12.contracts import VerifiedEventOutcome
from neraium_poly.research.phase12.ledger import content_sha256
from neraium_poly.research.phase13.contracts import SourceArtifact, SportsGame, SportsMapping
from neraium_poly.research.phase13.outcomes import corroborate_sports_outcome, score_ternary_forecast
from test_experimental_account import market

NOW = datetime(2026, 11, 6, 12, tzinfo=UTC)


def records():
    m = market(NOW - timedelta(days=2))
    rules = hashlib.sha256(m.resolution_rules.encode()).hexdigest()
    mapping = SportsMapping(
        event_id=m.event_id,
        market_id=m.market_id,
        token_id=m.token_id,
        game_id="controlled",
        league="NFL",
        provider="controlled",
        selected_team_id="a",
        opponent_team_id="b",
        event_start=NOW - timedelta(days=1),
        rules_sha256=rules,
        mapping_sha256="a" * 64,
        artifact_sha256="b" * 64,
    )
    f = SimpleNamespace(
        id="CONTROLLED-forecast",
        event_id=m.event_id,
        market_id=m.market_id,
        token_id=m.token_id,
        timestamp=NOW - timedelta(days=2),
        resolution_rules_sha256=rules,
    )
    g = SportsGame(
        provider="controlled",
        game_id="controlled",
        league="NFL",
        home_id="a",
        away_id="b",
        home_name="A",
        away_name="B",
        starts_at=mapping.event_start,
        status="final",
        home_score=21,
        away_score=14,
        result_observed_at=NOW,
        available_at=NOW,
        artifact_sha256="c" * 64,
    )
    a = SourceArtifact(
        provider="controlled",
        source_id="CONTROLLED",
        source_url="https://fixture.invalid",
        retrieved_at=NOW,
        available_at=NOW,
        content_sha256="c" * 64,
        raw_path="CONTROLLED",
        quality="qualified",
    )
    o = VerifiedEventOutcome(
        id="CONTROLLED-outcome",
        timestamp=NOW,
        available_at=NOW,
        source="CONTROLLED",
        event_id=m.event_id,
        market_id=m.market_id,
        token_id=m.token_id,
        payout=1,
        resolution_rules_sha256=rules,
        settled_at=NOW - timedelta(hours=12),
        verification_source="CONTROLLED-test-proof",
        verification={"CONTROLLED": True},
        proof_sha256=content_sha256({"CONTROLLED": True}),
    )
    return o, f, m, mapping, g, a


def test_result_requires_both_exchange_settlement_and_matching_external_score():
    o, f, m, mapping, g, a = records()
    result = corroborate_sports_outcome(o, f, m, mapping, [g], [a], now=NOW)
    assert result["accepted"] is True
    assert result["independent_source_is_official_league_api"] is False
    assert result["no_account_settlement_authority"] is True
    bad = o.model_copy(update={"payout": 0})
    assert not corroborate_sports_outcome(bad, f, m, mapping, [g], [a], now=NOW)["accepted"]


@pytest.mark.parametrize("status", ["canceled", "postponed", "in_progress", "unknown", "scheduled"])
def test_nonfinal_results_are_unresolved(status):
    o, f, m, mapping, g, a = records()
    result = corroborate_sports_outcome(
        o, f, m, mapping, [g.model_copy(update={"status": status})], [a], now=NOW
    )
    assert not result["accepted"]
    assert "external_result_" + status in result["reasons"]


def test_corrected_duplicate_results_rescheduling_ties_and_rule_changes_withhold():
    o, f, m, mapping, g, a = records()
    for games, market_record in [
        ([g, g.model_copy(update={"home_score": 7})], m),
        ([g.model_copy(update={"starts_at": g.starts_at + timedelta(hours=1)})], m),
        ([g.model_copy(update={"away_score": g.home_score})], m),
        ([g], m.model_copy(update={"resolution_rules": "changed"})),
    ]:
        assert not corroborate_sports_outcome(o, f, market_record, mapping, games, [a], now=NOW)["accepted"]


def test_ternary_descriptive_score_keeps_market_win_metric_unavailable():
    _o, _f, _m, _mapping, g, _a = records()
    scores = score_ternary_forecast({"win": 0.6, "tie": 0.02, "loss": 0.38}, g, "a")
    assert scores["actual"] == "win"
    assert scores["multiclass_brier"] == pytest.approx(0.3048)
    assert scores["market_win_brier"] is None
    with pytest.raises(ValueError, match="normalized"):
        score_ternary_forecast({"win": 0.6, "tie": 0.02, "loss": 0.7}, g, "a")
