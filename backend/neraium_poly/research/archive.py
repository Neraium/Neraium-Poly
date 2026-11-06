"""Lossless quote-level deduplication with explicit observed-time receipts.

Only identical levels share storage. Every new observed source/receipt time is
retained; a receipt never creates an unobserved historical state.
"""

import json
from hashlib import sha256

from neraium_poly.contracts import OrderBookSnapshot, Record


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


class QuoteArchive:
    def __init__(self, store, state=None):
        self.store = store
        self.state = dict(state or {})
        for token, row in self.state.items():
            saved = self.store.connection.execute(
                "SELECT payload,digest FROM events WHERE id=? AND kind='OrderBookSnapshot'",
                (row["full_book_id"],),
            ).fetchone()
            if not saved:
                raise ValueError("Missing canonical quote in recovered archive")
            if sha256(saved[0].encode()).hexdigest() != saved[1]:
                raise ValueError("Corrupt canonical quote in recovered archive")
            book = OrderBookSnapshot.model_validate_json(saved[0])
            if book.token_id != token or content_hash(book) != row["content_sha256"]:
                raise ValueError("Recovered quote content mismatch")

    def record(self, book: OrderBookSnapshot) -> bool:
        old = self.state.get(book.token_id)
        if old and old["observed_book_id"] == book.id:
            return False
        digest = content_hash(book)
        if old and old["content_sha256"] == digest:
            receipt = BookReceipt(
                id=sha256(("book-receipt:" + book.id).encode()).hexdigest(),
                timestamp=book.timestamp,
                available_at=book.available_at,
                source=book.source,
                market_id=book.market_id,
                token_id=book.token_id,
                exchange=book.exchange,
                observed_book_id=book.id,
                full_book_id=old["full_book_id"],
                content_sha256=digest,
                sequence=book.sequence,
                complete=book.complete,
            )
            self.store.append(receipt)
            full_id = old["full_book_id"]
        else:
            self.store.append(book)
            full_id = book.id
        self.state[book.token_id] = {
            "observed_book_id": book.id,
            "full_book_id": full_id,
            "content_sha256": digest,
        }
        return True

    def retain(self, tokens: set[str]):
        self.state = {key: row for key, row in self.state.items() if key in tokens}


def replay_sampled_books(store, *, until=None) -> tuple[OrderBookSnapshot, ...]:
    originals = {}
    result = []
    for event in store.replay(until=until):
        if event["kind"] == "OrderBookSnapshot":
            book = OrderBookSnapshot.model_validate(event["record"])
            originals[book.id] = book
            result.append(book)
        elif event["kind"] == "BookReceipt":
            receipt = BookReceipt.model_validate(event["record"])
            # Availability ordering may put a reference before its original only
            # if malformed input tried to backdate a receipt; reject rather than guess.
            original = originals.get(receipt.full_book_id)
            if original is None:
                row = store.connection.execute(
                    "SELECT payload,digest FROM events WHERE id=? AND kind='OrderBookSnapshot'",
                    (receipt.full_book_id,),
                ).fetchone()
                if row and sha256(row[0].encode()).hexdigest() == row[1]:
                    original = OrderBookSnapshot.model_validate_json(row[0])
            if (
                original is None
                or original.available_at > receipt.available_at
                or content_hash(original) != receipt.content_sha256
            ):
                raise ValueError("Missing or inconsistent quote reference during replay")
            values = original.model_dump()
            values.update(
                id=receipt.observed_book_id,
                timestamp=receipt.timestamp,
                available_at=receipt.available_at,
                source=receipt.source,
                sequence=receipt.sequence,
                complete=receipt.complete,
            )
            book = OrderBookSnapshot.model_validate(values)
            if (book.token_id, book.market_id, book.exchange) != (
                receipt.token_id,
                receipt.market_id,
                receipt.exchange,
            ):
                raise ValueError("Quote receipt instrument mismatch")
            result.append(book)
    return tuple(result)
