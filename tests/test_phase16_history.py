"""Controlled source records; never authentic research observations or trades."""
from datetime import UTC, datetime, timedelta

import pytest
from neraium_poly.research.phase16.history import CausalHistory
from neraium_poly.research.phase16.relationships import RelationshipHistory

START = datetime(2026, 11, 6, 20, tzinfo=UTC)


def frame(i=0, *, step=20, tokens=2, parent="fixture-parent", left=.3, right=.6):
    at = START + timedelta(seconds=i*step)
    common = {"schema_version": "1.0", "timestamp": at.isoformat(), "available_at": at.isoformat()}
    markets, books, fees = [], [], {}
    for n in range(tokens):
        midpoint = left if n % 2 == 0 else right
        token = f"fixture-token-{n}"
        markets.append({**common, "id": f"fixture-meta-{n}", "source": "https://gamma-api.polymarket.com",
                        "market_id": f"fixture-market-{n}", "event_id": parent, "token_id": token,
                        "question": f"Controlled independent proposition {n}", "outcome": "YES",
                        "probability": midpoint, "status": "active", "resolution_rules": "Fixture rules",
                        "resolution_source": "https://official.example.invalid/fixture"})
        books.append({**common, "id": f"fixture-book-{n}-{i}",
                      "source": "wss://ws-subscriptions-clob.polymarket.com/ws/market",
                      "market_id": f"fixture-market-{n}", "token_id": token, "complete": True,
                      "bids": [{"price": midpoint-.002, "size": 40}],
                      "asks": [{"price": midpoint+.002, "size": 40}]})
        fees[token] = {"fee_rate": .05, "source": "https://clob.polymarket.com/fee-rate",
                       "observed_at": at.isoformat(), "reference": f"fixture-fee-{i}-{n}"}
    return {**common, "id": f"fixture-frame-{i}", "producer_health": {"status": "ok"},
            "markets": markets, "books": books, "fees": fees}, at


def test_causal_depth_context_and_first_matured_quote_are_explicit():
    history = CausalHistory()
    f, now = frame(); result = history.observe(f, now=now)
    assert len(result["accepted"]) == 2 and not result["matured"]
    point = result["accepted"][0]
    assert point["quantity"] == 5 and point["bid_vwap"] == point["bid"]
    assert point["execution_evidence_complete"] and point["fee_observation_valid"]
    assert point["depth_scope"] == "top3_observed" and point["participation"] == .25
    assert point["trading_authority"] is False
    for i in range(1, 4):
        f, now = frame(i); result = history.observe(f, now=now)
    assert len(result["matured"]) == 2
    pair = result["matured"][0]
    assert pair["target_at"] == now.isoformat()
    assert pair["actual_bid"] == pair["unchanged_bid_baseline"]
    assert pair["label_lag_seconds"] == 0 and pair["independent_outcome"] is False
    assert history.summary()["per_token"][0]["matured_labels"] == 1


def test_label_waits_for_source_time_not_receipt_and_never_interpolates():
    history = CausalHistory()
    f, now = frame(0); history.observe(f, now=now)
    f, at = frame(1, step=59)
    result = history.observe(f, now=at+timedelta(seconds=2))
    assert not result["matured"]  # Receipt/cycle aftertarget is not a future source mark.
    f, at = frame(2, step=50)
    result = history.observe(f, now=at)
    assert not result["matured"]  # The original decision's first label is >30s late.
    f, at = frame(3, step=40); history.observe(f, now=at)
    assert history.summary()["rejections"]["horizon_label_missed_not_interpolated"] >= 1


def test_missing_producer_and_fee_evidence_preserves_descriptive_history_only():
    f, now = frame(); f.pop("producer_health"); f.pop("id"); f.pop("fees")
    result = CausalHistory().observe(f, now=now)
    assert len(result["accepted"]) == 2
    for point in result["accepted"]:
        assert point["execution_evidence_complete"] is False and point["fee_rate"] is None
        assert set(point["missing_fields"]) == {"producer_health", "source_frame_identity", "qualified_fee_observation"}


@pytest.mark.parametrize("change,reason", [
    ({"timestamp": (START-timedelta(seconds=16)).isoformat(), "available_at": START.isoformat()}, "stale_book"),
    ({"available_at": (START+timedelta(seconds=1)).isoformat()}, "future_data"),
    ({"market_id": "wrong"}, "book_source_or_market_identity_mismatch"),
    ({"source": "https://untrusted.invalid"}, "book_source_or_market_identity_mismatch"),
    ({"asks": []}, "missing_liquidity"), ({"complete": False}, "incomplete_book"),
])
def test_bad_observations_never_enter_history(change, reason):
    f, now = frame(); f["books"][0].update(change)
    result = CausalHistory().observe(f, now=now)
    assert len(result["accepted"]) == 1
    assert result["rejections"][reason] == 1


def test_duplicate_identity_future_metadata_and_incomplete_context_rejected():
    history = CausalHistory()
    f, now = frame(); history.observe(f, now=now)
    assert not history.observe(f, now=now+timedelta(seconds=1))["accepted"]
    f["books"][0]["bids"][0]["size"] = 41
    result = history.observe(f, now=now+timedelta(seconds=2))
    assert result["rejections"]["changed_book_identity"] == 1
    f, later = frame(1); f["markets"][0]["resolution_source"] = ""
    assert len(history.observe(f, now=later)["accepted"]) == 1
    f, later = frame(2); f["markets"][0]["available_at"] = (later+timedelta(seconds=1)).isoformat()
    assert len(history.observe(f, now=later)["accepted"]) == 1


def test_partial_top3_depth_never_becomes_a_full_liquid_label():
    h = CausalHistory()
    for i in range(4):
        f, now = frame(i); f["books"][0]["bids"][0]["size"] = 10
        result = h.observe(f, now=now)
    assert len(result["matured"]) == 1  # Only the other token has real participatingdepth.
    assert h.points("fixture-token-0")[-1]["bid_vwap"] is None
    assert "top3_participating_depth" in h.points("fixture-token-0")[-1]["missing_fields"]


def test_source_gap_and_rule_changes_start_new_causal_epochs_without_fake_labels():
    h = CausalHistory()
    for i in range(4):
        f, now = frame(i); h.observe(f, now=now)
    f, now = frame(10); result = h.observe(f, now=now)
    assert result["continuity_resets"] == 2 and result["current_observations"] == 2
    assert result["matured_labels"] == 2  # Previous real marks retained as research, not training events.
    assert all(r["matured_labels"] == 0 for r in result["per_token"])
    f, now = frame(11); f["markets"][0]["resolution_rules"] = "New fixture rules"
    result = h.observe(f, now=now)
    assert result["continuity_resets"] == 3 and len(h.points("fixture-token-0")) == 1


def test_restart_is_deterministic_and_corrupt_checkpoint_fails_closed():
    h = CausalHistory()
    for i in range(8):
        f, now = frame(i); h.observe(f, now=now)
    checkpoint = h.checkpoint(); restored = CausalHistory(); restored.restore(checkpoint)
    f, now = frame(8)
    assert restored.observe(f, now=now) == h.observe(f, now=now)
    checkpoint["history"]["fixture-token-0"][0]["bid_vwap"] = .9
    with pytest.raises(ValueError, match="invalid causal"):
        CausalHistory().restore(checkpoint)
    checkpoint = h.checkpoint(); checkpoint["labels"][0]["target_at"] = START.isoformat()
    with pytest.raises(ValueError, match="matured label"):
        CausalHistory().restore(checkpoint)


def test_history_and_label_memory_bound_is_explicit():
    h = CausalHistory(max_tokens=1, history_size=60, max_labels=3)
    for i in range(70):
        f, now = frame(i, tokens=1); result = h.observe(f, now=now)
    assert result["current_observations"] == 60 and result["current_matured_labels"] == 3
    assert result["valid_observations"] == 70 and result["matured_labels"] == 67
    assert result["independent_outcome_events"] == 0
    with pytest.raises(ValueError, match="bounded"):
        CausalHistory(max_tokens=64, history_size=240)


def test_graph_selection_is_causal_and_does_not_invent_logical_constraints():
    h = RelationshipHistory()
    for i in range(4):
        f, now = frame(i); result = h.observe(f, now=now)
        assert result["registered_statistical_candidates"] == int(i == 3)
    assert result["graph_version"] == 1 and result["engine"]["evaluations"] == 1
    assert result["logical_constraints_verified"] == 0 and result["trading_authority"] is False
    assert h.engine.engine.config["warmup"] == 10
    assert h.engine.engine.config["persistence"] == 3 and h.engine.engine.config["persistence_seconds"] == 60


def test_graph_retires_inactive_pairs_and_new_parent_can_take_slot_after_warmup():
    h = RelationshipHistory(max_pairs=1)
    for i in range(4):
        f, now = frame(i); h.observe(f, now=now)
    f, now = frame(4); f["markets"][0]["status"] = "closed"
    result = h.observe(f, now=now)
    assert result["registered_statistical_candidates"] == 0 and result["retirements_total"] == 1
    assert h.retired[0]["reason"] == "contract_inactive_or_ended"
    for i in range(5, 9):
        f, now = frame(i, parent="fixture-new-parent"); result = h.observe(f, now=now)
    assert result["registered_statistical_candidates"] == 1 and result["graph_version"] == 3
    assert next(iter(h.engine.definitions.values()))["parent_event_id"] == "fixture-new-parent"
    assert result["engine"]["evaluations"] >= 2


def test_graph_preserves_short_gaps_but_retires_universe_absence_after120seconds():
    h = RelationshipHistory(max_pairs=1)
    for i in range(4):
        f, now = frame(i); h.observe(f, now=now)
    h.observe({"markets": [], "books": []}, now=now+timedelta(seconds=20))
    assert h.summary()["registered_statistical_candidates"] == 1
    h.observe({"markets": [], "books": []}, now=now+timedelta(seconds=140))
    assert h.summary()["registered_statistical_candidates"] == 0
    assert h.retired[-1]["reason"] == "pair_absent_from_observed_universe_for120s"


def test_graph_restart_and_retirement_hashes_fail_closed_on_mutation():
    h = RelationshipHistory(max_pairs=1)
    for i in range(4):
        f, now = frame(i); h.observe(f, now=now)
    f, now = frame(4); f["markets"][0]["resolution_rules"] = "Changed semantics"
    h.observe(f, now=now)
    checkpoint = h.checkpoint(); other = RelationshipHistory(max_pairs=1); other.restore(checkpoint)
    f, now = frame(5)
    assert other.observe(f, now=now) == h.observe(f, now=now)
    checkpoint["retired"][0]["archived_state"]["definition"]["kind"] = "logical_probability_constraint"
    with pytest.raises(ValueError, match="retirement provenance"):
        RelationshipHistory(max_pairs=1).restore(checkpoint)


def test_duplicate_quote_pair_cannot_create_selection_persistence():
    h = RelationshipHistory()
    f, now = frame()
    for i in range(5):
        h.observe(f, now=now+timedelta(seconds=i))
    assert h.summary()["registered_statistical_candidates"] == 0


def test_exchange_minimum_and_fee_source_are_not_invented_execution_evidence():
    f, now = frame(); f["markets"][0]["min_order_size"] = 10
    f["fees"]["fixture-token-1"]["source"] = "https://untrusted.invalid/fee"
    result = CausalHistory().observe(f, now=now)
    by_token = {p["token_id"]: p for p in result["accepted"]}
    assert "exchange_minimum_quantity" in by_token["fixture-token-0"]["missing_fields"]
    assert by_token["fixture-token-1"]["fee_rate"] is None
    assert not any(p["execution_evidence_complete"] for p in result["accepted"])


def test_future_frame_ended_market_and_changed_checkpoint_authority_withhold():
    h = CausalHistory()
    f, now = frame(); f["available_at"] = (now+timedelta(seconds=1)).isoformat()
    assert h.observe(f, now=now)["current_observations"] == 0
    f, now = frame(1); f["markets"][0]["end_time"] = now.isoformat()
    assert len(h.observe(f, now=now)["accepted"]) == 1
    checkpoint = h.checkpoint(); checkpoint["history"]["fixture-token-1"][0]["trading_authority"] = True
    with pytest.raises(ValueError, match="invalid causal checkpoint point"):
        CausalHistory().restore(checkpoint)


def test_checkpoint_old_label_cannot_claim_availability_after_scoring():
    h = CausalHistory(history_size=60)
    for i in range(70):
        f, now = frame(i, tokens=1); h.observe(f, now=now)
    checkpoint = h.checkpoint()
    # This label's decision has left the bounded current history; label validation
    # must independently enforce its original point-in-time provenance.
    checkpoint["labels"][0]["label"]["available_at"] = (now+timedelta(seconds=1)).isoformat()
    with pytest.raises(ValueError, match="matured label"):
        CausalHistory(history_size=60).restore(checkpoint)


def test_frame_receipt_cannot_precede_its_event_time():
    f, now = frame(); f["timestamp"] = (now+timedelta(seconds=1)).isoformat()
    assert CausalHistory().observe(f, now=now+timedelta(seconds=2))["current_observations"] == 0


def test_graph_reused_identity_and_same_source_time_do_not_add_observations():
    h = RelationshipHistory()
    for i in range(4):
        f, now = frame(i); h.observe(f, now=now)
    baseline = h.engine.engine.states[next(iter(h.engine.definitions))]["observations"]
    f["books"][0]["bids"][0]["size"] = 41
    result = h.observe(f, now=now+timedelta(seconds=1))
    assert result["graph_rejections"]["changed_book_identity"] == 1
    f["books"][0]["id"] = "fixture-new-id-same-source-time"
    result = h.observe(f, now=now+timedelta(seconds=2))
    assert result["graph_rejections"]["non_increasing_source_time"] == 1
    assert h.engine.engine.states[next(iter(h.engine.definitions))]["observations"] == baseline


def test_graph_source_gap_retires_baseline_instead_of_manufacturing_persistence():
    h = RelationshipHistory()
    for i in range(4):
        f, now = frame(i); h.observe(f, now=now)
    f, now = frame(10); result = h.observe(f, now=now)
    assert result["registered_statistical_candidates"] == 0
    assert result["retirements_total"] == 1
    assert h.retired[-1]["reason"] == "source_gap_requires_new_baseline"
