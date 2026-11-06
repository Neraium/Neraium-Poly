"""Controlled taxonomy fixtures never count as real market observations."""
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from neraium_poly.contracts import MarketSnapshot
from neraium_poly.research.phase14.discovery import DomainDiscovery, classify_market, classify_snapshot

NOW = datetime(2026, 11, 6, 9, tzinfo=UTC)


def raw(ident="m", tags=None, **changes):
    return {"id": ident, "eventId": "e"+ident, "question": "Controlled fixture question?",
            "clobTokenIds": '["1","2"]', "outcomes": '["Yes","No"]', "description": "Controlled rules",
            "resolutionSource": "https://fixture.invalid/", "active": True, "closed": False,
            "liquidityNum": "1000", "volume24hr": 100, "tags": tags or [], **changes}


def test_strong_structured_taxonomy_precedes_keyword_suggestions():
    value = classify_market(raw(tags=[{"slug": "weather", "id": "5"}], question="Will Bitcoin reach a threshold?"), NOW)
    assert value.domain == "weather" and value.classification_basis == "structured_tag"
    assert value.metadata["executable_quotes_verified"] is False and value.metadata["spread"] is None
    assert value.metadata["bid_depth"] is None


def test_ambiguous_context_tags_require_review_and_specific_subtypes_are_distinct():
    value = classify_market(raw(tags=[{"slug": "weather"}, {"slug": "politics"}]), NOW)
    assert value.domain == "other" and value.classification_review_required
    esports = classify_market(raw(tags=[{"slug": "sports"}, {"slug": "esports"}]), NOW)
    assert esports.domain == "esports"
    crypto = classify_market(raw(tags=[{"slug": "finance"}, {"slug": "crypto"}]), NOW)
    assert crypto.domain == "crypto"


def test_unstructured_keywords_never_claim_verified_category():
    value = classify_market(raw(question="Will Bitcoin rise?"), NOW)
    assert value.domain == "other" and value.classification_review_required
    assert value.metadata["provisional_domains"] == ["crypto"]
    assert value.metadata["independent_evidence_available"] is False


def test_resolution_host_is_exact_and_unknown_metrics_stay_null():
    value = classify_market(raw(resolutionSource="https://www.bls.gov/blah", liquidityNum=None), NOW)
    assert value.domain == "economics" and value.metadata["liquidity_usd"] is None
    evil = classify_market(raw(resolutionSource="https://www.bls.gov.attacker.invalid"), NOW)
    assert evil.domain == "other"


@pytest.mark.parametrize("changes", [{"clobTokenIds": '["1","1"]'}, {"outcomes": '["Yes"]'}, {"eventId": ""}])
def test_incomplete_outcome_or_event_identity_rejects(changes):
    with pytest.raises(ValueError):
        classify_market(raw(**changes), NOW)


def test_old_snapshot_projection_does_not_become_fresh_or_invent_structured_metadata():
    market = MarketSnapshot(id="controlled", timestamp=NOW-timedelta(hours=2), available_at=NOW-timedelta(hours=2),
                            source="https://gamma-api.polymarket.com", market_id="m", event_id="e", token_id="t",
                            question="Controlled", outcome="Yes", probability=.5, status="active",
                            resolution_source="https://www.nba.com/", resolution_rules="Controlled rules")
    value = classify_snapshot(market, NOW)
    assert value.domain == "sports" and value.available_at == market.available_at
    assert value.token_ids == ("t",) and not value.metadata["observed_tags"]
    assert value.metadata["freshness"] == "stale" and value.support_status.startswith("stale")


@pytest.fixture
def no_wait(monkeypatch):
    async def sleep(_):
        return None
    monkeypatch.setattr("neraium_poly.research.phase14.discovery.asyncio.sleep", sleep)


def client(*, oversized=False, status=200):
    tags = [{"id": "42", "slug": "weather"}, {"id": "97", "slug": "crypto"}]
    events = [{"id": "e", "tags": [{"id": "42", "slug": "weather"}],
               "markets": [raw("w1"), raw("w2")]},
              {"id": "ec", "tags": [{"id": "97", "slug": "crypto"}], "markets": [raw("c1")]}]
    def handle(request):
        assert request.method == "GET" and request.url.host == "gamma-api.polymarket.com"
        if status != 200:
            return httpx.Response(status, json={"error": "CONTROLLED"})
        if request.url.path == "/tags":
            return httpx.Response(200, json=tags)
        if request.url.path.startswith("/tags/slug"):
            return httpx.Response(404, json={})
        assert request.url.path == "/events"
        if oversized:
            return httpx.Response(200, content=b" "*(5*1024**2))
        return httpx.Response(200, json=events)
    return httpx.AsyncClient(transport=httpx.MockTransport(handle))


async def test_bounded_category_round_robin_discovery_retains_real_provider_tag_ids(no_wait):
    http = client()
    discovery = DomainDiscovery(client=http, clock=lambda: NOW, max_requests=8)
    try:
        result = await discovery.discover(max_markets=2)
        assert len(result["markets"]) == 2
        assert {m.domain for m in result["markets"]} == {"weather", "crypto"}
        report = result["report"]
        assert report["requests"] <= 8 and report["selected_markets"] == 2
        assert report["actual_tag_ids"] == {"weather": "42", "crypto": "97"}
        assert report["independent_forecasts"] == report["executable_markets_verified"] == 0
        assert report["universe_complete"] is False
        assert all(r["sha256"] and r["received_at"] == NOW.isoformat() for r in result["responses"])
        assert all(m.available_at == NOW for m in result["markets"])
    finally:
        await http.aclose()


@pytest.mark.parametrize("status", [429, 503])
async def test_rate_failure_does_not_create_markets_or_retry_forever(no_wait, status):
    http = client(status=status)
    d = DomainDiscovery(client=http, clock=lambda: NOW)
    try:
        value = await d.discover()
        assert not value["markets"] and value["report"]["requests"] == 1
        assert value["report"]["errors"]
    finally:
        await http.aclose()


async def test_response_budget_rejects_oversized_metadata(no_wait):
    http = client(oversized=True)
    d = DomainDiscovery(client=http, clock=lambda: NOW)
    try:
        value = await d.discover()
        assert not value["markets"]
        assert any("byte_budget" in e for e in value["report"]["errors"])
    finally:
        await http.aclose()


@pytest.mark.parametrize("kwargs", [{"max_requests": 17}, {"byte_budget": 17*1024**2}, {"rate": 3}])
def test_unbounded_configuration_rejects(kwargs):
    with pytest.raises(ValueError):
        DomainDiscovery(**kwargs)


def test_prices_are_not_hidden_classification_features():
    before = classify_market(raw(tags=[{"slug": "weather"}], outcomePrices='["0.1","0.9"]'), NOW)
    after = classify_market(raw(tags=[{"slug": "weather"}], outcomePrices='["0.9","0.1"]'), NOW)
    assert before == after


async def test_exact_response_bytes_are_retained_for_source_hash_replay(no_wait):
    import hashlib
    http = client()
    d = DomainDiscovery(client=http, clock=lambda: NOW, max_requests=2)
    try:
        value = await d.discover()
        assert value["responses"]
        for row in value["responses"]:
            assert hashlib.sha256(row["raw_utf8"].encode()).hexdigest() == row["sha256"]
    finally:
        await http.aclose()
