"""Synthetic diagnostic regression fixtures; never live-market evidence."""

import hashlib
import json
import sqlite3
from datetime import timedelta

import pytest
from neraium_poly.experimental.strategies import ExperimentalStrategyEngine
from neraium_poly.research.phase10_diagnostics import category, cycle_window, frame_quality, historical_audit


def sample(market, book):
    return {
        "id": "controlled-frame",
        "mode": "real_market_data",
        "markets": [market.model_dump(mode="json")],
        "books": [book.model_dump(mode="json")],
    }


def test_source_and_receipt_freshness_are_separate(market, book, now):
    old = book.model_copy(update={"timestamp": now - timedelta(seconds=20)})
    r = frame_quality(
        sample(market, old), [market.token_id], {}, ExperimentalStrategyEngine().checkpoint(), now
    )
    assert r["counts"]["source"].get("fresh_source", 0) == 0
    assert r["counts"]["source"]["fresh_receipt"] == 1
    assert "stale_book" in r["rows"][0]["quality_reasons"]
    assert r["rows"][0]["modeled_net_edge"] is None


def test_unknown_fees_and_unmatured_history_never_make_opportunity(market, book, now):
    r = frame_quality(sample(market, book), [], {}, ExperimentalStrategyEngine().checkpoint(), now)
    assert r["counts"]["source"].get("static_operationally_eligible", 0) == 0
    assert r["counts"]["unselected"]["tokens"] == 1
    assert r["volume_and_historical_liquidity"] is None
    assert r["rows"][0]["fee_rejection"] == "unknown_fee_schedule"
    assert r["rows"][0]["history_rejections"] == ["insufficient_causal_bid_history"]


def test_past_end_and_minlot_exclude_standard_sizing(market, book, now):
    m = market.model_copy(update={"end_time": now - timedelta(seconds=1), "min_order_size": 100})
    r = frame_quality(sample(m, book), [m.token_id], {}, ExperimentalStrategyEngine().checkpoint(), now)
    assert r["counts"]["source"]["past_end"] == 1
    assert not r["rows"][0]["flags"]["metadata_eligible"]
    assert not r["rows"][0]["flags"]["minimum_lot_within_standard_cap"]


def test_no_logical_relationship_inferred_from_complementary_outcome(market, book, now):
    f = sample(market, book)
    f["markets"].append(
        market.model_copy(update={"token_id": "other", "outcome": "NO"}).model_dump(mode="json")
    )
    r = frame_quality(f, [], {}, ExperimentalStrategyEngine().checkpoint(), now)
    assert r["counts"]["source"].get("same_event_yes_peer", 0) == 0


def test_fixed_window_counts_nonexclusive_reasons_without_fake_returns(tmp_path):
    p = tmp_path / "events.sqlite"
    with sqlite3.connect(p) as c:
        c.execute("create table events(kind text,payload text,digest text)")
        for i in range(3):
            c.execute(
                "insert into events values(?,?,?)",
                (
                    "ExperimentalCycle",
                    json.dumps(
                        {
                            "timestamp": str(i),
                            "signal_count": 6,
                            "eligible_count": 0,
                            "rejection_counts": {"stale_book": 6, "unknown_fee_schedule": 6},
                            "representative_rejections": [],
                        }
                    ),
                    "stored-digest",
                ),
            )
    r = cycle_window(p, limit=2, high_water=2)
    assert r["cycles"] == 2 and r["new_deduplicated_signals"] == 12
    assert sum(r["rejection_reason_counts"].values()) == 24
    assert r["last_timestamp"] == "1"
    assert r["false_positive_rate"] is None and r["simulated_execution_return"] is None
    with pytest.raises(ValueError, match="limit"):
        cycle_window(p, limit=2001)
    with sqlite3.connect(p) as c:
        assert c.execute("select count(*) from events").fetchone()[0] == 3


def test_history_hash_mismatch_fails_before_chain_access(tmp_path):
    (tmp_path / "events.jsonl").write_bytes(b"tampered")
    (tmp_path / "manifest.json").write_text(
        json.dumps({"events_sha256": hashlib.sha256(b"original").hexdigest()})
    )
    with pytest.raises(ValueError, match="hash mismatch"):
        historical_audit(tmp_path, tmp_path / "absent")


def test_rejection_classification_preserves_unknowns_for_review():
    assert category("conservative_roundtrip_edge_insufficient") == "MARKET CONDITION"
    assert category("multi_leg_execution_and_hedging_not_supported") == "STRATEGY LIMITATION"
    assert (
        category("independent_context_verified_labels_and_calibration_required") == "CERTIFICATION DEPENDENCY"
    )
    assert category("new_unreviewed_reason") == "UNCLASSIFIED_REQUIRES_REVIEW"


def test_duplicate_books_and_unofficial_identity_are_not_accepted(market, book, now):
    f = sample(market, book)
    f["books"].append(f["books"][0])
    with pytest.raises(ValueError, match="duplicate"):
        frame_quality(f, [], {}, ExperimentalStrategyEngine().checkpoint(), now)
    f = sample(market, book.model_copy(update={"source": "https://example.test"}))
    r = frame_quality(f, [], {}, ExperimentalStrategyEngine().checkpoint(), now)
    assert r["counts"]["source"].get("official_book_identity", 0) == 0
    assert r["counts"]["source"].get("static_operationally_eligible", 0) == 0


def test_causal_baseline_only_scores_available_future_labels(market, now):
    from dataclasses import asdict

    from neraium_poly.experimental.strategies import QuotePoint
    from neraium_poly.research.phase10_diagnostics import forecast_baseline_audit

    engine = ExperimentalStrategyEngine()
    points = [
        QuotePoint(
            f"controlled-{i}",
            (now + timedelta(seconds=10 * i)).isoformat(),
            (now + timedelta(seconds=10 * i + 0.1)).isoformat(),
            0.5,
            0.51,
        )
        for i in range(96)
    ]
    cp = engine.checkpoint()
    cp["history"] = {market.token_id: [asdict(x) for x in points]}
    r = forecast_baseline_audit(cp, [market.model_dump(mode="json")])
    assert r["scored_labels"] > 0
    assert r["model_mae"] == 0 and r["unchanged_bid_mae"] == 0
    assert r["confidence_interval"] is None and r["execution_returns"] is None
    assert r["independently_reviewed_events"] == 0
    assert r["observed_event_ids"] == 1
    for row in r["token_results"][0]["representatives"]:
        assert row["label_available_at"] > row["decision_available_at"]
        assert row["label_source_delay_after_target_seconds"] <= 30
    # An unavailable point earlier in the input prefix invalidates its decisions.
    cp["history"][market.token_id][0]["available_at"] = (now + timedelta(days=1)).isoformat()
    assert forecast_baseline_audit(cp, [market.model_dump(mode="json")])["scored_labels"] == 0
