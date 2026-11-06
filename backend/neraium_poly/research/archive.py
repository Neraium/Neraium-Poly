"""Lossless quote-level deduplication with explicit observed-time receipts.

Only identical levels share storage. Every new observed source/receipt time is
retained; a receipt never creates an unobserved historical state.
"""

import json
from hashlib import sha256

from neraium_poly.contracts import OrderBookSnapshot, PriceLevel, Record


def content_hash(book: OrderBookSnapshot) -> str:
    value = [
        book.exchange,
        book.market_id,
        book.token_id,
        book.source,
        book.complete,
        [(p.price, p.size) for p in book.bids],
        [(p.price, p.size) for p in book.asks],
    ]
    return sha256(json.dumps(value, separators=(",", ":")).encode()).hexdigest()


class BookReceipt(Record):
    market_id: str
    token_id: str
    exchange: str
    observed_book_id: str
    full_book_id: str
    content_sha256: str
    sequence: int
    complete: bool


class BookDelta(BookReceipt):
    """Differences between two actually observed complete level arrays."""

    bids_changed: tuple[tuple[float, float], ...] = ()
    asks_changed: tuple[tuple[float, float], ...] = ()


def apply_observation(base, record):
    values = base.model_dump()
    if isinstance(record, BookDelta):
        for side, reverse in (("bids", True), ("asks", False)):
            levels = {p.price: p.size for p in getattr(base, side)}
            for price, size in getattr(record, side + "_changed"):
                if not 0 < price < 1 or size < 0:
                    raise ValueError("Invalid archived observed level")
                if size == 0:
                    levels.pop(price, None)
                else:
                    levels[price] = size
            values[side] = tuple(
                PriceLevel(price=p, size=size) for p, size in sorted(levels.items(), reverse=reverse)
            )
    values.update(
        id=record.observed_book_id,
        timestamp=record.timestamp,
        available_at=record.available_at,
        source=record.source,
        sequence=record.sequence,
        complete=record.complete,
    )
    book = OrderBookSnapshot.model_validate(values)
    if content_hash(book) != record.content_sha256 or (book.token_id, book.market_id, book.exchange) != (
        record.token_id,
        record.market_id,
        record.exchange,
    ):
        raise ValueError("Observed quote reconstruction failed integrity")
    return book


class QuoteArchive:
    def __init__(self, store, state=None):
        self.store = store
        self.state = dict(state or {})
        self.bases = {}
        for token, row in self.state.items():
            saved = self.store.get(row["full_book_id"])
            if not saved or saved[0] != "OrderBookSnapshot":
                raise ValueError("Missing canonical quote in recovered archive")
            if sha256(saved[1].encode()).hexdigest() != saved[2]:
                raise ValueError("Corrupt canonical quote in recovered archive")
            book = OrderBookSnapshot.model_validate_json(saved[1])
            if book.token_id != token or content_hash(book) != row.get(
                "base_content_sha256", row["content_sha256"]
            ):
                raise ValueError("Recovered quote content mismatch")
            self.bases[token] = book

    def record(self, book: OrderBookSnapshot) -> bool:
        old = self.state.get(book.token_id)
        if old and old["observed_book_id"] == book.id:
            return False
        digest = content_hash(book)
        base = self.bases.get(book.token_id)
        fields = {
            "id": sha256(("book-observation:" + book.id).encode()).hexdigest(),
            "timestamp": book.timestamp,
            "available_at": book.available_at,
            "source": book.source,
            "market_id": book.market_id,
            "token_id": book.token_id,
            "exchange": book.exchange,
            "observed_book_id": book.id,
            "full_book_id": base.id if base else book.id,
            "content_sha256": digest,
            "sequence": book.sequence,
            "complete": book.complete,
        }
        record = None
        if base is not None and (base.exchange, base.market_id) == (book.exchange, book.market_id):
            changed = {}
            for side in ("bids", "asks"):
                left = {p.price: p.size for p in getattr(base, side)}
                right = {p.price: p.size for p in getattr(book, side)}
                changed[side + "_changed"] = tuple(
                    (price, right.get(price, 0))
                    for price in sorted(left.keys() | right.keys())
                    if left.get(price, 0) != right.get(price, 0)
                )
            if digest == content_hash(base):
                record = BookReceipt(**fields)
            else:
                record = BookDelta(**fields, **changed)
        if record is not None and (
            type(record) is BookReceipt or len(record.model_dump_json()) < len(book.model_dump_json()) * 0.8
        ):
            self.store.append(record)
            full_id = base.id
            base_hash = content_hash(base)
        else:
            self.store.append(book)
            self.bases[book.token_id] = book
            full_id = book.id
            base_hash = digest
        self.state[book.token_id] = {
            "observed_book_id": book.id,
            "full_book_id": full_id,
            "base_content_sha256": base_hash,
            "content_sha256": digest,
        }
        return True

    def retain(self, tokens: set[str]):
        self.state = {key: row for key, row in self.state.items() if key in tokens}
        self.bases = {key: row for key, row in self.bases.items() if key in tokens}


def replay_sampled_books(store, *, until=None) -> tuple[OrderBookSnapshot, ...]:
    originals = {}
    result = []
    for event in store.replay(until=until):
        if event["kind"] == "OrderBookSnapshot":
            book = OrderBookSnapshot.model_validate(event["record"])
            originals[book.id] = book
            result.append(book)
        elif event["kind"] in {"BookReceipt", "BookDelta"}:
            receipt = (BookDelta if event["kind"] == "BookDelta" else BookReceipt).model_validate(
                event["record"]
            )
            # Availability ordering may put a reference before its original only
            # if malformed input tried to backdate a receipt; reject rather than guess.
            original = originals.get(receipt.full_book_id)
            if original is None:
                row = store.get(receipt.full_book_id)
                if row and row[0] == "OrderBookSnapshot" and sha256(row[1].encode()).hexdigest() == row[2]:
                    original = OrderBookSnapshot.model_validate_json(row[1])
            if original is None or original.available_at > receipt.available_at:
                raise ValueError("Missing or inconsistent quote reference during replay")
            result.append(apply_observation(original, receipt))
    unique = {}
    for book in result:
        if book.id in unique and unique[book.id] != book:
            raise ValueError("Conflicting observed book identity")
        unique.setdefault(book.id, book)
    return tuple(unique.values())
