"""Synthetic API fixtures exercise boundaries, never certify a real strategy."""

import json
from datetime import timedelta

import httpx
import pytest
from neraium_poly.data.operational import OperationalPolymarketAdapter, build_statistical_relationships
from neraium_poly.data.polymarket import normalize_market


def raw_market(i=1):
    return {
        "id": str(i),
        "eventId": "event-1",
        "question": f"Outcome {i}?",
        "clobTokenIds": json.dumps([f"{i}1", f"{i}2"]),
        "outcomes": '["Yes","No"]',
        "outcomePrices": '["0.4","0.6"]',
        "active": True,
        "closed": False,
        "description": "Verified externally supplied rules",
        "resolutionSource": "https://oracle.example/rules",
        "conditionId": f"condition-{i}",
    }


def adapter(handler, now, retries=2):
    async def noop(_):
        pass

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return OperationalPolymarketAdapter(
        client, retries=retries, sleep=noop, min_interval=0, clock=lambda: now
    )


async def test_discovery_more_than_ten_and_rotation(now):
    requests = []

    def handler(request):
        requests.append(request)
        offset = int(request.url.params["offset"])
        limit = int(request.url.params["limit"])
        return httpx.Response(
            200, json=[raw_market(i) for i in range(offset + 1, min(offset + limit, 65) + 1)]
        )

    a = adapter(handler, now)
    first = await a.discover_bounded(max_markets=50, page_size=20, max_pages=4)
    assert first.scanned_count == 50 and len(first.markets) == 100 and first.truncated
    assert first.next_offset == 50
    second = await a.discover_bounded(max_markets=50, page_size=20, max_pages=4)
    assert second.scanned_count == 15 and len(second.markets) == 30 and not second.truncated
    assert second.next_offset == 0
    assert len(requests) == 4
    await a.client.aclose()


async def test_discovery_rate_limit_retry_and_invalid_rows(now):
    calls = []

    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(429, headers={"Retry-After": "1"})
        return httpx.Response(200, json=[raw_market(), {"id": "bad"}, "bad"])

    a = adapter(handler, now)
    result = await a.discover_bounded(max_markets=10, page_size=10, max_pages=1)
    assert len(calls) == 2 and result.scanned_count == 2 and len(result.markets) == 2
    assert len(result.errors) == 2 and result.truncated
    await a.client.aclose()


async def test_discovery_bounds_and_duplicate_markets(now):
    a = adapter(lambda r: httpx.Response(200, json=[raw_market(), raw_market()]), now)
    with pytest.raises(ValueError):
        await a.discover_bounded(max_markets=1000)
    result = await a.discover_bounded(max_markets=10, page_size=10, max_pages=1)
    assert result.scanned_count == 1 and len(result.markets) == 2
    await a.client.aclose()


def fee_handler(details=None, parent=None):
    def handler(request):
        assert request.method == "GET"
        if request.url.path.startswith("/markets-by-token/"):
            return httpx.Response(
                200,
                json=parent or {"condition_id": "c1", "primary_token_id": "11", "secondary_token_id": "12"},
            )
        if request.url.path.startswith("/clob-markets/"):
            return httpx.Response(
                200,
                json=details
                or {
                    "c": "c1",
                    "t": [{"t": "11", "o": "Yes"}, {"t": "12", "o": "No"}],
                    "mbf": 1000,
                    "tbf": 1000,
                    "fd": {"r": 0.04, "e": 1, "to": True},
                },
            )
        raise AssertionError("Unexpected endpoint")

    return handler


async def test_fee_curve_not_legacy_basis_points(now):
    a = adapter(fee_handler(), now)
    model = await a.fee_model("11")
    assert model.protocol_rate == 0.04
    assert model.fee_per_share(0.5) == pytest.approx(0.01)
    assert model.effective_notional_bound() == 0.04
    await a.client.aclose()


@pytest.mark.parametrize(
    "fee",
    [
        {"r": 0.04, "e": 2, "to": True},
        {"r": 0.04, "e": 1, "to": False},
        {"r": -1, "e": 1, "to": True},
        {"r": True, "e": 1, "to": True},
        {"r": "nan", "e": 1, "to": True},
        {"r": 0.04, "to": True},
    ],
)
async def test_unsupported_fee_curve_rejected(now, fee):
    a = adapter(fee_handler(details={"c": "c1", "t": [{"t": "11"}], "fd": fee}), now)
    assert await a.fee_model("11") is None
    await a.client.aclose()


async def test_unknown_fee_and_identity_mismatch(now):
    a = adapter(lambda r: httpx.Response(404), now)
    assert await a.fee_model("11") is None
    await a.client.aclose()
    a = adapter(
        fee_handler(parent={"condition_id": "c1", "primary_token_id": "13", "secondary_token_id": "14"}), now
    )
    assert await a.fee_model("11") is None
    await a.client.aclose()


def resolution_handler(now, changes=None, raw_changes=None, parent_changes=None):
    raw = raw_market()
    raw.update(closed=True, active=False, umaResolutionStatus="resolved")
    raw.update(raw_changes or {})
    row = {
        "condition_id": "condition-1",
        "status": "resolved",
        "extended_review": False,
        "was_disputed": False,
        "new_version_q": False,
        "was_arbitrated": False,
        "resolution_source": "reported",
        "market_type": "BINARY",
        "reporter": "UMA_OO",
        "transaction_hash": "0xresolution",
        "resolved_at": (now - timedelta(seconds=30)).isoformat(),
        "last_update_timestamp": (now - timedelta(seconds=20)).isoformat(),
        "payouts": [1000000, 0],
    }
    row.update(changes or {})
    parent = {"condition_id": "condition-1", "primary_token_id": "11", "secondary_token_id": "12"}
    parent.update(parent_changes or {})

    def handler(request):
        assert request.method == "GET"
        if request.url.path == "/markets/1":
            return httpx.Response(200, json=raw)
        if request.url.path == "/markets-by-token/11":
            return httpx.Response(200, json=parent)
        if request.url.path == "/v2/resolutions":
            assert request.url.params["condition"] == "condition-1"
            return httpx.Response(200, json={"data": [row]})
        raise AssertionError(str(request.url))

    return handler


async def test_final_resolution_is_bound_to_rules_identity_and_payout(now):
    market = normalize_market(raw_market(), now)[0]
    a = adapter(resolution_handler(now), now)
    observation = await a.settlement(market)
    assert observation is not None
    assert observation.market_id == "1" and observation.token_id == "11" and observation.event_id == "event-1"
    assert observation.payout == 1 and observation.outcome_index == 0
    assert not observation.rules_reviewed
    assert observation.timestamp == now - timedelta(seconds=30)
    await a.client.aclose()


@pytest.mark.parametrize(
    "changes",
    [
        {"status": "proposed"},
        {"status": "disputed"},
        {"extended_review": True},
        {"was_disputed": True},
        {"new_version_q": True},
        {"was_arbitrated": True},
        {"resolution_source": "derived"},
        {"payouts": [500000, 500000]},
        {"payouts": [1, 0]},
        {"payouts": [True, False]},
        {"condition_id": "wrong"},
        {"market_type": "ATOMIC_NEGRISK"},
        {"transaction_hash": ""},
        {"reporter": "unknown"},
    ],
)
async def test_unresolved_ambiguous_disputed_or_unsupported_settlement_rejected(now, changes):
    market = normalize_market(raw_market(), now)[0]
    a = adapter(resolution_handler(now, changes), now)
    assert await a.settlement(market) is None
    await a.client.aclose()


@pytest.mark.parametrize(
    "changes",
    [
        {"description": "Rules changed"},
        {"resolutionSource": "different-source"},
        {"closed": False},
        {"umaResolutionStatus": "proposed"},
        {"eventId": "another-event"},
    ],
)
async def test_resolution_metadata_must_match_reviewed_market(now, changes):
    market = normalize_market(raw_market(), now)[0]
    a = adapter(resolution_handler(now, raw_changes=changes), now)
    assert await a.settlement(market) is None
    await a.client.aclose()


async def test_future_resolution_and_wrong_condition_rejected(now):
    market = normalize_market(raw_market(), now)[0]
    a = adapter(resolution_handler(now, {"resolved_at": (now + timedelta(seconds=1)).isoformat()}), now)
    assert await a.settlement(market) is None
    await a.client.aclose()
    a = adapter(resolution_handler(now, parent_changes={"condition_id": "different"}), now)
    assert await a.settlement(market) is None
    await a.client.aclose()


def test_relationships_are_statistical_bounded_deterministic_hypotheses(now):
    markets = [m for i in range(1, 15) for m in normalize_market(raw_market(i), now)]
    edges, tokens = build_statistical_relationships(markets, now, max_pairs=10)
    assert len(edges) == 10 and len(tokens) == 14
    assert all(e.kind == "statistical" and not e.rule_verified for e in edges)
    assert all(len(e.market_ids) == 2 for e in edges)
    assert edges == build_statistical_relationships(markets, now, max_pairs=10)[0]
    # ID remains stable; coordinator retains original edge's availability time.
    assert (
        edges[0].id
        == build_statistical_relationships(markets, now + timedelta(seconds=1), max_pairs=10)[0][0].id
    )


def test_relationships_reject_ambiguous_and_future_outcomes(now):
    markets = list(normalize_market(raw_market(1), now)) + list(normalize_market(raw_market(2), now))
    duplicate = markets[0].model_copy(update={"token_id": "ambiguous", "id": "ambiguous"})
    edges, tokens = build_statistical_relationships(markets + [duplicate], now)
    assert not edges and "1" not in tokens
    edges, _ = build_statistical_relationships(
        [m.model_copy(update={"available_at": now + timedelta(seconds=1)}) for m in markets], now
    )
    assert not edges
