"""Run the actual loopback routes and sampler against frozen public inputs."""

import argparse
import asyncio
import gzip
import json
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import RLock
from time import monotonic_ns
from types import SimpleNamespace

import httpx
import uvicorn
from neraium_poly.contracts import MarketSnapshot, OrderBookSnapshot
from neraium_poly.data import assess_book
from neraium_poly.data.segmented import ManagedEventStore
from neraium_poly.ops.api import create_app
from neraium_poly.ops.live import LivePaperRuntime
from neraium_poly.research.archive import QuoteArchive
from neraium_poly.research.phase44.reference import ReferenceSampler

PRODUCER_PORT = 18554
REPORT_PORT = 18555
DURATION = 300
MIB = 1024**2
GIB = 1024**3


def append(path, row):
    with path.open("a") as stream:
        stream.write(json.dumps(row, separators=(",", ":")) + "\n")


def private_cgroup(role):
    assert Path("/sys/class/net").is_dir()
    assert sorted(x.name for x in Path("/sys/class/net").iterdir()) == ["lo"], "private loopback only"
    protected = Path("/home/ubuntu/Neraium-Poly/data/paper-live/risk.sqlite")
    try:
        visible = protected.exists()
    except PermissionError:
        visible = False
    assert not visible, "live archive and accounts must be outside the replay"
    group = Path("/sys/fs/cgroup") / Path("/proc/self/cgroup").read_text().strip().split(":", 2)[2].lstrip(
        "/"
    )
    wanted = (
        "100000 100000",
        str((1 if role == "reference" else 2) * GIB),
        "64" if role == "reference" else "32",
    )
    obtained = tuple((group / key).read_text().strip() for key in ("cpu.max", "memory.max", "pids.max"))
    assert obtained == wanted, obtained
    return group


class Timeline:
    def __init__(self, options):
        with gzip.open(options.fixture, "rt") as stream:
            fixture = json.load(stream)
        self.origin = datetime.fromisoformat(fixture["start"])
        self.anchor = options.anchor_ns
        self.rows = fixture["rows"] if options.role == "reference" else []
        self.out = options.out

    def elapsed(self):
        return (monotonic_ns() - self.anchor) / 1e9

    def now(self):
        return self.origin + timedelta(seconds=self.elapsed())

    async def wait(self, elapsed):
        await asyncio.sleep(max(0, elapsed - self.elapsed()))


def app_server(runtime, port):
    return uvicorn.Server(
        uvicorn.Config(
            create_app(runtime=runtime, local_port=port),
            host="127.0.0.1",
            port=port,
            lifespan="off",
            access_log=False,
            log_config=None,
        )
    )


async def reference(clock):
    store = ManagedEventStore(
        clock.out / "archive/events.sqlite",
        segment_bytes=16 * MIB,
        budget_bytes=150 * GIB,
        min_free_bytes=100 * GIB,
        compress=True,
        clock=clock.now,
    )
    runtime = SimpleNamespace(
        clock=clock.now,
        _lock=RLock(),
        markets={},
        books={},
        prices={},
        fees={},
        relationships={},
        coverage=None,
        last_success=None,
        last_error=None,
        events=store,
    )
    runtime._current_books = lambda: LivePaperRuntime._current_books(runtime)
    runtime.market_frame = lambda: LivePaperRuntime.market_frame(runtime)
    quotes = QuoteArchive(store)
    records = []
    for origin, kind, record_id, _digest, payload in clock.rows:
        available = datetime.fromisoformat(payload["available_at"])
        if kind == "LiveCycle":
            continue
        if kind == "MarketSnapshot":
            entry = MarketSnapshot.model_validate(payload)
        else:
            entry = OrderBookSnapshot.model_validate(payload)
        records.append((available, origin, entry))

    def apply(origin, entry, *, archive):
        if isinstance(entry, MarketSnapshot):
            runtime.markets[entry.token_id] = entry
            return False
        prior = runtime.books.get(entry.token_id)
        # A faster arrival cannot roll the replayed native book backward.
        if prior and (entry.timestamp, entry.available_at) < (prior.timestamp, prior.available_at):
            return False
        with runtime._lock:
            runtime.books[entry.token_id] = entry
            if assess_book(entry, entry.available_at).healthy:
                runtime.last_success = entry.available_at
            market = runtime.markets.get(entry.token_id)
            if archive and origin == "reference" and market and market.market_id == entry.market_id:
                quotes.record(entry)
                LivePaperRuntime._book_market(runtime, entry)
                return True
        return False

    backlog = iter(records)
    record = next(backlog, None)
    while record is not None and record[0] < clock.origin:
        apply(record[1], record[2], archive=False)
        record = next(backlog, None)
    assert len(runtime.markets) <= 1000
    append(
        clock.out / "workload.jsonl", {"warm_markets": len(runtime.markets), "warm_books": len(runtime.books)}
    )
    server = app_server(runtime, PRODUCER_PORT)
    serving = asyncio.create_task(server.serve())
    applied = 0
    writes = 0
    last_stat = -1
    try:
        await clock.wait(0)
        while clock.elapsed() < DURATION + 5:
            now = clock.now()
            while record is not None and record[0] <= now:
                writes += apply(record[1], record[2], archive=True)
                applied += 1
                record = next(backlog, None)
            second = int(clock.elapsed())
            if second // 10 != last_stat:
                last_stat = second // 10
                await asyncio.to_thread(store.maintain)
                append(
                    clock.out / "workload.jsonl",
                    {
                        "elapsed": clock.elapsed(),
                        "applied": applied,
                        "quote_writes": writes,
                        "markets": len(runtime.markets),
                        "books": len(runtime.books),
                    },
                )
            await asyncio.sleep(0.1)
    finally:
        server.should_exit = True
        await serving
        store.close()


async def experimental(clock):
    runtime = SimpleNamespace()
    loop = asyncio.get_running_loop()

    def publish(frame, receipt):
        now = clock.now()
        runtime.shadow_research_snapshot = {
            "as_of": now.isoformat(),
            "input_frame_available_at": frame.available_at.isoformat(),
            "freshness_trace": {"published_at": now.isoformat(), "decision_reads": [receipt]},
        }

    class RecordingSampler(ReferenceSampler):
        def observe(self):
            before = monotonic_ns()
            started_at = datetime.now(UTC).isoformat()
            super().observe()
            ended_at = datetime.now(UTC).isoformat()
            current = self.status()
            receipt = current["recent_reads"][-1]
            append(
                clock.out / "requests.jsonl",
                {
                    "ordinal": current["attempts"],
                    "elapsed": clock.elapsed(),
                    "wall_started_at": started_at,
                    "wall_finished_at": ended_at,
                    "duration_seconds": (monotonic_ns() - before) / 1e9,
                    **receipt,
                },
            )
            if receipt["status"] == "accepted":
                frame, original = self.latest_with_receipt()
                loop.call_soon_threadsafe(publish, frame, original)

    sampler = RecordingSampler(f"http://127.0.0.1:{PRODUCER_PORT}/api/market-frame", clock=clock.now)
    runtime.research_reference = sampler
    # Use the real report route/verdict on the historical clock; no model or broker is loaded.
    from neraium_poly.ops import api

    api.datetime = SimpleNamespace(now=lambda _: clock.now())
    server = app_server(runtime, REPORT_PORT)
    serving = asyncio.create_task(server.serve())
    try:
        await clock.wait(0)
        sampling = asyncio.create_task(sampler.run(lambda: clock.elapsed() >= DURATION))
        async with httpx.AsyncClient(timeout=3, trust_env=False) as client:
            while clock.elapsed() < DURATION:
                row = {"elapsed": clock.elapsed()}
                try:
                    result = await client.get(f"http://127.0.0.1:{REPORT_PORT}/api/shadow-research")
                    result.raise_for_status()
                    report = result.json()
                    row.update(
                        status=report["status"],
                        report_as_of=report.get("as_of"),
                        age_seconds=report.get("age_seconds"),
                        runtime_error=report.get("runtime_error"),
                    )
                except httpx.HTTPError as error:
                    row["http_error"] = type(error).__name__
                append(clock.out / "polls.jsonl", row)
                await clock.wait(min(DURATION, clock.elapsed() + 5))
        sampler.stop()
        await sampling
    finally:
        server.should_exit = True
        await serving


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("role", choices=("reference", "experimental"))
    parser.add_argument("fixture", type=Path)
    parser.add_argument("anchor_ns", type=int)
    parser.add_argument("out", type=Path)
    options = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    group = private_cgroup(options.role)
    clock = Timeline(options)
    try:
        await (reference(clock) if options.role == "reference" else experimental(clock))
    finally:
        stats = {
            name: (group / name).read_text()
            for name in (
                "cpu.stat",
                "memory.peak",
                "memory.events",
                "memory.max",
                "cpu.max",
                "pids.max",
                "io.stat",
            )
        }
        append(options.out / "resources.jsonl", stats)


if __name__ == "__main__":
    asyncio.run(main())
