"""Bounded public GET capture in the Phase 56 tape format."""

import asyncio
import gzip
import json
import shutil
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent
F = json.loads((ROOT / "freeze.json").read_text())
RESERVE = 100 * 2**30


def utc():
    return datetime.now(UTC).isoformat()


async def fetch(client, token):
    start = utc()
    try:
        async with asyncio.timeout(3):
            async with client.stream("GET", "/book", params={"token_id": token}) as response:
                response.raise_for_status()
                payload = bytearray()
                async for chunk in response.aiter_bytes(chunk_size=65536):
                    if len(payload) + len(chunk) > 2**20:
                        raise ValueError("book byte cap")
                    payload.extend(chunk)
            book = json.loads(payload)
            if book["asset_id"] != token or not all(isinstance(book[k], list) for k in ("asks", "bids")):
                raise ValueError("book identity or format")
        return dict(token=token, started=start, received=utc(), book=book)
    except (httpx.HTTPError, TimeoutError, ValueError, KeyError, TypeError) as error:
        return dict(token=token, started=start, received=utc(), error=type(error).__name__)


async def capture(path):
    tokens = [r["token_id"] for m in F["markets"].values() for r in m["rows"]]
    raw_path = path / "holdout.jsonl.gz"
    status = {"start": utc(), "polls": 0, "http_errors": 0, "state": "running"}

    def checkpoint():
        status.update(as_of=utc(), bytes=raw_path.stat().st_size, free_bytes=shutil.disk_usage(path).free)
        tmp = path / "status.tmp"
        tmp.write_text(json.dumps(status, indent=2) + "\n")
        tmp.replace(path / "status.json")

    began = time.monotonic()
    deadline = began + F["duration_seconds"]
    interval = F["capture_interval_seconds"]
    async with httpx.AsyncClient(base_url="https://clob.polymarket.com", trust_env=False) as client:
        with gzip.open(raw_path, "xb", compresslevel=3) as stream:
            while time.monotonic() + 3 < deadline:
                checkpoint()
                if (
                    status["free_bytes"] <= RESERVE + 2**30
                    or status["bytes"] >= F["capture_limit_bytes"] - len(tokens) * 2**20
                ):
                    status["state"] = "storage_guard"
                    break
                tick = time.monotonic()
                row = await asyncio.gather(*(fetch(client, token) for token in tokens))
                stream.write((json.dumps(row, separators=(",", ":")) + "\n").encode())
                stream.flush()
                status["polls"] += 1
                status["http_errors"] += sum("error" in book for book in row)
                await asyncio.sleep(max(0, min(tick + interval, deadline) - time.monotonic()))
    if status["state"] == "running":
        await asyncio.sleep(max(0, deadline - time.monotonic()))
        status["state"] = "complete"
    status["elapsed_seconds"] = time.monotonic() - began
    checkpoint()


if __name__ == "__main__":
    asyncio.run(capture(Path(sys.argv[1])))
