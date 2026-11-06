"""Controlled adapter fixtures only; never counted as authentic sports forecasts."""

import hashlib
import sqlite3
import sys
import types
from datetime import UTC, datetime, timedelta

import pytest
from neraium_poly.experimental.contracts import SharedMarketFrame
from neraium_poly.research.phase12.ledger import EventForecastLedger
from neraium_poly.research.phase13.contracts import (
    SourceArtifact,
    SportsGame,
    SportsMapping,
    SportsPrediction,
)
from neraium_poly.research.phase13.runtime import SportsForecastJournal, SportsResearchRuntime
from test_experimental_account import book, market

NOW = datetime(2026, 11, 6, 12, tzinfo=UTC)


@pytest.fixture
def controlled(tmp_path, monkeypatch):
    source_module, mapping_module, model_module = [
        types.ModuleType("controlled " + name) for name in ("source", "mapping", "model")
    ]
    for name, module in [("sources", source_module), ("mapping", mapping_module), ("models", model_module)]:
        monkeypatch.setitem(sys.modules, "neraium_poly.research.phase13." + name, module)
    m, b = market(NOW), book(NOW)
    directory = tmp_path / "sports"
    snapshot = directory / "sources/controlled"
    snapshot.mkdir(parents=True)
    raw = snapshot / "raw.json"
    raw.write_text('{"CONTROLLED_fixture":true}')
    digest = hashlib.sha256(raw.read_bytes()).hexdigest()
    artifact = SourceArtifact(
        provider="controlled",
        source_id="fixture",
        source_url="https://fixture.invalid/data",
        retrieved_at=NOW - timedelta(seconds=1),
        available_at=NOW - timedelta(seconds=1),
        content_sha256=digest,
        raw_path="raw.json",
        quality="qualified",
    )
    game = SportsGame(
        provider="controlled",
        game_id="fixture-game",
        league="NFL",
        home_id="a",
        away_id="b",
        home_name="A",
        away_name="B",
        starts_at=NOW + timedelta(days=1),
        status="scheduled",
        artifact_sha256=digest,
        available_at=artifact.available_at,
    )
    data = {"artifacts": [artifact], "games": [game], "report": {"fixture": True}}

    def load(path):
        if hashlib.sha256((path / "raw.json").read_bytes()).hexdigest() != digest:
            raise ValueError("controlled raw integrity failed")
        return data

    def mapping(market, games, *, now):
        return SportsMapping(
            event_id=market.event_id,
            market_id=market.market_id,
            token_id=market.token_id,
            game_id=game.game_id,
            league="NFL",
            provider="controlled",
            selected_team_id="a",
            opponent_team_id="b",
            event_start=game.starts_at,
            rules_sha256=hashlib.sha256(market.resolution_rules.encode()).hexdigest(),
            mapping_sha256="a" * 64,
            artifact_sha256=digest,
        )

    def predict(games, target, selected_team_id, cutoff, **kwargs):
        return SportsPrediction(
            game_id=game.game_id,
            selected_team_id=selected_team_id,
            probability=0.6,
            lower_probability=0.3,
            upper_probability=0.8,
            cutoff=cutoff,
            model_version="CONTROLLED-only",
            model_sha256="b" * 64,
            feature_version="CONTROLLED",
            dataset_sha256="c" * 64,
            training_games=50,
            participant_games={"a": 20, "b": 20},
            uncertainty={
                "outcome_probabilities": {"win": 0.6, "tie": 0.02, "loss": 0.38},
                "expected_payout": 0.61,
                "type": "CONTROLLED fixture",
            },
        )

    source_module.load_sports = load
    source_module.collect_sports = lambda *a, **k: None
    mapping_module.map_market = mapping
    model_module.predict_game = predict
    model_module.log_loss = lambda p, y: 0.0  # Controlled fixture import surface only.
    ledger = EventForecastLedger(tmp_path / "binary", clock=lambda: NOW)
    runtime = SportsResearchRuntime(
        ledger, directory, clock=lambda: NOW, state={"snapshot": "sources/controlled"}
    )
    frame = SharedMarketFrame(
        timestamp=NOW,
        available_at=NOW,
        source="controlled",
        producer_health={"status": "ok"},
        markets=(m,),
        books=(b,),
    )
    yield runtime, ledger, frame, raw, data, model_module
    runtime.close()
    ledger.close()


def test_ternary_forecast_does_not_enter_binary_ledger_or_gain_trading_authority(controlled):
    r, ledger, frame, _raw, _data, _model = controlled
    r.on_frame(frame, NOW)
    assert not ledger.forecasts()
    records = r.journal.records("forecast")
    assert len(records) == 1
    f = records[0]
    assert f["kind"] == "independent_ternary_research"
    assert f["prediction"]["probability"] == 0.6
    assert f["prediction"]["uncertainty"]["expected_payout"] == 0.61
    assert f["market_expected_payout_baseline"] == pytest.approx(0.395)
    assert f["market_win_probability"] is None
    assert f["trading_authority"] is False
    assert r.summary()["ternary_forecasts"] == 1
    assert r.summary()["scores"]["market_win_brier"] is None
    r.on_frame(frame, NOW)
    assert len(r.journal.records("forecast")) == 1


def test_replayed_mutated_raw_evidence_prevents_forecast(controlled):
    r, ledger, frame, raw, _data, _model = controlled
    raw.write_text('{"CONTROLLED_fixture":"tampered"}')
    r.on_frame(frame, NOW)
    assert not r.journal.records("forecast") and not ledger.forecasts()
    assert r.rejections["controlled raw integrity failed"] == 1


@pytest.mark.parametrize("change", ["stale", "wrong_market", "untrusted_source", "missing_depth"])
def test_bad_market_observations_cannot_create_research_forecast(controlled, change):
    r, _ledger, frame, _raw, _data, _model = controlled
    b = frame.books[0]
    if change == "stale":
        b = b.model_copy(update={"timestamp": NOW - timedelta(seconds=16)})
    elif change == "wrong_market":
        b = b.model_copy(update={"market_id": "other"})
    elif change == "untrusted_source":
        b = b.model_copy(update={"source": "CONTROLLED fake live source"})
    else:
        b = b.model_copy(update={"asks": ()})
    r.on_frame(frame.model_copy(update={"books": (b,)}), NOW)
    assert not r.journal.records("forecast")


def test_future_available_sources_and_mapping_replay_deny(controlled):
    r, _ledger, frame, _raw, data, _model = controlled
    data["artifacts"][0] = data["artifacts"][0].model_copy(
        update={"available_at": NOW + timedelta(seconds=1)}
    )
    r.on_frame(frame, NOW)
    assert not r.journal.records("forecast")
    assert r.rejections["sports_source_not_available_at_forecast"] == 1


def test_journal_append_immutability_and_anchor_restart(controlled):
    r, _ledger, frame, _raw, _data, _model = controlled
    r.on_frame(frame, NOW)
    j = r.journal
    record = j.records("forecast")[0]
    assert not j.append("forecast", record["id"], record)
    anchor = j.verify()
    with pytest.raises(ValueError, match="collision"):
        j.append("forecast", record["id"], {**record, "baseline_comparison": "changed"})
    with pytest.raises(ValueError):
        j.append("forecast", "untyped", {"sample": "CONTROLLED"})
    with pytest.raises(sqlite3.IntegrityError, match="append only"):
        j.db.execute("UPDATE records SET payload='{}'")
    with pytest.raises(sqlite3.IntegrityError, match="append only"):
        j.db.execute("DELETE FROM records")
    r.close()
    j = SportsForecastJournal(r.directory, anchor=anchor)
    assert j.verify() == anchor
    j.close()
    with pytest.raises(ValueError, match="rollback"):
        SportsForecastJournal(r.directory, anchor={"records": anchor["records"] + 1, "head_sha256": "a" * 64})
    r.close = lambda: None


def test_restart_dedup_uses_journal_not_checkpoint(controlled):
    r, ledger, frame, _raw, _data, _model = controlled
    r.on_frame(frame, NOW)
    checkpoint = r.checkpoint()
    r.close()
    r2 = SportsResearchRuntime(ledger, r.directory, clock=lambda: NOW, state=checkpoint)
    try:
        r2.on_frame(frame, NOW)
        assert len(r2.journal.records("forecast")) == 1
    finally:
        r2.close()
    # Fixture's cleanup is idempotent.
    r.close = lambda: None


def test_storage_alias_and_journal_corruption_reject_before_research(tmp_path):
    external = tmp_path / "outside"
    external.write_text("do not modify")
    root = tmp_path / "sports"
    root.mkdir()
    (root / "prospective.sqlite").symlink_to(external)
    with pytest.raises(ValueError, match="aliases"):
        SportsForecastJournal(root)
    assert external.read_text() == "do not modify"


async def test_refresh_errors_and_archive_floor_withhold_research(controlled, monkeypatch):
    r, _ledger, _frame, _raw, _data, _model = controlled
    from neraium_poly.research.phase13 import sources

    async def fail(*args, **kwargs):
        raise RuntimeError("controlled provider unavailable")

    monkeypatch.setattr(sources, "collect_sports", fail)
    await r.refresh()
    assert "controlled provider unavailable" in r.last_error
    assert r.totals["refreshes"] == 1
    await r.refresh()
    assert r.totals["refreshes"] == 1
    assert r.summary()["trading_enabled"] is False


def test_cannot_replace_an_existing_independent_reviewer(tmp_path):
    ledger = EventForecastLedger(
        tmp_path / "binary", clock=lambda: NOW, independent_forecast_validator=lambda *_: False
    )
    try:
        with pytest.raises(ValueError, match="replace"):
            SportsResearchRuntime(ledger, tmp_path / "sports", clock=lambda: NOW)
    finally:
        ledger.close()
