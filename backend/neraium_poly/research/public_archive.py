"""Bounded publisher-attributed L2 inspection, never certified exchange books."""
from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True)
class PublisherSnapshot:
    market_slug: str
    token_id: str
    outcome: str
    captured_at: datetime
    market_end_at: datetime
    bids: tuple[tuple[float, float], ...]
    asks: tuple[tuple[float, float], ...]
    publisher_url: str
    raw_sha256: str
    retrieved_at: datetime
    # No exchange event time, historical receipt time or verified winner exists here.


def _time(value: object) -> datetime:
    result = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("Publisher timestamp lacks timezone")
    return result


def _files(directory: Path) -> list[dict]:
    manifest_path = directory / "manifest.json"
    if manifest_path.stat().st_size > 1024 * 1024:
        raise ValueError("Archive manifest exceeds bounded size")
    manifest = json.loads(manifest_path.read_text())
    if len(manifest["files"]) > 16:
        raise ValueError("Archive file count exceeds bounded size")
    result = []
    total_bytes = 0
    for entry in manifest["files"]:
        path = (directory / entry["file"]).resolve()
        if not path.is_relative_to(directory.resolve()) or not path.is_file():
            raise ValueError("Unsafe or missing archive file")
        size = path.stat().st_size
        total_bytes += size
        if size > 20 * 1024 * 1024 or total_bytes > 100 * 1024 * 1024:
            raise ValueError("Archive bytes exceed bounded size")
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(65536), b""):
                digest.update(chunk)
        if digest.hexdigest() != entry["sha256"] or path.stat().st_size != entry["bytes"]:
            raise ValueError("Archive checksum or length mismatch")
        if path.suffix == ".parquet":
            result.append({**entry, "path": path})
    return result


def _reader(path: Path):
    try:
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise RuntimeError("Public archive inspection requires optional research PyArrow") from exc
    return pq.ParquetFile(path)


def _limits(max_rows: int, batch_size: int) -> None:
    if not 1 <= max_rows <= 5000 or not 1 <= batch_size <= 512:
        raise ValueError("Audit limits require 1..5000 rows and 1..512 rows per batch")


def iter_public_snapshots(
    directory: str | Path, *, max_rows: int = 5000, batch_size: int = 512
) -> Iterator[PublisherSnapshot]:
    """Yield finite research rows; preserve capture meaning and exclude winner columns."""
    _limits(max_rows, batch_size)
    count = 0
    for entry in _files(Path(directory)):
        columns = ["market_slug", "token_id", "outcome", "captured_at", "market_end_at",
                   "bid_prices", "bid_sizes", "ask_prices", "ask_sizes"]
        for batch in _reader(entry["path"]).iter_batches(batch_size=batch_size, columns=columns):
            for row in batch.to_pylist():
                if count >= max_rows:
                    return
                count += 1
                if len(row["bid_prices"]) != len(row["bid_sizes"]) or len(
                    row["ask_prices"]
                ) != len(row["ask_sizes"]):
                    raise ValueError("Publisher ladder lengths disagree")
                yield PublisherSnapshot(
                    market_slug=str(row["market_slug"]), token_id=str(row["token_id"]),
                    outcome=str(row["outcome"]), captured_at=_time(row["captured_at"]),
                    market_end_at=_time(row["market_end_at"]),
                    bids=tuple(zip(row["bid_prices"], row["bid_sizes"], strict=True)),
                    asks=tuple(zip(row["ask_prices"], row["ask_sizes"], strict=True)),
                    publisher_url=entry["final_url"], raw_sha256=entry["sha256"],
                    retrieved_at=_time(entry["retrieved_at"]),
                )


def audit_public_archive(
    directory: str | Path, *, max_rows: int = 5000, batch_size: int = 512
) -> dict:
    """Deterministic bounded quality sample, not a representative performance estimate."""
    _limits(max_rows, batch_size)
    entries = _files(Path(directory))
    totals = {e["file"]: _reader(e["path"]).metadata.num_rows for e in entries}
    counts: Counter = Counter()
    slugs, tokens, times = set(), set(), []
    for row in iter_public_snapshots(directory, max_rows=max_rows, batch_size=batch_size):
        counts["sampled_rows"] += 1
        slugs.add(row.market_slug)
        tokens.add(row.token_id)
        times.append(row.captured_at)
        bids, asks = row.bids, row.asks
        counts["one_sided"] += not bids or not asks
        counts["invalid_or_zero_levels"] += any(
            not math.isfinite(price) or not 0 < price < 1
            or not math.isfinite(size) or size <= 0 for price, size in bids + asks
        )
        counts["crossed_or_locked"] += bool(bids and asks and max(p for p, _ in bids)
                                                    >= min(p for p, _ in asks))
        counts["unsorted_ladders"] += any(bids[i][0] < bids[i+1][0]
                                               for i in range(len(bids)-1)) or any(
            asks[i][0] > asks[i+1][0] for i in range(len(asks)-1)
        )
        counts["capture_at_or_after_end"] += row.captured_at >= row.market_end_at
    return {
        "kind": "publisher_archive_quality_sample", "source_file_rows": totals,
        "source_total_rows": sum(totals.values()), "sample_is_representative": False,
        "sample_max_rows": max_rows, "batch_size": batch_size, **counts,
        "sample_distinct_market_slugs": len(slugs), "sample_distinct_tokens": len(tokens),
        "official_event_mapping_count": 0, "verified_outcome_count": 0,
        "certification_eligible_events": 0,
        "first_sample_capture": min(times).isoformat() if times else None,
        "last_sample_capture": max(times).isoformat() if times else None,
        "timestamp_meaning": "Publisher captured_at; no original exchange or receipt timestamp",
        "deficiencies": [
            "Publisher outcome columns are withheld, not official verified settlement labels",
            "No linked original exchange timestamps or historical receipt proof",
            "No official parent event mapping, independent context or dependency review",
            "Adjacent and overlapping same-asset windows do not prove independent events",
            "Quality sample cannot establish full capture completeness or fill availability",
        ],
    }
