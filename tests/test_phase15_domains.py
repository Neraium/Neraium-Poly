"""Controlled fixtures only: these tests are not observed forecast skill."""
import hashlib
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from neraium_poly.research.phase14.contracts import DomainContract
from neraium_poly.research.phase15.domains import (
    calibration_report,
    collect_nws_precipitation,
    qualify_domain_inputs,
)

NOW = datetime(2026, 11, 6, 20, tzinfo=UTC)


def sample(index=0, split="train"):
    at = NOW - timedelta(days=300-index if split == "train" else 100-index)
    return {"dependency_group": str(index)+split, "domain": "weather", "model_version": "fixture-v1",
            "feature_version": "fixture-v1", "contract_type": "point_rain", "uses_market_features": False,
            "forecast_at": at.isoformat(), "evidence_available_at": at.isoformat(),
            "market_at": at.isoformat(), "market_available_at": at.isoformat(), "outcome_at": (at+timedelta(hours=1)).isoformat(),
            "outcome_available_at": (at+timedelta(hours=2)).isoformat(),
            "probability": .6, "market_probability": .5, "outcome": index % 2, "split": split}


def test_no_replay_no_score_and_empty_metrics_remain_null():
    result = calibration_report([sample()], cutoff=NOW)
    assert result["training_events"] == 0 and result["metrics"] is None
    assert result["rejections"] == {"independent_raw_replay_required": 1}
    assert calibration_report([], cutoff=NOW)["metrics"] is None


def test_event_independence_chronological_counts_and_no_promotion():
    rows = [sample(i) for i in range(100)] + [sample(i, "heldout") for i in range(100)]
    result = calibration_report(rows+[rows[-1]], cutoff=NOW, verify_raw=lambda _: True)
    assert result["training_events"] == result["heldout_events"] == 100
    assert result["rejections"] == {"repeated_dependency_group": 1}
    assert result["cohort_sufficient"]
    assert result["metrics"]["brier"] == pytest.approx(.26)
    assert result["metrics"]["market_brier"] == pytest.approx(.25)
    assert result["metrics"]["brier_difference_95_bound"][0] < 0
    assert not result["trading_authority"] and not result["certification_authority"]
    assert result["execution_cost_adjusted_performance"] is None
    assert calibration_report(rows, cutoff=NOW, verify_raw=lambda _: True)["dataset_sha256"] != result["dataset_sha256"]


@pytest.mark.parametrize("change,reason", [
    ({"evidence_available_at": (NOW+timedelta(seconds=1)).isoformat()}, "noncausal_or_unavailable_evidence"),
    ({"market_at": (NOW-timedelta(days=300)+timedelta(seconds=1)).isoformat()}, "noncontemporaneous_market_baseline"),
    ({"market_available_at": NOW.isoformat()}, "noncontemporaneous_market_baseline"),
    ({"probability": float("nan")}, "invalid_binary_scoring_input"),
    ({"uses_market_features": True}, "independent_feature_review_required"),
    ({"outcome": True}, "invalid_binary_scoring_input"),
    ({"evidence_available_at": "2026-01-01"}, "aware_timestamp_required"),
])
def test_forecast_leakage_and_invalid_binary_values_rejected(change, reason):
    result = calibration_report([{**sample(), **change}], cutoff=NOW, verify_raw=lambda _: True)
    assert result["rejections"] == {reason: 1}


def test_training_resolutions_cannot_follow_heldout_forecast_and_domain_binding():
    row = sample(0, "heldout")
    train = {**sample(), "outcome_available_at": (NOW-timedelta(days=1)).isoformat()}
    result = calibration_report([train, row], cutoff=NOW, verify_raw=lambda _: True)
    assert "chronological_training_leakage" in result["blockers"] and result["metrics"] is None
    result = calibration_report([sample(), {**row, "domain": "crypto"}], cutoff=NOW, verify_raw=lambda _: True)
    assert "mixed_domain_model_or_semantics" in result["blockers"]


def nws_handler(request):
    if "/points/" in request.url.path:
        return httpx.Response(200, json={"properties": {"forecastHourly": "https://api.weather.gov/gridpoints/OKX/34,45/forecast/hourly"}})
    return httpx.Response(200, json={"properties": {"updateTime": (NOW-timedelta(hours=1)).isoformat(), "periods": [
        {"startTime": (NOW+timedelta(hours=1)).isoformat(), "endTime": (NOW+timedelta(hours=2)).isoformat(),
         "probabilityOfPrecipitation": {"unitCode": "wmoUnit:percent", "value": 40}}]}})


async def test_nws_provider_probability_preserves_raw_hash_not_market_forecast():
    async with httpx.AsyncClient(transport=httpx.MockTransport(nws_handler)) as client:
        e = await collect_nws_precipitation(40.7789, -73.9692, client=client, clock=lambda: NOW)
    assert e.available_at == e.retrieved_at == NOW
    assert e.payload["periods"][0]["provider_probability"] == .4
    assert not e.payload["market_forecast"] and not e.payload["station_mapping_verified"]
    assert hashlib.sha256(e.payload["raw_response_utf8"].encode()).hexdigest() == e.payload["raw_response_sha256"]
    c = DomainContract(id="fixture", timestamp=NOW, available_at=NOW, source="fixture",
        domain="weather", event_id="fixture", market_id="fixture", token_id="fixture", contract_type="temperature",
        probability_semantics="binary_event_probability", rules_sha256="a"*64,
        parameters={"station": {"id": "RKSI"}, "period_start_utc": (NOW-timedelta(days=1)).isoformat(),
                    "period_end_utc": (NOW-timedelta(hours=1)).isoformat()})
    result = qualify_domain_inputs(c, [e], cutoff=NOW)
    assert result["probability"] is None and "observation_window_already_closed" in result["reasons"]
    assert "station_matched_predictive_distribution_and_calibration_required" in result["reasons"]
    corrupted = e.model_copy(update={"payload": {**e.payload, "raw_response_utf8": "corrupt"}})
    assert "evidence_content_hash_mismatch" in qualify_domain_inputs(c, [corrupted], cutoff=NOW)["reasons"]


async def test_nws_rejects_untrusted_link_large_response_and_rate_limit():
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"properties": {
            "forecastHourly": "https://untrusted.invalid/forecast/hourly"}}))) as client:
        with pytest.raises(ValueError, match="official_nws_url"):
            await collect_nws_precipitation(40, -73, client=client, clock=lambda: NOW)
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, content=b"x"*524289))) as client:
        with pytest.raises(ValueError, match="bounded_nws_response"):
            await collect_nws_precipitation(40, -73, client=client, clock=lambda: NOW)
    calls = []
    def limited(request):
        calls.append(request)
        return httpx.Response(429)
    async with httpx.AsyncClient(transport=httpx.MockTransport(limited)) as client:
        with pytest.raises(httpx.HTTPStatusError):
            await collect_nws_precipitation(40, -73, client=client, clock=lambda: NOW)
    assert len(calls) == 1  # Scheduled caller applies backoff; no tight retry storm.


def test_large_calibration_input_bounded():
    with pytest.raises(ValueError, match="bounded_calibration"):
        calibration_report([{}]*10001, cutoff=NOW)
