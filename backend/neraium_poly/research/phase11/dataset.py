"""Bounded read-only immutable extraction of authentic observations, never replay fills."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
from bisect import bisect_right
from collections import Counter
from pathlib import Path

from neraium_poly.contracts import MarketSnapshot, OrderBookSnapshot
from neraium_poly.experimental.fees import FeeObservation, PublicFeeResponse
from neraium_poly.research.archive import BookDelta, BookReceipt, apply_observation
from neraium_poly.research.phase11.contracts import ResearchObservation

OFFICIAL = {"https://clob.polymarket.com", "wss://ws-subscriptions-clob.polymarket.com/ws/market"}
MAX_BYTES = 512 * 1024 * 1024


def _verified(row):
    if hashlib.sha256(row["payload"].encode()).hexdigest() != row["digest"]:
        raise ValueError("corrupt immutable source record")
    return row


def extract_dataset(database, output, *, limit=30000, high_water=None, min_free_bytes=8 * 1024**3):
    """Take at most 30k most-recent quoted observations from one read snapshot.

    Metadata and fee availability are matched AS OF each quote. Missing context
    stays null. Existing artifacts are never overwritten. All source record
    hashes are bound in source-records.jsonl; no source database is opened writable.
    """
    if not 1 <= limit <= 30000 or min_free_bytes < 0:
        raise ValueError("bounded extraction settings required")
    output = Path(output)
    if output.exists():
        raise ValueError("new dataset directory required")
    output.parent.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(output.parent).free < min_free_bytes + MAX_BYTES:
        raise ValueError("research disk reserve unavailable")
    source = Path(database).resolve()
    conn = sqlite3.connect(source.as_uri() + "?mode=ro", uri=True, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("BEGIN")
    try:
        maximum = conn.execute("SELECT COALESCE(MAX(rowid),0) FROM events").fetchone()[0]
        high_water = maximum if high_water is None else high_water
        if not isinstance(high_water, int) or high_water < 1 or high_water > maximum:
            raise ValueError("valid fixed high-water required")
        raw = conn.execute(
            "SELECT rowid,* FROM events WHERE rowid<=? AND kind IN ('OrderBookSnapshot','BookDelta','BookReceipt') ORDER BY rowid DESC LIMIT ?",
            (high_water, limit),
        ).fetchall()
        if not raw:
            raise ValueError("no archived observations")
        # Context cardinality bound is explicit, independent from quote count.
        contexts = conn.execute(
            "SELECT rowid,* FROM events WHERE rowid<=? AND kind IN ('MarketSnapshot','FeeObservation') ORDER BY rowid LIMIT 100001",
            (high_water,),
        ).fetchall()
        if len(contexts) > 100000:
            raise ValueError("research context budget exceeded")
        bindings = {}

        def bind(row):
            _verified(row)
            bindings[row["id"]] = {
                "rowid": row["rowid"],
                "id": row["id"],
                "kind": row["kind"],
                "sha256": row["digest"],
            }
            return json.loads(row["payload"])

        metadata, fees, bases = {}, {}, {}
        for row in contexts:
            data = bind(row)
            if row["kind"] == "MarketSnapshot":
                record = MarketSnapshot.model_validate(data)
                metadata.setdefault(record.token_id, []).append(record)
            else:
                record = FeeObservation.model_validate(data)
                if record.source != "https://clob.polymarket.com" or len(record.raw_response_ids) < 2:
                    raise ValueError("unverified public fee provenance")
                for rid in record.raw_response_ids:
                    rr = conn.execute(
                        "SELECT rowid,* FROM events WHERE id=? AND rowid<=?", (rid, high_water)
                    ).fetchone()
                    if not rr or rr["kind"] != "PublicFeeResponse":
                        raise ValueError("missing fee raw response")
                    proof = PublicFeeResponse.model_validate(bind(rr))
                    canonical = json.dumps(
                        proof.payload, sort_keys=True, separators=(",", ":"), allow_nan=False
                    )
                    if (
                        hashlib.sha256(canonical.encode()).hexdigest() != proof.content_sha256
                        or proof.available_at > record.available_at
                    ):
                        raise ValueError("invalid fee response digest or availability")
                fees.setdefault(record.token_id, []).append(record)
        for values in (*metadata.values(), *fees.values()):
            values.sort(key=lambda r: (r.available_at, r.id))
        times = {k: [r.available_at for r in rows] for k, rows in metadata.items()}
        fee_times = {k: [r.available_at for r in rows] for k, rows in fees.items()}
        rows, missing = [], Counter()
        for source_row in raw:
            data = bind(source_row)
            if source_row["kind"] == "OrderBookSnapshot":
                book = OrderBookSnapshot.model_validate(data)
            else:
                receipt = (BookDelta if source_row["kind"] == "BookDelta" else BookReceipt).model_validate(
                    data
                )
                if receipt.full_book_id not in bases:
                    rr = conn.execute(
                        "SELECT rowid,* FROM events WHERE id=? AND rowid<=?",
                        (receipt.full_book_id, high_water),
                    ).fetchone()
                    if not rr or rr["kind"] != "OrderBookSnapshot":
                        raise ValueError("missing original complete book")
                    bases[receipt.full_book_id] = OrderBookSnapshot.model_validate(bind(rr))
                original = bases[receipt.full_book_id]
                if original.available_at > receipt.available_at:
                    raise ValueError("future quote baseline")
                book = apply_observation(original, receipt)
            if book.source not in OFFICIAL or book.exchange != "polymarket":
                missing["unsupported_quote_source"] += 1
                continue
            market = fee = None
            idx = bisect_right(times.get(book.token_id, []), book.available_at) - 1
            if idx >= 0:
                candidate = metadata[book.token_id][idx]
                if candidate.market_id == book.market_id:
                    market = candidate
            if market is None:
                missing["point_in_time_market_metadata_unavailable"] += 1
            idx = bisect_right(fee_times.get(book.token_id, []), book.available_at) - 1
            if idx >= 0:
                candidate = fees[book.token_id][idx]
                if 0 <= (book.available_at - candidate.available_at).total_seconds() <= 300:
                    fee = {
                        "fee_rate": candidate.fee_rate,
                        "observed_at": candidate.available_at.isoformat(),
                        "source": candidate.source,
                        "evidence_id": candidate.id,
                        "raw_response_ids": list(candidate.raw_response_ids),
                        "assumption": candidate.assumption,
                    }
            if fee is None:
                missing["point_in_time_fresh_fee_unavailable"] += 1
            rows.append(ResearchObservation(book=book, market=market, fee=fee))
        rows.sort(key=lambda r: (r.book.available_at, r.book.timestamp, r.book.id))
        if len({r.book.id for r in rows}) != len(rows):
            raise ValueError("duplicate observed book identity")
        output.mkdir()
        h, size = hashlib.sha256(), 0
        with (output / "observations.jsonl").open("xb") as handle:
            for row in rows:
                encoded = (row.model_dump_json() + "\n").encode()
                size += len(encoded)
                if size > MAX_BYTES:
                    raise ValueError("dataset byte budget exceeded; partial artifact retained")
                h.update(encoded)
                handle.write(encoded)
        source_text = "".join(
            json.dumps(r, sort_keys=True) + "\n" for r in sorted(bindings.values(), key=lambda r: r["rowid"])
        )
        (output / "source-records.jsonl").write_text(source_text)
        manifest = {
            "schema_version": "1.0",
            "dataset_sha256": h.hexdigest(),
            "observations": len(rows),
            "observation_bytes": size,
            "source_database": str(source),
            "source_high_water": high_water,
            "source_quote_rowid_min": min(r["rowid"] for r in raw),
            "source_quote_rowid_max": max(r["rowid"] for r in raw),
            "source_record_bindings_sha256": hashlib.sha256(source_text.encode()).hexdigest(),
            "source_records": len(bindings),
            "source_interval": [
                min(r.book.timestamp for r in rows).isoformat(),
                max(r.book.timestamp for r in rows).isoformat(),
            ],
            "availability_interval": [
                rows[0].book.available_at.isoformat(),
                rows[-1].book.available_at.isoformat(),
            ],
            "markets": len({r.book.market_id for r in rows}),
            "tokens": len({r.book.token_id for r in rows}),
            "event_groups": len({r.market.event_id for r in rows if r.market}),
            "independently_reviewed_events": 0,
            "completeness": dict(missing),
            "selection": "Latest bounded quote observations by insertion high-water, then sorted by actual availability; no outcome selection",
            "certification_authority": False,
            "automatic_promotion": False,
            "limitations": [
                "Sampling is bounded, not complete tick history",
                "Observed depth is not guaranteed future executable liquidity",
                "Metadata and fee context missing at decision time remains null",
                "Event IDs are not proof of event independence",
            ],
        }
        (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        return manifest
    finally:
        conn.close()


def load_dataset(directory):
    path = Path(directory)
    manifest = json.loads((path / "manifest.json").read_text())
    file = path / "observations.jsonl"
    if file.stat().st_size > MAX_BYTES:
        raise ValueError("dataset byte budget exceeded")
    digest = hashlib.sha256()
    rows = []
    with file.open("rb") as handle:
        for line in handle:
            digest.update(line)
            rows.append(ResearchObservation.model_validate_json(line))
            if len(rows) > 30000:
                raise ValueError("dataset observation budget exceeded")
    if digest.hexdigest() != manifest["dataset_sha256"] or len(rows) != manifest["observations"]:
        raise ValueError("dataset identity mismatch")
    if rows != sorted(rows, key=lambda r: (r.book.available_at, r.book.timestamp, r.book.id)):
        raise ValueError("dataset availability ordering violated")
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=30000)
    parser.add_argument("--high-water", type=int)
    args = parser.parse_args()
    print(
        json.dumps(
            extract_dataset(args.database, args.output, limit=args.limit, high_water=args.high_water),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
