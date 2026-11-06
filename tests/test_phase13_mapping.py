"""Exact deterministic mapping fixture tests, never live observations."""

from datetime import UTC, datetime, timedelta

import pytest
from neraium_poly.contracts import MarketSnapshot
from neraium_poly.research.phase13.contracts import SportsGame
from neraium_poly.research.phase13.mapping import map_market

NOW = datetime(2026, 11, 6, 6, tzinfo=UTC)
START = datetime(2026, 11, 8, 18, tzinfo=UTC)
RULES = """In the upcoming NFL football game between Lions and Dolphins, scheduled for November 8 at 1:00PM ET:
This market will resolve to "Lions" if Lions win the game.
This market will resolve to "Dolphins" if Dolphins win the game.
Overtime is included if played.
If the game ends in a tie, this market will resolve 50-50.
If the game is postponed, this market will remain open until the game has been completed.
If the game is canceled entirely, with no make-up game, this market will resolve 50-50."""


def market(**kw):
    return MarketSnapshot(
        id="fixture",
        timestamp=NOW,
        available_at=NOW,
        source="https://gamma-api.polymarket.com",
        exchange="polymarket",
        market_id="m",
        event_id="parent",
        question="Lions vs. Dolphins",
        token_id="token",
        outcome="Lions",
        probability=0.7,
        status="active",
        resolution_rules=RULES,
        resolution_source="https://www.nfl.com/scores",
        end_time=START,
    ).model_copy(update=kw)


def game(**kw):
    return SportsGame(
        provider="nflverse/nflverse-data",
        game_id="2026_09_DET_MIA",
        league="NFL",
        home_id="MIA",
        away_id="DET",
        home_name="Miami Dolphins",
        away_name="Detroit Lions",
        starts_at=START,
        status="scheduled",
        artifact_sha256="a" * 64,
        available_at=NOW,
        **kw,
    )


def test_exact_mapping_and_complement_share_event():
    left = map_market(market(), [game()], now=NOW)
    right = map_market(market(outcome="Dolphins", token_id="other"), [game()], now=NOW)
    assert left.game_id == right.game_id and left.selected_team_id == "DET"
    assert right.selected_team_id == "MIA" and left.mapping_sha256 != right.mapping_sha256
    assert map_market(market(), [game()], now=NOW) == left


@pytest.mark.parametrize(
    "change,reason",
    [
        ({"question": "Spread: Lions (-3.5)"}, "unsupported_contract"),
        ({"outcome": "Yes"}, "ambiguous_participant"),
        ({"question": "Detroit vs. Miami"}, "ambiguous_participant"),
        (
            {"resolution_rules": RULES.replace("Overtime is included if played.", "Regulation only.")},
            "resolution_rules",
        ),
        ({"resolution_rules": RULES.replace('"Lions" if Lions', '"Dolphins" if Lions')}, "resolution_rules"),
        ({"end_time": START + timedelta(hours=1)}, "schedule_mismatch"),
        ({"resolution_source": "https://www.nba.com/"}, "unsupported_league"),
        ({"available_at": NOW + timedelta(seconds=1)}, "noncausal"),
    ],
)
def test_quarantines_unsupported_or_ambiguous_contracts(change, reason):
    with pytest.raises(ValueError, match=reason):
        map_market(market(**change), [game()], now=NOW)


def test_duplicate_schedule_postponement_and_started_event():
    with pytest.raises(ValueError, match="ambiguous_schedule"):
        map_market(market(), [game(), game()], now=NOW)
    postponed = game().model_copy(update={"status": "postponed"})
    with pytest.raises(ValueError, match="non_scheduled"):
        map_market(market(), [postponed], now=NOW)
    with pytest.raises(ValueError, match="already_started"):
        map_market(market(), [game()], now=START)


def test_stale_schedule_withholds():
    stale = game().model_copy(update={"available_at": NOW - timedelta(days=2)})
    with pytest.raises(ValueError, match="stale"):
        map_market(market(), [stale], now=NOW)
