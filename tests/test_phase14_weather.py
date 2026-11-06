"""Controlled METAR/mapping fixtures, never operational forecasts or weather outcomes."""
import hashlib
import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from neraium_poly.contracts import MarketSnapshot
from neraium_poly.research.phase14 import weather

NOW = datetime(2026, 11, 6, 8, 30, tzinfo=UTC)
RULES = "CONTROLLED weather rule fixture; not a real market rule approval"


@pytest.fixture
def contract(monkeypatch):
    # Only controlled tests substitute the hash; real capture uses the unmodified
    # audited full rule hash and actual Polymarket snapshot.
    monkeypatch.setattr(weather, "AUDITED_RULES", hashlib.sha256(RULES.encode()).hexdigest())
    m = MarketSnapshot(timestamp=NOW-timedelta(minutes=1), available_at=NOW-timedelta(minutes=1),
        source="https://gamma-api.polymarket.com", market_id="controlled-weather", event_id="controlled-parent",
        token_id="controlled-yes", question="Will the highest temperature in Seoul (Incheon) be 12°C on November 6?",
        outcome="Yes", probability=.5, status="active", resolution_rules=RULES,
        resolution_source="https://aviationweather.gov/api/data/metar?ids=RKSI&format=raw&date=2026-11-06T18:00:00Z&hours=30",
        end_time=datetime(2026,11,6,12,tzinfo=UTC))
    return m, weather.map_weather(m, now=NOW)


def row(raw="METAR RKSI 060800Z 32020KT CAVOK 08/M09 Q1027 NOSIG", at=None, **changes):
    at = at or NOW.replace(minute=0)
    return {"icaoId":"RKSI", "obsTime":at.timestamp(), "receiptTime":(at+timedelta(minutes=4)).isoformat(),
            "rawOb":raw, "temp":99, **changes}


def body(*rows):
    return json.dumps(list(rows)).encode()


def test_exact_mapping_station_local_window_and_metadata_end_are_distinct(contract):
    m,c = contract
    assert c.compatible and not c.review_required
    assert c.parameters["station"]["timezone"] == "Asia/Seoul"
    assert c.parameters["period_start_utc"] == "2026-11-05T15:00:00+00:00"
    assert c.parameters["period_end_utc"] == "2026-11-06T15:00:00+00:00"
    assert datetime.fromisoformat(c.parameters["period_end_utc"]) != m.end_time
    assert c.parameters["unrounded_lower_inclusive"] == "11.5"


@pytest.mark.parametrize("changes", [
    {"resolution_source":"https://aviationweather.gov/api/data/metar?ids=RKSS"},
    {"resolution_rules":"changed rules"}, {"question":"Will it rain tomorrow?"},
    {"outcome":"Maybe"}, {"status":"resolved"}, {"available_at":NOW+timedelta(seconds=1)}])
def test_ambiguous_or_changed_contracts_withhold(contract, changes):
    m,_ = contract
    c = weather.map_weather(m.model_copy(update=changes), now=NOW)
    assert not c.compatible and c.review_required and c.probability_semantics == "unsupported"


def test_raw_remark_precision_overrides_body_and_api_derived_temperature(contract):
    _,c=contract
    obs, rejected=weather.normalize_metars(body(row("METAR RKSI 060800Z CAVOK 14/13 RMK T01390133")),c,retrieved_at=NOW)
    assert not rejected and obs[0]["temperature_celsius"] == 13.9
    assert obs[0]["rounded_celsius"] == 14
    assert obs[0]["precision"] == "tenths_Celsius_T_remark"


@pytest.mark.parametrize("value,rounded", [(16.5,17),(-8.5,-8),(-1.7,-2),(17.4,17)])
def test_exact_contract_half_rounding(value,rounded):
    assert weather.rounded_celsius(value)==rounded


def test_routine_rules_exclude_only_speci_not_off_hour_or_unlabeled(contract):
    _,c=contract
    at=NOW.replace(hour=7,minute=17)
    raw=body(row("SPECI RKSI 060800Z CAVOK 30/10"),
             row("RKSI 060717Z CAVOK 09/M08",at=at))
    obs,rejected=weather.normalize_metars(raw,c,retrieved_at=NOW)
    assert len(obs)==1 and obs[0]["temperature_celsius"]==9
    assert rejected["special_observation_excluded_by_rules"]==1


@pytest.mark.parametrize("change,reason", [
    ({"icaoId":"RKSS"},"weather_station_mismatch"),
    ({"receiptTime":None},"fromisoformat"),
    ({"obsTime":(NOW+timedelta(hours=1)).timestamp()},"future_weather_observation"),
    ({"rawOb":"METAR RKSI 060700Z CAVOK 08/M09"},"raw_and_structured_observation_time_mismatch"),
])
def test_invalid_observations_cannot_enter_evidence(contract,change,reason):
    _,c=contract
    obs,rejected=weather.normalize_metars(body(row(**change)),c,retrieved_at=NOW)
    assert not obs and any(reason in r for r in rejected)


def test_local_day_boundary_and_conflicting_corrections_are_not_guessed(contract):
    _,c=contract
    outside=NOW.replace(day=5,hour=14,minute=30)
    obs,rejected=weather.normalize_metars(body(
        row("METAR RKSI 051430Z CAVOK 13/10",at=outside),row(),
        row("METAR RKSI 060800Z COR CAVOK 20/10")),c,retrieved_at=NOW)
    assert not obs
    assert rejected["outside_station_local_observation_day"]==1
    assert rejected["conflicting_same_observation_revision"]==1


async def test_actual_interface_archives_source_hash_and_withholds_probability(contract):
    _,c=contract
    raw=body(row())
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request:httpx.Response(200,content=raw))) as client:
        evidence=await weather.collect_weather(c,client=client,clock=lambda:NOW)
    e=evidence[0]
    assert e.qualification=="qualified_research" and e.available_at==NOW
    assert e.payload["raw_sha256"]==hashlib.sha256(raw).hexdigest()
    assert e.content_sha256==weather.digest(e.payload)
    assert e.payload["maximum_observed_celsius"]==8
    assert e.payload["observation_period_complete"] is False
    result=weather.forecast_weather(c,evidence+evidence,cutoff=NOW)
    assert result["probability"] is None and result["qualified"] is False
    assert result["qualified_observations"]==1  # A repeated evidence record is not new evidence.
    assert not result["forecast_recorded"] and not result["trading_authority"]
    earlier=weather.forecast_weather(c,evidence,cutoff=NOW-timedelta(seconds=1))
    assert earlier["qualified_observations"]==0


@pytest.mark.parametrize("status",[204,429,503,302])
async def test_unavailable_rate_limited_redirected_responses_never_fallback(contract,status):
    _,c=contract
    calls=[]
    def handler(request):
        calls.append(request)
        assert request.method=="GET" and request.url.host=="aviationweather.gov"
        return httpx.Response(status,headers={"location":"https://evil.invalid"},content=b"[]")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        if status==204:
            assert await weather.collect_weather(c,client=client,clock=lambda:NOW)==()
        else:
            with pytest.raises((httpx.HTTPError,ValueError)):
                await weather.collect_weather(c,client=client,clock=lambda:NOW)
    assert len(calls)==1


async def test_oversized_payload_rejects_before_normalization(contract):
    _,c=contract
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r:httpx.Response(200,content=b"x"*(weather.MAX_BYTES+1)))) as client:
        with pytest.raises(ValueError,match="byte_budget"):
            await weather.collect_weather(c,client=client,clock=lambda:NOW)


def test_contract_copy_cannot_redirect_collection(contract):
    _,c=contract
    changed=c.model_copy(update={"parameters":{**c.parameters,"source_request_url":"https://evil.invalid"}})
    with pytest.raises(ValueError,match="qualified exact"):
        weather.forecast_weather(changed,(),cutoff=NOW)


async def test_external_provider_cannot_be_self_asserted_from_another_origin(contract):
    _,c=contract
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r:httpx.Response(200,content=body(row())))) as client:
        (e,)=await weather.collect_weather(c,client=client,clock=lambda:NOW)
    spoof=e.model_copy(update={"source":"https://fixture.invalid/spoof"})
    result=weather.forecast_weather(c,(spoof,),cutoff=NOW)
    assert result["qualified_observations"]==0
    assert "noncausal_or_mismatched_weather_evidence" in result["reasons"]


def test_threshold_copy_requires_original_mapping_replay(contract):
    _,c=contract
    changed=c.model_copy(update={"parameters":{**c.parameters,"threshold_celsius":13,
        "unrounded_lower_inclusive":"12.5","unrounded_upper_exclusive":"13.5"}})
    with pytest.raises(ValueError,match="mapping replay"):
        weather.forecast_weather(changed,(),cutoff=NOW)
