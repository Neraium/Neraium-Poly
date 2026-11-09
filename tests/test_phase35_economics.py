"""Synthetic execution arithmetic fixtures, never prospective performance."""

import math

import pytest
from neraium_poly.research.phase35.economics import depth_capacity


def scenario(asks=None, **changes):
    args = {
        "probability": 0.6,
        "lower_probability": 0.0,
        "upper_probability": 1.0,
        "fee_rate": 0.05,
        "bankroll": 500,
    }
    args.update(changes)
    return depth_capacity(asks or [{"price": 0.5, "size": 100}, {"price": 0.55, "size": 200}], **args)


def test_exact_native_curve_multilevel_not_flat_fee():
    result = scenario()
    expected_fee = 10 * 0.05 * 0.5 * 0.5 + 20 * 0.05 * 0.55 * 0.45
    assert result["supported_quantity"] == 30
    assert result["acquisition_cost"] == 16
    assert math.isclose(result["protocol_fee_before_rounding"], expected_fee)
    assert math.isclose(result["conditional_point_headroom_after_protocol_fee"], 18 - 16 - expected_fee)
    assert result["native_headroom_bounds_before_unverified_costs"][0] < 0
    assert result["actual_fill"] is False


def test_twenty_percent_cap_includes_protocol_fee():
    r = scenario([{"price": 0.5, "size": 100000}])
    assert math.isclose(r["capital_with_protocol_fee"], 100)
    assert math.isclose(r["supported_quantity"], 100 / (0.5 + 0.0125))


def test_capacity_saturates_instead_of_scaling_with_bankroll():
    small, large = scenario(bankroll=1000), scenario(bankroll=1000000)
    assert small["supported_quantity"] == large["supported_quantity"] == 30


def test_unfavorable_levels_do_not_create_hypothetical_positions():
    r = scenario([{"price": 0.6, "size": 100}, {"price": 0.7, "size": 100}])
    assert r["supported_quantity"] == r["capital_with_protocol_fee"] == 0


def test_sub_three_cent_research_headroom_not_suppressed():
    r = scenario([{"price": 0.58, "size": 100}])
    assert 0 < r["conditional_point_headroom_after_protocol_fee"] < 0.3
    assert r["supported_quantity"] == 10


@pytest.mark.parametrize(
    "asks",
    [
        [{"price": 0.5, "size": 10}, {"price": 0.5, "size": 20}],
        [{"price": 0.6, "size": 10}, {"price": 0.5, "size": 20}],
        [{"price": 0.5, "size": -1}],
        [{"price": 0.5, "size": math.inf}],
    ],
)
def test_duplicate_or_invalid_depth_rejected(asks):
    with pytest.raises(ValueError):
        scenario(asks)


@pytest.mark.parametrize(
    "changes",
    [{"participation": 0.2}, {"probability": math.nan}, {"lower_probability": 0.7}, {"bankroll": 0}],
)
def test_invalid_assumptions_rejected(changes):
    with pytest.raises(ValueError):
        scenario(**changes)
