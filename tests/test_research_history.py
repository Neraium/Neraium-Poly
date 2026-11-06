"""Controlled transport tests, not actual historical strategy evidence."""

import json
from datetime import timedelta

import httpx
import pytest
from neraium_poly.contracts import OrderBookSnapshot, PriceLevel
from neraium_poly.data import EventStore
from neraium_poly.research.history import AcquisitionLimit, HistoryPipeline, completeness_report, load_bundle


def raw_market(now, number=1, parent=None):
    return {
        "id": str(number),
        "question": f"Test outcome {number}?",
        "conditionId": f"condition{number}",
        "events": [{"id": f"event{number}", "parentEventId": parent, "tags": [{"label": "controlled"}]}],
        "createdAt": (now - timedelta(days=3)).isoformat(),
        "closedTime": (now - timedelta(hours=1)).isoformat(),
        "closed": True,
        "clobTokenIds": json.dumps([f"t{number}", f"n{number}"]),
        "outcomes": '["Yes","No"]',
        "outcomePrices": '["1","0"]',
        "description": "Explicit controlled test rules",
        "resolutionSource": "https://test.example/rules",
        "volume": "100",
        "liquidity": "0",
    }


def native(now, number=1):
    return {
        "condition_id": f"condition{number}",
        "status": "resolved",
        "extended_review": False,
        "was_disputed": False,
        "new_version_q": False,
        "transaction_hash": f"test-tx{number}",
        "market_type": "BINARY",
        "resolution_source": "reported",
        "payouts": [1000000, 0],
        "resolved_at": (now - timedelta(hours=1)).isoformat(),
    }


def transport(now, markets=None, resolution_transform=None, price_rows=None):
    markets = markets if markets is not None else [raw_market(now, 1), raw_market(now, 2)]

    def handler(request):
        if request.url.host == "gamma-api.polymarket.com":
            return httpx.Response(200, json=markets)
        if request.url.path == "/v2/resolutions":
            rows = [native(now, int(r["id"])) for r in markets]
            if resolution_transform:
                rows = [resolution_transform(r) for r in rows]
            return httpx.Response(200, json={"data": rows})
        if request.url.path == "/v2/prices-history":
            rows = (
                price_rows
                if price_rows is not None
                else [
                    {
                        "timestamp": int((now - timedelta(days=1)).timestamp()),
                        "price": 0.4,
                        "resolution_seconds": 43200,
                    },
                    {
                        "timestamp": int((now - timedelta(minutes=59)).timestamp()),
                        "price": 0.9,
                        "resolution_seconds": 43200,
                    },
                    {
                        "timestamp": int((now - timedelta(minutes=1)).timestamp()),
                        "price": 1,
                        "resolution_seconds": 0,
                    },
                ]
            )
            return httpx.Response(
                200, json={"data": rows, "pagination": {"has_more": False, "next_cursor": None}}
            )
        if request.url.host == "clob.polymarket.com":
            n = int(request.url.path.rsplit("condition", 1)[-1])
            return httpx.Response(
                200,
                json={
                    "condition_id": f"condition{n}",
                    "closed": True,
                    "tokens": [
                        {"token_id": f"t{n}", "outcome": "Yes", "winner": True, "price": 0},
                        {"token_id": f"n{n}", "outcome": "No", "winner": False, "price": 1},
                    ],
                },
            )
        raise AssertionError(str(request.url))

    return httpx.MockTransport(handler)


async def acquire(tmp_path, now, **kwargs):
    client = httpx.AsyncClient(transport=transport(now, **kwargs))
    pipeline = HistoryPipeline(tmp_path, client=client, clock=lambda: now, min_interval=0, max_market_rows=2)
    try:
        bundle = await pipeline.acquire(max_events=2, max_history_requests=2, max_context_requests=0)
        return bundle, pipeline
    finally:
        await client.aclose()


async def test_authentic_provenance_shapes_availability_and_roundtrip(tmp_path, now):
    bundle, pipeline = await acquire(tmp_path, now)
    assert len(bundle.events) == 2 and all(e.outcome_verified and e.outcome == 1 for e in bundle.events)
    assert len(bundle.prices) == 2
    assert all(
        p.available_at == now and p.timestamp < now and p.availability_basis == "collected_now"
        for p in bundle.prices
    )
    assert all(e.available_at == now for e in bundle.events)
    assert load_bundle(tmp_path) == bundle
    report = completeness_report(bundle)
    assert report["verified_outcome_events"] == 2
    assert report["certifiable_independent_events"] == 0
    assert not report["certification_split_feasible"]
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    assert manifest["requests"] == 4 and pipeline.requests == 4
    assert all(x["method"] == "GET" and x["sha256"] for x in manifest["raw"])


async def test_closed_and_terminal_price_alone_never_establish_outcome(tmp_path, now):
    bundle, _ = await acquire(tmp_path, now, resolution_transform=lambda r: {**r, "status": "proposed"})
    assert all(not e.outcome_verified and e.outcome is None for e in bundle.events)


async def test_disputed_or_fractional_settlement_withheld(tmp_path, now):
    bundle, _ = await acquire(
        tmp_path, now, resolution_transform=lambda r: {**r, "was_disputed": True, "payouts": [500000, 500000]}
    )
    assert not any(e.outcome_verified for e in bundle.events)


async def test_correlated_parent_events_are_not_independent_samples(tmp_path, now):
    bundle, _ = await acquire(
        tmp_path, now, markets=[raw_market(now, 1, parent="match1"), raw_market(now, 2, parent="match1")]
    )
    assert len(bundle.events) == 1
    assert completeness_report(bundle)["distinct_event_groups"] == 1


async def test_explicit_winner_flags_corroborate_legacy_resolution_without_using_price(tmp_path, now):
    def legacy(row):
        row.pop("payouts")
        row.pop("resolved_at")
        row["price"] = "69"
        return row

    bundle, _ = await acquire(tmp_path, now, resolution_transform=legacy)
    assert all(e.outcome_verified and e.outcome == 1 and e.settlement_at is None for e in bundle.events)
    assert not completeness_report(bundle)["certification_split_feasible"]


async def test_terminal_and_postclose_price_rows_are_excluded(tmp_path, now):
    bundle, _ = await acquire(tmp_path, now)
    assert all(p.probability == 0.4 for p in bundle.prices)
    assert "terminal_or_postclose_chart_points_excluded" in bundle.deficiencies


async def test_future_history_is_not_accepted(tmp_path, now):
    bundle, _ = await acquire(
        tmp_path, now, price_rows=[{"timestamp": int((now + timedelta(days=1)).timestamp()), "price": 0.5}]
    )
    assert not bundle.prices
    assert any("price_history_unavailable" in reason for reason in bundle.deficiencies)


async def test_normalized_evidence_tampering_detected(tmp_path, now):
    await acquire(tmp_path, now)
    p = tmp_path / "bundle.json"
    body = json.loads(p.read_text())
    body["prices"][0]["probability"] = 0.6
    p.write_text(json.dumps(body))
    with pytest.raises(ValueError, match="normalized"):
        load_bundle(tmp_path)


async def test_raw_payload_tampering_detected(tmp_path, now):
    await acquire(tmp_path, now)
    raw = next((tmp_path / "raw").iterdir())
    raw.write_text("{}")
    with pytest.raises(ValueError, match="raw provenance"):
        load_bundle(tmp_path)


async def test_request_budget_stops_without_inventing_missing_data(tmp_path, now):
    async with httpx.AsyncClient(transport=transport(now)) as client:
        pipeline = HistoryPipeline(
            tmp_path, client=client, clock=lambda: now, min_interval=0, max_market_rows=2, max_requests=1
        )
        with pytest.raises(AcquisitionLimit, match="request budget"):
            await pipeline.acquire(max_events=2, max_history_requests=2)
    assert not (tmp_path / "bundle.json").exists()


async def test_byte_budget_prevents_large_response(tmp_path, now):
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, content=b"x" * 2048))
    ) as client:
        pipeline = HistoryPipeline(
            tmp_path, client=client, clock=lambda: now, min_interval=0, max_bytes=1024, max_market_rows=1
        )
        with pytest.raises(AcquisitionLimit, match="byte budget"):
            await pipeline.acquire(max_events=1)


async def test_rate_limit_retry_after_is_respected(tmp_path, now):
    delays = []
    calls = 0

    async def sleep(delay):
        delays.append(delay)

    def handler(request):
        nonlocal calls
        calls += 1
        return (
            httpx.Response(429, headers={"Retry-After": "2"}, json={"error": "busy"})
            if calls == 1
            else httpx.Response(200, json=[])
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        pipeline = HistoryPipeline(
            tmp_path, client=client, clock=lambda: now, min_interval=0, sleep=sleep, max_market_rows=1
        )
        bundle = await pipeline.acquire(max_events=1, max_history_requests=0, max_context_requests=0)
        assert not bundle.events and 2 in delays and calls == 2


async def test_long_retry_delay_holds_instead_of_violating_limit(tmp_path, now):
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(429, headers={"Retry-After": "90"}, json={}))
    ) as client:
        pipeline = HistoryPipeline(
            tmp_path, client=client, clock=lambda: now, min_interval=0, max_market_rows=1
        )
        with pytest.raises(AcquisitionLimit, match="retry delay"):
            await pipeline.acquire(max_events=1)


def test_import_actual_archive_preserves_event_and_availability_time(tmp_path, now):
    archive = tmp_path / "archive.sqlite"
    store = EventStore(archive)
    book = OrderBookSnapshot(
        id="controlledbook",
        timestamp=now - timedelta(seconds=1),
        available_at=now,
        source="https://clob.polymarket.com",
        market_id="m",
        token_id="t",
        bids=(PriceLevel(price=0.3, size=10),),
        asks=(PriceLevel(price=0.4, size=10),),
    )
    store.append(book)
    store.close()
    pipeline = HistoryPipeline(tmp_path / "evidence")
    try:
        assert pipeline.import_books(archive) == (book,)
    finally:
        import asyncio

        asyncio.run(pipeline.close())


async def test_context_is_independent_but_not_backdated(tmp_path, now):
    markets = [raw_market(now, 1)]
    markets[0]["description"] = "METAR temperature station EGLC"
    original = transport(now, markets=markets)

    def handler(request):
        if request.url.host == "aviationweather.gov":
            return httpx.Response(
                200,
                json=[
                    {"icaoId": "EGLC", "obsTime": int((now - timedelta(days=1)).timestamp()), "temp": 10.5}
                ],
            )
        return original.handle_request(request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        p = HistoryPipeline(tmp_path, client=client, clock=lambda: now, min_interval=0, max_market_rows=1)
        b = await p.acquire(max_events=1, max_history_requests=0, max_context_requests=1)
    assert b.context[0].independent and b.context[0].available_at == now
    assert b.context[0].availability_basis == "collected_now"
    assert not completeness_report(b)["certification_split_feasible"]


async def test_partial_discovery_failure_is_explicit_not_exchange_completeness(tmp_path, now):
    original = transport(now)

    def handler(request):
        if request.url.host == "gamma-api.polymarket.com" and int(request.url.params.get("offset", "0")) > 0:
            return httpx.Response(422, json={"error": "offset limit"})
        return original.handle_request(request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        p = HistoryPipeline(tmp_path, client=client, clock=lambda: now, min_interval=0, max_market_rows=200)
        # Force a full first page to exercise a second source page.
        markets = [raw_market(now, i) for i in range(1, 101)]

        def paged(request):
            if request.url.host == "gamma-api.polymarket.com":
                return (
                    httpx.Response(200, json=markets)
                    if request.url.params.get("offset") == "0"
                    else httpx.Response(422, json={"error": "offset limit"})
                )
            if request.url.path == "/v2/resolutions":
                return httpx.Response(200, json={"data": []})
            return httpx.Response(200, json={"data": []})

        await client.aclose()
    async with httpx.AsyncClient(transport=httpx.MockTransport(paged)) as client:
        p = HistoryPipeline(tmp_path, client=client, clock=lambda: now, min_interval=0, max_market_rows=200)
        b = await p.acquire(max_events=150, max_history_requests=0, max_context_requests=0)
    assert len(b.events) == 100
    assert "discovery_page_unavailable:HTTPStatusError" in b.deficiencies
    assert not completeness_report(b)["certification_split_feasible"]


async def test_label_availability_follows_resolution_fetch_not_metadata_receipt(tmp_path, now):
    current = [now]
    original = transport(now)

    def handler(request):
        if request.url.path == "/v2/resolutions":
            current[0] += timedelta(seconds=10)
        return original.handle_request(request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        p = HistoryPipeline(
            tmp_path, client=client, clock=lambda: current[0], min_interval=0, max_market_rows=2
        )
        b = await p.acquire(max_events=2, max_history_requests=0, max_context_requests=0)
    assert all(e.available_at == now + timedelta(seconds=10) for e in b.events)


async def test_event_first_can_assemble_200_verified_groups_without_claiming_certification(tmp_path, now):
    markets = [raw_market(now, i) for i in range(1, 206)]

    def handler(request):
        if request.url.path == "/events":
            offset = int(request.url.params["offset"])
            limit = int(request.url.params["limit"])
            return httpx.Response(
                200,
                json=[
                    {"id": f"event{r['id']}", "tags": [{"label": "controlled"}], "markets": [r]}
                    for r in markets[offset : offset + limit]
                ],
            )
        if request.url.path == "/v2/resolutions":
            ids = [int(c.replace("condition", "")) for c in request.url.params["condition"].split(",")]
            return httpx.Response(200, json={"data": [native(now, i) for i in ids]})
        raise AssertionError(str(request.url))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        p = HistoryPipeline(tmp_path, client=client, clock=lambda: now, min_interval=0, max_requests=100)
        b = await p.acquire(max_events=205, max_history_requests=0, max_context_requests=0, event_first=True)
    report = completeness_report(b)
    assert report["verified_outcome_events"] == 205
    assert not report["certification_split_feasible"]
    assert report["certifiable_independent_events"] == 0
    assert load_bundle(tmp_path) == b


async def test_event_first_named_binary_tokens_are_not_renamed_or_inferred_from_price(tmp_path, now):
    market = raw_market(now, 1)
    market["outcomes"] = '["Up","Down"]'
    market["outcomePrices"] = '["0","1"]'

    def handler(request):
        if request.url.path == "/events":
            return httpx.Response(200, json=[{"id": "event1", "markets": [market]}])
        return httpx.Response(200, json={"data": [native(now)]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        p = HistoryPipeline(tmp_path, client=client, clock=lambda: now, min_interval=0, max_requests=10)
        b = await p.acquire(max_events=1, max_history_requests=0, max_context_requests=0, event_first=True)
    assert b.events[0].token_id == "t1"
    assert b.events[0].outcome == 1 and b.events[0].outcome_verified


async def test_nullable_type_requires_winner_corroboration_and_transaction_ref(tmp_path, now):
    bundle, _ = await acquire(
        tmp_path / "valid",
        now,
        resolution_transform=lambda r: {k: v for k, v in r.items() if k != "market_type"},
    )
    assert all(e.outcome_verified for e in bundle.events)

    def no_tx(row):
        row.pop("market_type")
        row["transaction_hash"] = ""
        return row

    rejected, _ = await acquire(tmp_path / "missing-tx", now, resolution_transform=no_tx)
    assert not any(e.outcome_verified for e in rejected.events)


async def test_nullable_type_with_conflicting_payout_and_winner_withheld(tmp_path, now):
    def conflict(row):
        row.pop("market_type")
        row["payouts"] = [0, 1000000]
        return row

    bundle, _ = await acquire(tmp_path, now, resolution_transform=conflict)
    assert not any(e.outcome_verified for e in bundle.events)


async def test_known_nonbinary_type_never_becomes_binary_from_winner_flags(tmp_path, now):
    bundle, _ = await acquire(
        tmp_path, now, resolution_transform=lambda r: {**r, "market_type": "INCREMENTAL_NEGRISK"}
    )
    assert not any(e.outcome_verified for e in bundle.events)


@pytest.fixture
def publisher_archive(tmp_path, monkeypatch, now):
    """Controlled rows only; publisher fixtures never qualify strategy validation."""
    import hashlib
    from types import SimpleNamespace

    from neraium_poly.research import public_archive

    file = tmp_path / 'sample.parquet'
    file.write_bytes(b'controlled test-only parquet substitute')
    (tmp_path / 'manifest.json').write_text(json.dumps({'files': [{
        'file': file.name, 'sha256': hashlib.sha256(file.read_bytes()).hexdigest(),
        'bytes': file.stat().st_size, 'final_url': 'https://test.example/publisher',
        'retrieved_at': now.isoformat(),
    }]}))
    rows = [{'market_slug': 'test-market', 'token_id': 'test-token', 'outcome': 'Up',
             'captured_at': now - timedelta(days=1), 'market_end_at': now,
             'bid_prices': [.4], 'bid_sizes': [2.], 'ask_prices': [.6], 'ask_sizes': [3.],
             'winner': 'Up', 'is_winning_outcome': True}]

    class Reader:
        metadata = SimpleNamespace(num_rows=1000)

        def iter_batches(self, batch_size, columns):
            assert batch_size <= 512
            assert 'winner' not in columns and 'is_winning_outcome' not in columns
            yield SimpleNamespace(to_pylist=lambda: rows)

    monkeypatch.setattr(public_archive, '_reader', lambda path: Reader())
    return tmp_path, rows


def test_publisher_archive_capture_is_not_exchange_time_or_verified_label(publisher_archive):
    from neraium_poly.research.public_archive import audit_public_archive, iter_public_snapshots

    directory, _ = publisher_archive
    snapshot = next(iter_public_snapshots(directory))
    assert snapshot.retrieved_at > snapshot.captured_at
    assert not hasattr(snapshot, 'timestamp') and not hasattr(snapshot, 'available_at')
    assert not hasattr(snapshot, 'winner') and not hasattr(snapshot, 'outcome_verified')
    report = audit_public_archive(directory)
    assert report['source_total_rows'] == 1000 and report['sampled_rows'] == 1
    assert report['official_event_mapping_count'] == report['certification_eligible_events'] == 0


def test_publisher_archive_quality_and_hard_bounds(publisher_archive):
    from neraium_poly.research.public_archive import audit_public_archive

    directory, rows = publisher_archive
    rows[0].update(bid_prices=[.6, .7], bid_sizes=[0., 2.], ask_prices=[.5, .4], ask_sizes=[1., 1.])
    report = audit_public_archive(directory)
    assert report['crossed_or_locked'] == 1
    assert report['unsorted_ladders'] == 1 and report['invalid_or_zero_levels'] == 1
    for kwargs in [{'max_rows': 5001}, {'batch_size': 513}, {'max_rows': 0}]:
        with pytest.raises(ValueError, match='Audit limits'):
            audit_public_archive(directory, **kwargs)


def test_publisher_archive_rejects_tampering_lengths_and_naive_times(publisher_archive):
    from neraium_poly.research.public_archive import audit_public_archive

    directory, rows = publisher_archive
    rows[0]['bid_sizes'] = []
    with pytest.raises(ValueError, match='lengths'):
        audit_public_archive(directory)
    rows[0]['bid_sizes'] = [1.]
    rows[0]['captured_at'] = '2026-01-01T00:00:00'
    with pytest.raises(ValueError, match='timezone'):
        audit_public_archive(directory)
    (directory / 'sample.parquet').write_bytes(b'tampered')
    with pytest.raises(ValueError, match='checksum'):
        audit_public_archive(directory)
