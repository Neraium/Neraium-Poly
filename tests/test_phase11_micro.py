"""Controlled fixtures only: no synthetic input is installed in real research artifacts."""

import hashlib
import json
from datetime import UTC, datetime, timedelta

import pytest
from neraium_poly.contracts import MarketSnapshot, OrderBookSnapshot, PriceLevel
from neraium_poly.data import EventStore
from neraium_poly.experimental.fees import FeeObservation, PublicFeeResponse
from neraium_poly.research.archive import BookDelta, content_hash
from neraium_poly.research.phase11.contracts import ResearchObservation
from neraium_poly.research.phase11.dataset import extract_dataset, load_dataset
from neraium_poly.research.phase11.microstructure import causal_features, depth_quote, execution_scenarios

NOW = datetime(2026, 11, 6, 3, tzinfo=UTC)


def quote(seconds=0, *, bid=0.4, ask=0.41, size=1000, source_delay=0):
    at = NOW + timedelta(seconds=seconds)
    return OrderBookSnapshot(
        id=f"controlled-{seconds}-{bid}-{size}",
        timestamp=at - timedelta(seconds=source_delay),
        available_at=at,
        source="https://clob.polymarket.com",
        market_id="controlled-m",
        token_id="controlled-t",
        bids=(PriceLevel(price=bid, size=size),),
        asks=(PriceLevel(price=ask, size=size),),
    )


def metadata(seconds=-1):
    at = NOW + timedelta(seconds=seconds)
    return MarketSnapshot(
        timestamp=at,
        available_at=at,
        source="https://gamma-api.polymarket.com",
        market_id="controlled-m",
        token_id="controlled-t",
        event_id="controlled-event",
        question="CONTROLLED fixture",
        probability=0.4,
        status="active",
        resolution_rules="CONTROLLED",
        resolution_source="https://controlled.invalid",
        min_order_size=1,
    )


def observation(seconds=0, **kw):
    b = quote(seconds, **kw)
    return ResearchObservation(
        book=b,
        market=metadata(),
        fee={
            "fee_rate": 0.02,
            "observed_at": b.available_at.isoformat(),
            "source": "https://clob.polymarket.com",
            "reference": "controlled-only",
        },
    )


def test_extract_fixed_source_window_asof_context_and_lossless_delta(tmp_path):
    store = EventStore(tmp_path / "source.sqlite")
    try:
        base = quote()
        store.append(base)
        store.append(metadata(5))  # Future to original quote; cannot backfill.
        changed = quote(10, bid=0.39)
        store.append(
            BookDelta(
                timestamp=changed.timestamp,
                available_at=changed.available_at,
                source=changed.source,
                market_id=changed.market_id,
                token_id=changed.token_id,
                exchange=changed.exchange,
                observed_book_id=changed.id,
                full_book_id=base.id,
                content_sha256=content_hash(changed),
                sequence=0,
                complete=True,
                bids_changed=((0.4, 0), (0.39, 1000)),
            )
        )
        high = store.connection.execute("select max(rowid) from events").fetchone()[0]
        store.append(quote(20))
        manifest = extract_dataset(
            tmp_path / "source.sqlite", tmp_path / "dataset", high_water=high, min_free_bytes=0
        )
        rows = load_dataset(tmp_path / "dataset")
        assert len(rows) == 2 and rows[0].market is None and rows[1].market is not None
        assert rows[1].book == changed
        assert manifest["source_high_water"] == high
        assert manifest["completeness"]["point_in_time_market_metadata_unavailable"] == 1
        assert all(r.fee is None for r in rows)
        with pytest.raises(ValueError, match="new dataset"):
            extract_dataset(tmp_path / "source.sqlite", tmp_path / "dataset", min_free_bytes=0)
    finally:
        store.close()


def test_observed_fee_availability_ttl_and_raw_provenance(tmp_path):
    store = EventStore(tmp_path / "source.sqlite")
    try:
        store.append(metadata())
        refs = []
        for n in range(2):
            payload = {"controlled": n}
            h = hashlib.sha256(
                json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
            raw = PublicFeeResponse(
                timestamp=NOW,
                available_at=NOW,
                source="https://clob.polymarket.com",
                url="https://clob.polymarket.com/controlled",
                content_sha256=h,
                payload=payload,
            )
            store.append(raw)
            refs.append(raw.id)
        store.append(
            FeeObservation(
                timestamp=NOW,
                available_at=NOW,
                source="https://clob.polymarket.com",
                token_id="controlled-t",
                fee_rate=0.02,
                raw_response_ids=tuple(refs),
            )
        )
        for second in (-0.5, 1, 60, 301):
            store.append(quote(second))
        extract_dataset(tmp_path / "source.sqlite", tmp_path / "dataset", min_free_bytes=0)
        rows = load_dataset(tmp_path / "dataset")
        assert rows[0].fee is None and rows[1].fee["fee_rate"] == 0.02 and rows[-1].fee is None
        features, _ = causal_features(rows)
        scenarios, _ = execution_scenarios(rows, features)
        assert any(r["hypothetical_net_difference_after_fee_bound"] is not None for r in scenarios)
    finally:
        store.close()


def test_dataset_hash_and_source_hash_fail_closed(tmp_path):
    store = EventStore(tmp_path / "source.sqlite")
    store.append(quote())
    store.close()
    extract_dataset(tmp_path / "source.sqlite", tmp_path / "dataset", min_free_bytes=0)
    p = tmp_path / "dataset/observations.jsonl"
    p.write_text(p.read_text().replace("controlled-m", "tampered"))
    with pytest.raises(ValueError, match="identity mismatch"):
        load_dataset(tmp_path / "dataset")


def test_features_are_causal_and_reject_stale_or_out_of_order_quotes():
    rows = [observation(0), observation(10, bid=0.42, ask=0.43), observation(20, bid=0.9, ask=0.91)]
    before, _ = causal_features(rows[:2])
    after, _ = causal_features(rows)
    assert after[:2] == before
    assert before[1]["prior_observations"] == 1 and before[1]["history_available_through"] == NOW.isoformat()
    _, reasons = causal_features([rows[1], rows[0], observation(30, source_delay=16)])
    assert reasons["out_of_order_observation"] == 1 and reasons["stale_book"] == 1


def test_depth_participation_partial_capacity_and_price_bounds():
    levels = (PriceLevel(price=0.4, size=10), PriceLevel(price=0.42, size=100))
    result = depth_quote(levels, 5, limit=0.41)
    assert not result["complete"] and result["quantity_available"] == pytest.approx(1)
    assert depth_quote(levels, 5)["average_price"] == pytest.approx((1 * 0.4 + 4 * 0.42) / 5)
    with pytest.raises(ValueError):
        depth_quote(levels, 5, participation=2)


def test_cost_scenarios_require_post_latency_source_receipt_and_real_fees():
    data = [observation(0), observation(0.2), observation(60, bid=0.43, ask=0.44)]
    features, _ = causal_features(data)
    result, reasons = execution_scenarios(data, features)
    two = next(r for r in result if r["notional_target"] == 2)
    assert two["entry_book_id"] == data[1].book.id and two["exit_book_id"] == data[2].book.id
    expected = two["shares"] * (0.43 * 0.98 - 0.41 * 1.02)
    assert two["hypothetical_net_difference_after_fee_bound"] == pytest.approx(expected)
    assert two["additional_per_leg_slippage_sensitivity"]["0.01"] == pytest.approx(
        expected - two["shares"] * 0.02
    )
    nofee = [r.model_copy(update={"fee": None}) for r in data]
    result, _ = execution_scenarios(nofee, features)
    assert all(r["hypothetical_net_difference_after_fee_bound"] is None for r in result)
    delayed = [data[0], observation(0.2, source_delay=0.2), data[2]]
    result, reasons = execution_scenarios(delayed, features)
    assert not result and reasons["post_latency_entry_or_horizon_exit_missing"] > 0


def test_no_future_market_or_fee_accepted():
    with pytest.raises(ValueError, match="future metadata"):
        ResearchObservation(book=quote(), market=metadata(1))
    with pytest.raises(ValueError, match="future fee"):
        ResearchObservation(book=quote(), fee={"observed_at": (NOW + timedelta(seconds=1)).isoformat()})


def test_source_bindings_cannot_be_tampered_or_omitted(tmp_path):
    store = EventStore(tmp_path / "source.sqlite")
    store.append(quote())
    store.close()
    extract_dataset(tmp_path / "source.sqlite", tmp_path / "dataset", min_free_bytes=0)
    p = tmp_path / "dataset/source-records.jsonl"
    p.write_text(p.read_text().replace("OrderBookSnapshot", "MarketSnapshot"))
    with pytest.raises(ValueError, match="binding identity mismatch"):
        load_dataset(tmp_path / "dataset")


def test_long_gap_same_top_quote_resets_history_and_persistence():
    features, _ = causal_features([observation(0), observation(130)])
    assert features[1]["prior_observations"] == 0
    assert features[1]["quote_persistence_seconds"] == 0


def test_loader_rejects_duplicate_id_even_if_observation_hash_rebound(tmp_path):
    store = EventStore(tmp_path / "source.sqlite")
    store.append(quote())
    store.close()
    extract_dataset(tmp_path / "source.sqlite", tmp_path / "dataset", min_free_bytes=0)
    p = tmp_path / "dataset/observations.jsonl"
    payload = p.read_bytes() * 2
    p.write_bytes(payload)
    m = tmp_path / "dataset/manifest.json"
    manifest = json.loads(m.read_text())
    manifest.update(
        observations=2, observation_bytes=len(payload), dataset_sha256=hashlib.sha256(payload).hexdigest()
    )
    m.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="duplicate or unsupported"):
        load_dataset(tmp_path / "dataset")
