"""Freeze public, point-in-time replay inputs with original archive identities."""

import gzip
import hashlib
import json
import sqlite3
import sys
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

from neraium_poly.contracts import OrderBookSnapshot
from neraium_poly.research.archive import BookDelta, BookReceipt, apply_observation
from neraium_poly.research.phase17.provenance import ReadonlyArchive

HERE = Path(__file__).resolve().parent
ROOT = Path("/home/ubuntu/Neraium-Poly/data")
with gzip.open(HERE.parent / "phase52/freshness-polls.jsonl.gz", "rt") as stream:
    picked = next(row for line in stream if (row := json.loads(line))["window"] == 1)
start = datetime.fromisoformat(picked["at"])
end = start + timedelta(seconds=300)
lower = start - timedelta(minutes=30)
reference = ReadonlyArchive(ROOT / "paper-live")
rows = []


def add(origin, kind, payload, digest, book=None):
    assert hashlib.sha256(payload.encode()).hexdigest() == digest
    raw = json.loads(payload)
    t = datetime.fromisoformat(raw["available_at"])
    if lower <= t <= end:
        rows.append([origin, kind, raw["id"], digest, (book.model_dump(mode="json") if book else raw)])


bases = {}
for kind in ("MarketSnapshot", "OrderBookSnapshot", "BookDelta", "BookReceipt", "LiveCycle"):
    records = reference._catalog_rows(
        "SELECT * FROM records WHERE kind=? AND available_at>=? AND available_at<=? "
        "ORDER BY available_at,id LIMIT 20001",
        (kind, lower.isoformat(), end.isoformat()),
    )
    assert len(records) < 20001
    for entry in records:
        _, payload, digest = reference._fetch(entry)
        if kind in ("BookDelta", "BookReceipt"):
            record = (BookDelta if kind == "BookDelta" else BookReceipt).model_validate_json(payload)
            book = bases.get(record.full_book_id)
            if book is None:
                original = reference.get(record.full_book_id)
                assert original and original[0] == "OrderBookSnapshot"
                book = bases[record.full_book_id] = OrderBookSnapshot.model_validate_json(original[1])
            assert book.available_at <= record.available_at
            add("reference", kind, payload, digest, apply_observation(book, record))
        else:
            add("reference", kind, payload, digest)

# A bounded row-ID slab supplies actually retained REST quotes between sparse reference archive samples.
# It covers the selected interval and its immediate lead-in, not the reference WS history.
with sqlite3.connect((ROOT / "live-20261106/public.sqlite").as_uri() + "?mode=ro", uri=True) as source:
    source.execute("PRAGMA query_only=ON")
    for kind, payload, digest in source.execute(
        "SELECT kind,payload,digest FROM events WHERE rowid BETWEEN ? AND ? AND kind IN "
        "('OrderBookSnapshot','MarketSnapshot') ORDER BY rowid",
        (4531721, 4536641),
    ):
        add("collector", kind, payload, digest)

rows.sort(key=lambda row: (datetime.fromisoformat(row[4]["available_at"]), row[2]))
data = {"start": start.isoformat(), "end": end.isoformat(), "warmup_lower": lower.isoformat(), "rows": rows}
body = gzip.compress(json.dumps(data, separators=(",", ":")).encode(), mtime=0)
assert len(body) < 12 * 1024**2
Path(sys.argv[1]).write_bytes(body)
summary = {
    "start": data["start"],
    "end": data["end"],
    "rows": dict(Counter(f"{r[0]}:{r[1]}" for r in rows)),
    "fixture_sha256": hashlib.sha256(body).hexdigest(),
    "compressed_bytes": len(body),
}
(HERE / "fixture-manifest.json").write_text(json.dumps(summary, indent=2) + "\n")
print(json.dumps(summary))
