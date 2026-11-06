from datetime import timedelta

import pytest
from neraium_poly.contracts import PriceLevel
from neraium_poly.data import EventStore
from neraium_poly.research.archive import QuoteArchive, replay_sampled_books


def test_identical_levels_preserve_actual_source_and_availability(book, now):
    store = EventStore()
    archive = QuoteArchive(store)
    assert archive.record(book)
    later = book.model_copy(
        update={
            "id": "second",
            "timestamp": now + timedelta(seconds=1),
            "available_at": now + timedelta(seconds=2),
        }
    )
    assert archive.record(later)
    assert not archive.record(later)
    assert [e["kind"] for e in store.replay()] == ["OrderBookSnapshot", "BookReceipt"]
    recovered = replay_sampled_books(store)
    assert recovered == (book, later)
    assert replay_sampled_books(store, until=now) == (book,)
    restarted = QuoteArchive(store, archive.state)
    assert not restarted.record(later)


def test_changed_depth_requires_new_actual_full_book(book, now):
    store = EventStore()
    archive = QuoteArchive(store)
    archive.record(book)
    newer = book.model_copy(
        update={
            "id": "changed",
            "timestamp": now + timedelta(seconds=1),
            "available_at": now + timedelta(seconds=1),
            "asks": (PriceLevel(price=0.41, size=2),),
        }
    )
    archive.record(newer)
    assert all(e["kind"] == "OrderBookSnapshot" for e in store.replay())
    assert replay_sampled_books(store) == (book, newer)


def test_corrupt_recovery_refuses_manufacturing_quotes(book):
    store = EventStore()
    archive = QuoteArchive(store)
    archive.record(book)
    state = {book.token_id: {**archive.state[book.token_id], "full_book_id": "missing"}}
    with pytest.raises(ValueError, match="Missing canonical"):
        QuoteArchive(store, state)


def test_observed_level_delta_replays_exact_actual_depth_and_transport(book, now):
    from neraium_poly.contracts import OrderBookSnapshot

    base = book.model_copy(
        update={
            "id": "deep",
            "bids": tuple(PriceLevel(price=0.39 - i * 0.005, size=100) for i in range(50)),
            "asks": tuple(PriceLevel(price=0.4 + i * 0.005, size=100) for i in range(50)),
        }
    )
    store = EventStore()
    archive = QuoteArchive(store)
    archive.record(base)
    values = base.model_dump()
    values.update(
        id="ws-delta-observation",
        timestamp=now + timedelta(seconds=1),
        available_at=now + timedelta(seconds=2),
        source="wss://ws-subscriptions-clob.polymarket.com/ws/market",
        asks=(PriceLevel(price=0.4, size=3),) + base.asks[1:],
    )
    observed = OrderBookSnapshot.model_validate(values)
    archive.record(observed)
    assert store.replay()[-1]["kind"] == "BookDelta"
    assert replay_sampled_books(store) == (base, observed)
    restored = QuoteArchive(store, archive.state)
    next_observed = observed.model_copy(
        update={
            "id": "ws-next",
            "timestamp": now + timedelta(seconds=3),
            "available_at": now + timedelta(seconds=4),
        }
    )
    restored.record(next_observed)
    assert replay_sampled_books(store)[-1] == next_observed
