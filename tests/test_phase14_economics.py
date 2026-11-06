"""Controlled release-vintage fixtures do not establish authentic economic forecasts."""
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from neraium_poly.research.phase14 import economics
from test_phase14_finance import market

NOW = datetime(2026,11,6,9,tzinfo=UTC)


def economic_contract():
    m=market().model_copy(update={"resolution_source": economics.FOMC_CALENDAR,
        "resolution_rules":"The upper bound of the target federal funds range defines this controlled contract."})
    return economics.map_economic(m,now=NOW)


def vintage():
    return {"source_url":"https://www.bls.gov/news.release/cpi.nr0.htm", "release_at":(NOW-timedelta(hours=1)).isoformat(),
        "retrieved_at":NOW.isoformat(), "vintage_at":(NOW-timedelta(hours=1)).isoformat(),
        "release_status":"initial", "is_revision":False, "series_id":"fixture_CPI", "units":"percent",
        "raw_evidence_sha256":"a"*64, "value":1.2}


def test_fomc_target_upper_bound_is_not_effective_funds_rate_or_probability():
    c=economic_contract()
    assert c.parameters["effective_funds_rate_is_not_target_upper_bound"] is True
    assert not c.compatible and c.review_required
    assert economics.forecast_economic(c,[],cutoff=NOW)["probability"] is None


@pytest.mark.parametrize("change", [{"release_at": (NOW+timedelta(seconds=1)).isoformat()},
    {"retrieved_at": (NOW+timedelta(seconds=1)).isoformat()}, {"vintage_at":"2026-11-06"},
    {"is_revision":True}, {"release_status":"revised"}, {"source_url":"https://private.invalid/data"},
    {"raw_evidence_sha256":"bad"}, {"value":float('nan')}, {"value":False}])
def test_future_revised_unknown_or_unproven_vintages_withheld(change):
    report=economics.qualify_economic_vintages([{**vintage(),**change}],cutoff=NOW)
    assert not report["accepted"] and report["rejections"]


def test_retrieval_today_cannot_supply_past_release_feature_availability():
    assert not economics.qualify_economic_vintages([vintage()],cutoff=NOW-timedelta(days=1))["accepted"]
    qualified=economics.qualify_economic_vintages([vintage()],cutoff=NOW)
    assert qualified["accepted"][0]["available_at"] == NOW.isoformat()
    assert qualified["certification_authority"] is False


async def test_official_calendar_context_preserves_raw_bytes_without_inventing_publication_time():
    body=b'<html>federalreserve FOMC 2026 meeting calendar</html>'
    def handler(request):
        assert str(request.url)==economics.FOMC_CALENDAR and request.method=='GET'
        return httpx.Response(200,content=body)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        (e,)=await economics.collect_economic(economic_contract(),client=client,clock=lambda:NOW)
    assert e.available_at==NOW and e.source_timestamp is None
    assert e.payload["raw_response_utf8"]==body.decode()
    assert "historical_vintages" in e.missingness
