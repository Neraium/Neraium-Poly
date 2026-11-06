"""Controlled official-shape responses, not actual exchange evidence."""

from datetime import timedelta

import httpx
from neraium_poly.data import EventStore
from neraium_poly.experimental.fees import AuditedFeeAdapter, merge_fee_observations


def test_fee_merge_cannot_hide_higher_fresh_cost(now):
    def fee(rate, at):
        return {
            "fee_rate": rate,
            "observed_at": at.isoformat(),
            "source": "https://clob.polymarket.com",
            "reference": "controlled-test",
        }

    old = fee(0.01, now - timedelta(seconds=30))
    high = fee(0.03, now)
    assert merge_fee_observations({"token": high}, {"token": old}, now=now)["token"] == high
    assert merge_fee_observations({"token": old}, {"token": high}, now=now)["token"] == high
    assert (
        merge_fee_observations({"token": fee(0.1, now - timedelta(seconds=301))}, {"token": old}, now=now)[
            "token"
        ]
        == old
    )
    assert not merge_fee_observations({"token": fee(0, now + timedelta(seconds=1))}, now=now)


async def test_actual_shaped_fee_responses_and_hash_basis_are_preserved(tmp_path):
    store = EventStore(tmp_path / "events.sqlite")
    parent = {
        "primary_token_id": "controlled-a",
        "secondary_token_id": "controlled-b",
        "condition_id": "controlled-condition",
    }
    details = {
        "c": "controlled-condition",
        "t": [{"t": "controlled-a"}, {"t": "controlled-b"}],
        "fd": {"to": True, "e": 1, "r": 0},
    }

    def handle(request):
        return httpx.Response(200, json=parent if "markets-by-token" in request.url.path else details)

    adapter = AuditedFeeAdapter(
        store, lambda: True, client=httpx.AsyncClient(transport=httpx.MockTransport(handle))
    )
    try:
        fee = await adapter.observed_fee("controlled-a")
        assert fee["fee_rate"] == 0 and len(fee["raw_response_ids"]) == 2
        records = store.replay(kind="PublicFeeResponse")
        assert len(records) == 2 and all(
            r["record"]["hash_basis"] == "canonical_json_payload_not_HTTP_bytes" for r in records
        )
        await adapter.observed_fee("controlled-a")
        assert len(store.replay(kind="PublicFeeResponse")) == 2
        assert len(store.replay(kind="FeeObservation")) == 2
    finally:
        await adapter.close()
        store.close()


async def test_unknown_fee_curve_cannot_be_assumed_zero(tmp_path):
    store = EventStore(tmp_path / "events.sqlite")
    adapter = AuditedFeeAdapter(
        store,
        lambda: True,
        client=httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={}))),
    )
    try:
        assert await adapter.observed_fee("controlled-a") is None
    finally:
        await adapter.close()
        store.close()
