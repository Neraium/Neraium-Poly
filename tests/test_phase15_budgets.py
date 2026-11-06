"""Controlled capacity fixtures, not measured service consumption."""

from datetime import timedelta

import pytest
from neraium_poly.research.phase15.budgets import GIB, capacity_status, project_retention


def archive():
    return {"health": "ok", "usage_bytes": 4 * GIB, "budget_bytes": 64 * GIB,
            "free_bytes": 400 * GIB, "global_floor_bytes": 64 * GIB,
            "growth_bytes_per_second": 100000}


def test_capacity_soft_warning_never_weakens_hard_floor_or_grants_removal(now):
    a = archive()
    a["growth_bytes_per_second"] = 1e6
    result = capacity_status(a, service="collector", now=now)
    assert result["status"] == "warning" and not result["backpressure"]
    assert not result["retirement_authorized"] and not result["budget_increase_authorized"]
    a.update(free_bytes=7 * GIB, global_floor_bytes=0)
    assert capacity_status(a, service="collector", now=now)["backpressure"]


@pytest.mark.parametrize("rate", [None, 0, float("nan"), -1, True])
def test_missing_or_invalid_growth_never_implies_infinite_retention(now, rate):
    a = archive()
    a["growth_bytes_per_second"] = rate
    assert capacity_status(a, service="collector", now=now)["seconds_to_capacity"] is None


def test_stale_or_future_capacity_input_fails_closed(now):
    for at in [now - timedelta(seconds=61), now + timedelta(seconds=1)]:
        assert capacity_status(archive(), service="collector", now=now, generated_at=at)["backpressure"]


def test_retention_scenarios_include_linear_catalog_and_no_assumed_cleanup():
    values = {"current_usage": 4 * GIB, "budget": 64 * GIB, "daily_raw": 8 * GIB,
              "daily_gzip": 2 * GIB, "daily_catalog_state": GIB, "warm_days": 1}
    retained = project_retention(**values)
    conditional = project_retention(**values, proposed_original_removal=True)
    assert retained["projected_usage_bytes"] > conditional["projected_usage_bytes"]
    assert not conditional["fits_budget"]  # Compression alone cannot erase growing catalog/state.
    assert conditional["scenario_only"] and not conditional["removal_authorized"]
