"""Controlled fixtures only; no synthetic outcome is a real market observation."""

import copy
from datetime import UTC, datetime, timedelta

import pytest
from neraium_poly.contracts import PriceLevel
from neraium_poly.research.phase16.execution import assess_execution, depth_walk
from neraium_poly.research.phase16.short_horizon import replay_forecasts

OFFICIAL = "https://clob.polymarket.com"
START = datetime(2026, 11, 6, 12, tzinfo=UTC)


def source_pair(market, book):
    return (market.model_copy(update={"source": "https://gamma-api.polymarket.com"}),
            book.model_copy(update={"source": OFFICIAL}))


def fee(now, token="t1", value=.05):
    return {"fee_rate": value, "observed_at": now.isoformat(), "source": OFFICIAL,
            "reference": f"/markets-by-token/{token}", "token_id": token,
            "evidence_id": "CONTROLLED fee evidence", "raw_response_ids": ["fixture-1", "fixture-2"]}


def test_exact_depth_costs_and_reservation_match_existing_standard_sizing(market, book, now):
    m, b = source_pair(market, book)
    r = assess_execution(m, b, now=now, fee_observation=fee(now), forecast_lower_bid=.6)
    assert r["quantity_shares"] == 5
    assert r["broker_limit_notional"] == pytest.approx(2)
    assert r["broker_fee_inclusive_reservation"] == pytest.approx(2.1)
    assert r["estimated_net_edge_per_share"] == pytest.approx(.13)
    assert r["execution_checks_pass"] and r["cost_adjusted_edge_pass"]
    assert not r["trading_authority"] and not r["future_exit_liquidity_verified"]
    assert r["probability_semantics"].endswith("not_terminal_probability")


def test_deeper_liquidity_never_makes_best_ask_limit_executable(market, book, now):
    m, b = source_pair(market, book)
    b = b.model_copy(update={"asks": (PriceLevel(price=.4, size=2), PriceLevel(price=.42, size=100))})
    r = assess_execution(m, b, now=now, fee_observation=fee(now, value=0), forecast_lower_bid=.6)
    assert r["hypothetical_sweep_entry"]["complete"]
    assert r["hypothetical_sweep_entry"]["vwap"] == pytest.approx(.418)
    assert r["broker_limit_capacity_shares"] == .5
    assert "best_ask_limit_participation_insufficient" in r["reasons"]
    assert not r["execution_checks_pass"]


def test_partial_depth_and_disappearing_exit_liquidity_reject(market, book, now):
    m, b = source_pair(market, book)
    b = b.model_copy(update={"bids": (PriceLevel(price=.39, size=4),),
                             "asks": (PriceLevel(price=.4, size=4),)})
    r = assess_execution(m, b, now=now, fee_observation=fee(now), forecast_lower_bid=.6)
    assert r["hypothetical_sweep_entry"]["depth_supported_shares"] == 1
    assert r["hypothetical_sweep_entry"]["unavailable_shares"] == 4
    assert "current_bid_exit_depth_insufficient" in r["reasons"]
    assert "observed_ask_depth_insufficient" in r["reasons"]
    assert r["estimated_net_edge_per_share"] is None


@pytest.mark.parametrize("change,reason", [
    ({"timestamp": START-timedelta(seconds=16), "available_at": START-timedelta(seconds=15)}, "stale_book"),
    ({"available_at": START+timedelta(seconds=1)}, "future_data"),
    ({"source": "fixture-untrusted"}, "unverified_public_source"),
    ({"market_id": "ambiguous-other-market"}, "market_book_identity_mismatch"),
    ({"complete": False}, "incomplete_book"),
    ({"asks": ()}, "missing_liquidity"),
])
def test_stale_missing_or_mismatched_depth_fails_closed(market, book, change, reason):
    m, b = source_pair(market, book)
    m = m.model_copy(update={"timestamp": START, "available_at": START})
    b = b.model_copy(update={"timestamp": START, "available_at": START, **change})
    r = assess_execution(m, b, now=START, fee_observation=fee(START), forecast_lower_bid=.6)
    assert reason in r["execution_reasons"] and not r["execution_checks_pass"]


@pytest.mark.parametrize("bad", [None, {"fee_rate": True}, {"fee_rate": .01, "observed_at": START.isoformat(),
    "source": "https://other.invalid", "reference": "fake"},
    {"fee_rate": .01, "observed_at": (START-timedelta(seconds=301)).isoformat(),
     "source": OFFICIAL, "reference": "expired"}])
def test_fee_missingness_or_unverified_provenance_never_becomes_zero_fee(market, book, bad):
    m, b = source_pair(market, book)
    m = m.model_copy(update={"timestamp": START, "available_at": START})
    b = b.model_copy(update={"timestamp": START, "available_at": START})
    r = assess_execution(m, b, now=START, fee_observation=bad, forecast_lower_bid=.6)
    assert r["fee_rate"] is None and not r["execution_checks_pass"]
    assert r["estimated_net_edge_per_share"] is None


def test_minimum_order_and_fee_spread_costs_can_eliminate_edge(market, book, now):
    m, b = source_pair(market, book)
    r = assess_execution(m, b, now=now, fee_observation=fee(now), forecast_lower_bid=.43)
    assert not r["cost_adjusted_edge_pass"] and r["estimated_net_edge_per_share"] < .03
    r = assess_execution(m.model_copy(update={"min_order_size": 20}), b, now=now,
                         fee_observation=fee(now), forecast_lower_bid=.6)
    assert "minimum_order_exceeds_standard_notional" in r["reasons"]


def test_nonfinite_or_wrong_tier_values_cannot_create_unserializable_metrics(market, book, now):
    import json
    m, b = source_pair(market, book)
    for value in [float("nan"), True, -1, 15]:
        r = assess_execution(m, b, now=now, target_notional=value,
                             fee_observation=fee(now), forecast_lower_bid=.6)
        assert "unsupported_research_notional_tier" in r["reasons"]
        json.dumps(r, allow_nan=False)
    with pytest.raises(ValueError):
        depth_walk([{"price": .4, "size": 100}], 5, participation=.5)


def points(count=180, *, seconds=20):
    result = []
    for i in range(count):
        at = START+timedelta(seconds=i*seconds)
        bid = .35+i*.0005
        result.append({"source": OFFICIAL, "source_at": at.isoformat(),
            "available_at": (at+timedelta(seconds=1)).isoformat(),
            "observed_at": (at+timedelta(seconds=2)).isoformat(),
            "book_id": f"CONTROLLED-book-{i}", "market_id": "m1", "token_id": "t1", "event_id": "e1",
            "rules_sha256": "a"*64, "quantity": 5.0, "depth_scope": "top3_observed",
            "bid": bid, "ask": bid+.01, "bid_vwap": bid-.001, "ask_vwap": bid+.011,
            "fee_observation": fee(at+timedelta(seconds=1)), "proof": "CONTROLLED raw replay"})
    return result


def verify_fixture(p):
    return p.get("proof") == "CONTROLLED raw replay"


def test_mark_replay_is_causal_purged_frozen_and_not_probability_or_profit():
    rows = points(); cutoff=START+timedelta(hours=2)
    r = replay_forecasts(rows, cutoff=cutoff, verify_point=verify_fixture)
    assert r["status"] == "exploratory_temporal_mark_validation"
    assert r["heldout_mark_examples"] > 20 and r["training_mark_examples"] > 20
    split = datetime.fromisoformat(r["training_interval"]["end"])
    heldout = datetime.fromisoformat(r["heldout_interval"]["start"])
    assert (heldout-split).total_seconds() == 90
    assert r["model_mae"] < r["unchanged_bid_baseline_mae"]
    # A controlled forecasting improvement still loses the modeled spread/fees.
    assert r["cost_adjusted_quote_roundtrip_mean"] < 0
    for p in r["records"]:
        assert datetime.fromisoformat(p["max_training_label_available_at"]) <= split
        assert datetime.fromisoformat(p["decision_at"]) >= heldout
        assert datetime.fromisoformat(p["label_source_at"]) >= datetime.fromisoformat(p["target_at"])
        assert all(int(i.rsplit("-", 1)[1]) < int(p["book_id"].rsplit("-", 1)[1]) for i in p["feature_ids"])
    assert r["overlapping_parent_groups"] == 1
    assert r["independent_training_events"] == r["independent_heldout_events"] == 0
    assert r["calibration_brier"] is r["calibration_log_loss"] is None
    assert not r["trading_authority"] and not r["certification_eligible"]


def test_raw_replay_is_required_and_future_append_does_not_change_past_forecasts():
    rows = points(); cutoff=START+timedelta(hours=2)
    none = replay_forecasts(rows, cutoff=cutoff)
    assert none["accepted_points"] == 0 and none["model_mae"] is None
    a = replay_forecasts(rows, cutoff=cutoff, verify_point=verify_fixture)
    future = points(1)[0]
    future.update(source_at=(cutoff+timedelta(seconds=1)).isoformat(),
                  available_at=(cutoff+timedelta(seconds=2)).isoformat(),
                  observed_at=(cutoff+timedelta(seconds=3)).isoformat(), book_id="future-book")
    b = replay_forecasts(rows+[future], cutoff=cutoff, verify_point=verify_fixture)
    assert a["records"] == b["records"]
    assert b["rejected_points"]["future_stale_or_unavailable_point"] == 1


def test_missing_depth_fees_and_ambiguous_quote_identity_are_not_invented():
    rows = points(); cutoff=START+timedelta(hours=2)
    missing = copy.deepcopy(rows); missing[50]["bid_vwap"] = None
    r = replay_forecasts(missing, cutoff=cutoff, verify_point=verify_fixture)
    assert r["rejected_points"]["insufficient_or_invalid_fixed_share_depth"] == 1
    for p in rows:p["fee_observation"] = None
    r = replay_forecasts(rows, cutoff=cutoff, verify_point=verify_fixture)
    assert r["heldout_mark_examples"] > 0 and r["cost_adjusted_quote_roundtrip_mean"] is None
    duplicate = copy.deepcopy(rows[50]); duplicate["bid_vwap"] -= .0001
    r = replay_forecasts(rows+[duplicate], cutoff=cutoff, verify_point=verify_fixture)
    assert r["rejected_points"]["changed_quote_identity"] == 1
    assert r["rejected_points"]["ambiguous_original_quote_quarantined"] == 1
    assert r["accepted_points"] == len(rows)-1


def test_gaps_and_unmatched_horizons_withhold_instead_of_interpolating():
    r = replay_forecasts(points(100, seconds=60), cutoff=START+timedelta(hours=3), verify_point=verify_fixture)
    assert r["heldout_mark_examples"] == 0
    assert r["decision_rejections"]["unmatured_target"] > 0
    r = replay_forecasts(points(100, seconds=130), cutoff=START+timedelta(hours=5), verify_point=verify_fixture)
    assert r["heldout_mark_examples"] == 0
    with pytest.raises(ValueError):
        replay_forecasts(points(), cutoff=START+timedelta(hours=3), verify_point=verify_fixture, min_prior=20)
