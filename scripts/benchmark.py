"""Bounded reproducible persistence benchmark, not trading throughput certification."""

import json
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from time import perf_counter

from neraium_poly.contracts import MarketSnapshot
from neraium_poly.data import EventStore


def main():
    count = 2000
    base = datetime(2026, 11, 5, tzinfo=UTC)
    with tempfile.TemporaryDirectory(prefix="poly-benchmark-") as directory:
        store = EventStore(Path(directory) / "events.sqlite")
        started = perf_counter()
        for i in range(count):
            at = base + timedelta(milliseconds=i)
            store.append(
                MarketSnapshot(
                    id=f"bench-{i}",
                    timestamp=at,
                    available_at=at,
                    source="synthetic-benchmark",
                    market_id="m",
                    event_id="e",
                    token_id="t",
                    question="Persistence benchmark",
                    probability=0.5,
                )
            )
        appended = perf_counter() - started
        started = perf_counter()
        replay = store.replay()
        replay_seconds = perf_counter() - started
        assert len(replay) == count
        store.close()
    print(
        json.dumps(
            {
                "records": count,
                "append_seconds": appended,
                "replay_seconds": replay_seconds,
                "append_records_per_second": count / appended,
                "scope": "single-process SQLite FULL synchronous local temporary file; not full trading throughput",
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
