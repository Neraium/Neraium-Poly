"""Controlled service integration; fixture results are never market evidence."""
from datetime import datetime, timedelta

import pytest
from neraium_poly.research.phase12.contracts import VerifiedEventOutcome
from neraium_poly.research.phase12.ledger import content_sha256
from test_phase13_runtime import NOW, controlled  # noqa: F401


async def test_async_result_receipt_uses_post_acquisition_clock(controlled, monkeypatch):  # noqa: F811
    r, _ledger, frame, _raw, original_data, _model = controlled
    r.on_frame(frame, NOW)
    saved = r.journal.records("forecast")[0]
    game = original_data["games"][0]
    clock = [game.starts_at + timedelta(hours=7)]
    r.clock = lambda: clock[0]
    artifact = original_data["artifacts"][0].model_copy(update={"retrieved_at": clock[0], "available_at": clock[0]})
    result = game.model_copy(update={"status": "final", "home_score": 2, "away_score": 1,
                                    "available_at": clock[0], "result_observed_at": clock[0]})
    latest = {"artifacts": [artifact], "games": [result], "report": {"fixture": True}}
    r.data, r.snapshot = latest, "sources/latest"
    monkeypatch.setattr(r, "_load", lambda path: original_data if path == "sources/controlled" else latest)
    monkeypatch.setattr(r, "_replay_outcome", lambda record: True)  # Transport replay covered separately.

    async def acquire(reference, market, output):
        assert reference.original_record_sha256 == content_sha256(saved)
        clock[0] += timedelta(seconds=2)
        proof = {"CONTROLLED": True}
        return VerifiedEventOutcome(id="controlled-outcome", timestamp=game.starts_at + timedelta(hours=4),
            available_at=clock[0], source="CONTROLLED fixture", event_id=reference.event_id,
            market_id=reference.market_id, token_id=reference.token_id, payout=1,
            resolution_rules_sha256=reference.resolution_rules_sha256,
            settled_at=game.starts_at + timedelta(hours=4), verification_source="CONTROLLED",
            proof_sha256=content_sha256(proof), verification=proof)

    monkeypatch.setattr("neraium_poly.research.phase12.outcome_collector.acquire_verified_outcome", acquire)
    monkeypatch.setattr("neraium_poly.research.phase12.outcome_collector.verify_collected_outcome", lambda *a: True)
    await r.resolve_pending()
    outcomes = r.journal.records("outcome")
    assert len(outcomes) == 1
    assert outcomes[0]["corroboration"]["accepted"] is True
    assert datetime.fromisoformat(outcomes[0]["timestamp"]) == clock[0]
    assert r.journal.records("forecast")[0] == saved


async def test_paper_archive_stop_does_not_grant_orders_or_stop_separate_research(tmp_path, monkeypatch):
    from test_experimental_runtime import runtime

    r, _clock, _feed = runtime(tmp_path, NOW)
    seen = []
    try:
        monkeypatch.setattr(r, "_budget_ok", lambda: False)
        monkeypatch.setattr(r.event_intelligence, "on_sports_frame", lambda frame, now: seen.append(frame))
        await r.cycle()
        assert seen and seen[0].producer_health["status"] == "ok"
        assert r.account.snapshot(now=NOW)["kill_switch"] is True
        state = r.state()
        assert state["cash"] == 500 and not state["orders"] and not state["positions"]
        assert not r.event_intelligence.ledger.forecasts()
    finally:
        await r.close()


def test_journal_payload_identity_and_source_model_replay(controlled):  # noqa: F811
    r, _ledger, frame, raw, _data, _model = controlled
    r.on_frame(frame, NOW)
    record = r.journal.records("forecast")[0]
    assert r.replay_ternary_forecast(record) is True
    with pytest.raises(ValueError, match="identity"):
        r.journal.append("forecast", "a" * 64, record)
    raw.write_text('"CONTROLLED tampered"')
    assert r.replay_ternary_forecast(record) is False


def test_recovery_rejects_hash_consistent_but_untyped_tail(controlled):  # noqa: F811
    r, _ledger, _frame, _raw, _data, _model = controlled
    value = {"CONTROLLED": "invalid forecast type"}
    digest = content_sha256(value)
    r.journal.db.execute("INSERT INTO records(kind,id,payload,digest,previous,chain) VALUES(?,?,?,?,?,?)",
                        ("forecast", "f", '{"CONTROLLED":"invalid forecast type"}', digest, None,
                         content_sha256([None, "forecast", "f", digest])))
    with pytest.raises(ValueError):
        r.journal.verify()


def test_outcome_replay_binds_exact_publisher_game_record(controlled, monkeypatch):  # noqa: F811
    from neraium_poly.research.phase13.contracts import SportsMapping
    from neraium_poly.research.phase13.outcomes import corroborate_sports_outcome, score_ternary_forecast
    from neraium_poly.research.phase13.runtime import SportsSettlementReference
    r, _ledger, frame, _raw, original, _model = controlled
    r.on_frame(frame, NOW)
    saved = r.journal.records("forecast")[0]
    mapping = SportsMapping.model_validate(saved["mapping"])
    at = mapping.event_start + timedelta(hours=7)
    r.clock = lambda: at
    game = original["games"][0].model_copy(update={"status": "final", "home_score": 2, "away_score": 1,
                                                  "available_at": at, "result_observed_at": at})
    artifact = original["artifacts"][0].model_copy(update={"available_at": at, "retrieved_at": at})
    latest = {"games": [game], "artifacts": [artifact]}
    r.data, r.snapshot = latest, "sources/latest"
    monkeypatch.setattr(r, "_load", lambda path: original if path == "sources/controlled" else latest)
    monkeypatch.setattr("neraium_poly.research.phase12.outcome_collector.verify_collected_outcome", lambda *a: True)
    reference = SportsSettlementReference(id=saved["id"], original_record_sha256=content_sha256(saved),
        event_id=mapping.event_id, market_id=mapping.market_id, token_id=mapping.token_id,
        timestamp=NOW, evidence_cutoff=NOW, resolution_rules_sha256=mapping.rules_sha256)
    proof = {"CONTROLLED": True}
    outcome = VerifiedEventOutcome(id="controlled-result", timestamp=at, available_at=at,
        source="CONTROLLED", event_id=mapping.event_id, market_id=mapping.market_id,
        token_id=mapping.token_id, payout=1, settled_at=at, resolution_rules_sha256=mapping.rules_sha256,
        verification_source="CONTROLLED", verification=proof, proof_sha256=content_sha256(proof))
    check = corroborate_sports_outcome(outcome, reference, frame.markets[0], mapping, [game], [artifact], now=at)
    record = {"forecast_id": saved["id"], "timestamp": at.isoformat(), "sports_result": game.model_dump(mode="json"),
              "current_source_snapshot": "sources/latest", "exchange_outcome": outcome.model_dump(mode="json"),
              "corroboration": check, "descriptive_scores": score_ternary_forecast(
                  saved["prediction"]["uncertainty"]["outcome_probabilities"], game, mapping.selected_team_id)}
    assert r._replay_outcome(record) is True
    record["sports_result"]["home_score"] = 3  # Same winner, wrong authenticated source record.
    assert r._replay_outcome(record) is False
