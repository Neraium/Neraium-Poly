"""Controlled strategy fixtures; these are never real-market performance evidence."""

from copy import deepcopy
from datetime import UTC, datetime, timedelta

import pytest
from neraium_poly.contracts import MarketSnapshot, OrderBookSnapshot, PriceLevel
from neraium_poly.experimental.contracts import SharedMarketFrame
from neraium_poly.experimental.strategies import ExperimentalStrategyEngine

START = datetime(2026, 1, 1, tzinfo=UTC)


def frame(
    i, bid=0.6, *, fee=True, source="https://clob.polymarket.com", token="t1", market="m1", metadata=None
):
    now = START + timedelta(seconds=i * 10)
    book = OrderBookSnapshot(
        id=f"controlled-book-{token}-{i}",
        timestamp=now,
        available_at=now,
        source=source,
        market_id=market,
        token_id=token,
        bids=(PriceLevel(price=bid, size=100),),
        asks=(PriceLevel(price=bid + 0.01, size=100),),
    )
    snapshot = MarketSnapshot(
        id=f"controlled-market-{token}-{i}",
        timestamp=now,
        available_at=now,
        source="https://gamma-api.polymarket.com",
        market_id=market,
        event_id="e1",
        token_id=token,
        probability=0.99,
        question="Controlled test fixture?",
        outcome="Yes",
        status="active",
        resolution_rules="Controlled fixture rules",
        resolution_source="https://example.test/controlled-oracle",
    )
    if metadata:
        snapshot = snapshot.model_copy(update=metadata)
    fees = (
        {
            token: {
                "fee_rate": 0.02,
                "observed_at": now.isoformat(),
                "source": "https://clob.polymarket.com/clob-markets/test",
            }
        }
        if fee
        else {}
    )
    return SharedMarketFrame(
        id=f"controlled-frame-{token}-{i}",
        timestamp=now,
        available_at=now,
        source="controlled-test-producer",
        producer_health={"status": "ok"},
        markets=(snapshot,),
        books=(book,),
        fees=fees,
    ), now


def warm(engine, n=80, **kw):
    for i in range(n):
        f, now = frame(i, **kw)
        engine.evaluate_frame(f, now)


def test_six_registered_candidates_are_explicitly_unvalidated_and_no_forced_trade():
    engine = ExperimentalStrategyEngine()
    f, now = frame(0)
    signals = engine.evaluate_frame(f, now)
    assert len(signals) == 6 and not any(s.eligible for s in signals)
    assert all(s.validation_status == "unvalidated" and s.account_id == "experimental-paper" for s in signals)
    assert engine.status()["certified_approval_authority"] is False
    assert all(s.uncertainty and s.hypothesis and s.evidence_ids for s in signals)


def test_measured_prior_horizon_model_can_qualify_dislocation_without_claiming_calibration():
    engine = ExperimentalStrategyEngine(enabled=["short_horizon"])
    warm(engine)
    f, now = frame(80, bid=0.45)
    (signal,) = engine.evaluate_frame(f, now)
    assert signal.eligible and signal.forecast_value == 0.6
    assert signal.lower_value == pytest.approx(0.59) and signal.upper_value == pytest.approx(0.61)
    assert signal.estimated_net_edge == pytest.approx(0.59 * 0.98 - 0.46 * 1.02 - 0.02)
    assert signal.valuation_kind == "horizon_mark"
    assert signal.diagnostics["matured_errors"] >= 20
    assert signal.diagnostics["fee_reference"].startswith("https://clob.polymarket.com/")
    assert "controlled-book-t1-80" in signal.evidence_ids
    assert "terminal" in signal.assumptions[0]


def test_flat_prices_do_not_clear_roundtrip_costs():
    engine = ExperimentalStrategyEngine(enabled=["short_horizon"])
    warm(engine)
    f, now = frame(80)
    (signal,) = engine.evaluate_frame(f, now)
    assert not signal.eligible and "conservative_roundtrip_edge_insufficient" in signal.reasons


@pytest.mark.parametrize(
    "change,reason",
    [
        ({"fee": False}, "unknown_fee_schedule"),
        ({"source": "publisher-captured-at"}, "unverified_public_book_source"),
        ({"metadata": {"resolution_source": ""}}, "unsupported_resolution_rules"),
    ],
)
def test_unsupported_inputs_reject(change, reason):
    engine = ExperimentalStrategyEngine(enabled=["short_horizon"])
    warm(engine)
    f, now = frame(80, bid=0.45, **change)
    (signal,) = engine.evaluate_frame(f, now)
    assert not signal.eligible and reason in signal.reasons


def test_stale_future_and_incomplete_books_reject():
    for kind in ("stale", "future", "incomplete"):
        engine = ExperimentalStrategyEngine(enabled=["short_horizon"])
        warm(engine)
        f, now = frame(80, bid=0.45)
        if kind == "stale":
            now += timedelta(seconds=16)
        elif kind == "future":
            now -= timedelta(seconds=1)
        else:
            f = f.model_copy(update={"books": (f.books[0].model_copy(update={"complete": False}),)})
        (signal,) = engine.evaluate_frame(f, now)
        assert not signal.eligible
        assert any(r in signal.reasons for r in ("stale_book", "future_data", "incomplete_book"))


def test_unknown_or_spoofed_fee_and_unverified_zero_are_not_silently_used():
    for fee in ({"fee_rate": False}, {"fee_rate": 0.01, "source": "https://clob.polymarket.com.evil.test"}):
        engine = ExperimentalStrategyEngine(enabled=["short_horizon"])
        f, now = frame(0)
        raw = dict(f.fees["t1"])
        raw.update(fee)
        f = f.model_copy(update={"fees": {"t1": raw}})
        (signal,) = engine.evaluate_frame(f, now)
        assert not signal.eligible and "unknown_or_stale_fee_schedule" in signal.reasons


def test_replay_duplicate_and_restart_cannot_inflate_observations_or_signals():
    engine = ExperimentalStrategyEngine(enabled=["short_horizon"])
    warm(engine)
    f, now = frame(80, bid=0.45)
    first = engine.evaluate_frame(f, now)
    assert len(first) == 1
    assert engine.evaluate_frame(f, now) == []
    restored = ExperimentalStrategyEngine(enabled=["short_horizon"])
    restored.restore(engine.checkpoint())
    assert restored.evaluate_frame(f, now) == []
    assert restored.status()["history_observations"] == 81
    assert restored.checkpoint() == engine.checkpoint()


def test_source_gap_resets_model_not_repaired_by_new_receipt_timestamp():
    engine = ExperimentalStrategyEngine(enabled=["short_horizon"])
    warm(engine)
    f, now = frame(100, bid=0.45)
    (signal,) = engine.evaluate_frame(f, now)
    assert not signal.eligible and "insufficient_causal_bid_history" in signal.reasons
    assert engine.status()["history_observations"] == 1


def test_current_quote_is_not_a_training_label_or_baseline_member():
    engine = ExperimentalStrategyEngine(enabled=["short_horizon"])
    warm(engine)
    f, now = frame(80, bid=0.45)
    (result,) = engine.evaluate_frame(f, now)
    assert result.forecast_value == 0.6
    assert result.diagnostics["reference_bid"] == 0.6
    assert result.diagnostics["bias"] == 0


def test_backdated_and_changed_immutable_book_inputs_are_rejected():
    engine = ExperimentalStrategyEngine(enabled=["short_horizon"])
    warm(engine)
    f, now = frame(79)
    changed = f.books[0].model_copy(update={"bids": (PriceLevel(price=0.5, size=100),)})
    (result,) = engine.evaluate_frame(f.model_copy(update={"books": (changed,)}), now)
    assert "changed_book_identity" in result.reasons
    f, _ = frame(78)
    (result,) = engine.evaluate_frame(f, now)
    assert "out_of_order_book" in result.reasons


def test_checkpoint_rejects_policy_capacity_and_time_corruption():
    engine = ExperimentalStrategyEngine(enabled=["short_horizon"])
    warm(engine, n=1)
    checkpoint = engine.checkpoint()
    for mutation in ("policy", "history", "time"):
        corrupt = deepcopy(checkpoint)
        if mutation == "policy":
            corrupt["policy"]["history_size"] = 20
        elif mutation == "history":
            corrupt["history"]["t1"] *= 100
        else:
            corrupt["history"]["t1"][0]["timestamp"] = "2026-01-01T00:00:00"
        with pytest.raises(ValueError):
            ExperimentalStrategyEngine(enabled=["short_horizon"]).restore(corrupt)


def test_causal_persistent_relationship_evidence_is_descriptive_not_payoff_constraint():
    engine = ExperimentalStrategyEngine(enabled=["persistent_relationship"])
    for i in range(24):
        left, now = frame(i, bid=0.3 if i < 20 else 0.4)
        right, _ = frame(i, bid=0.4, token="t2", market="m2")
        combined = left.model_copy(
            update={
                "markets": left.markets + right.markets,
                "books": left.books + right.books,
                "fees": {**left.fees, **right.fees},
            }
        )
        results = engine.evaluate_frame(combined, now)
    status = engine.status()["intelligence"]
    assert status["relationships"] == 1
    assert status["qualified_descriptive_findings"] == 1
    assert status["logical_payoff_constraints_inferred"] == 0
    assert status["profitability_implication"] is False
    assert not any(s.eligible for s in results)


def test_unregistered_strategy_and_oversized_universe_reject():
    with pytest.raises(ValueError):
        ExperimentalStrategyEngine(enabled=["automatic-profit"])
    engine = ExperimentalStrategyEngine(max_tokens=1)
    left, now = frame(0)
    right, _ = frame(0, token="t2", market="m2")
    with pytest.raises(ValueError):
        engine.evaluate_frame(left.model_copy(update={"markets": left.markets + right.markets}), now)


def test_adaptive_results_are_idempotent_cost_adjusted_and_not_training_labels():
    from neraium_poly.experimental.evaluation import AdaptiveResearchTracker

    tracker = AdaptiveResearchTracker()
    assert tracker.record("short_horizon", "exit-1", -1.0, 0.1, START, ["observed-entry", "observed-exit"])
    assert not tracker.record(
        "short_horizon", "exit-1", -1.0, 0.1, START, ["observed-entry", "observed-exit"]
    )
    with pytest.raises(ValueError):
        tracker.record("short_horizon", "exit-1", 1.0, 0.1, START, ["observed-entry", "observed-exit"])
    summary = tracker.summary()
    assert summary["rankings"][0]["net_realized_pnl"] == -1
    assert summary["rankings"][0]["fees"] == 0.1
    assert summary["baseline"]["simulated_pnl"] == 0
    assert summary["independent_evidence"] is False and summary["automatic_certified_promotion"] is False
    restored = AdaptiveResearchTracker()
    restored.restore(tracker.checkpoint())
    assert restored.summary() == summary


def test_losing_streak_and_loss_limit_suspend_without_chasing_or_promotion():
    from neraium_poly.experimental.evaluation import AdaptiveResearchTracker

    tracker = AdaptiveResearchTracker()
    for i in range(5):
        tracker.record("short_horizon", f"exit-{i}", -5.0, 0.1, START, [f"actual-quote-{i}"])
    state = tracker.summary()["rankings"][0]
    assert state["suspended"]
    assert "strategy_loss_limit" in state["reasons"] and "losing_streak_suspension" in state["reasons"]
    assert state["candidate_for_formal_research"] is False and state["certification_eligible"] is False


def test_promising_simulated_track_record_only_requests_research_never_certification():
    from neraium_poly.experimental.evaluation import AdaptiveResearchTracker

    tracker = AdaptiveResearchTracker()
    for i in range(20):
        tracker.record("short_horizon", f"exit-{i}", 0.1, 0.01, START, [f"actual-quote-{i}"])
    state = tracker.summary()["rankings"][0]
    assert state["candidate_for_formal_research"] is True
    assert state["certification_eligible"] is False and state["validation_status"] == "unvalidated"


def test_adaptive_drawdown_suspension_and_corrupt_checkpoints_reject():
    from neraium_poly.experimental.evaluation import AdaptiveResearchTracker

    tracker = AdaptiveResearchTracker()
    tracker.record("short_horizon", "gain", 50.0, 0.1, START, ["actual-quote-gain"])
    tracker.record("short_horizon", "loss", -50.0, 0.1, START, ["actual-quote-loss"])
    assert "strategy_drawdown_limit" in tracker.summary()["rankings"][0]["reasons"]
    bad = tracker.checkpoint()
    bad["states"]["short_horizon"]["fees"] = -1
    with pytest.raises(ValueError):
        AdaptiveResearchTracker().restore(bad)
    with pytest.raises(ValueError):
        tracker.record("s", "bad", 1.0, 0.1, START, [])


def test_readonly_archive_diagnostic_scores_quotes_without_inventing_execution(tmp_path):
    import sqlite3

    from neraium_poly.data import EventStore
    from neraium_poly.experimental.evaluation import _archive_worker

    path = tmp_path / "controlled-test-quotes.sqlite"
    store = EventStore(path)
    for i in range(100):
        f, _ = frame(i)
        store.append(f.books[0])
    store.close()
    readonly = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    high_water = readonly.execute("select max(rowid) from events").fetchone()[0]
    readonly.close()
    result = _archive_worker((str(path), high_water, 100, 60))
    assert result["raw_records_checked"] == 100
    assert result["scored_monetary_forecasts"] > 0
    assert result["future_bid_mae"] == 0 and result["unchanged_current_bid_baseline_mae"] == 0
    assert result["execution_pnl"] is None and result["simulated_fills"] is None
    assert result["certification_status"] == "blocked"
