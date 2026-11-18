"""Read-only concurrent CLOB order book snapshots, without application changes."""

import asyncio
import gzip
import json
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx

HERE = Path(__file__).resolve().parent
F = json.loads((HERE / "freeze.json").read_text())


async def main():
    tokens = [r["token_id"] for m in F["markets"].values() for r in m["rows"]]
    async with httpx.AsyncClient(timeout=3, trust_env=False) as client:

        async def get(token):
            started = datetime.now(UTC).isoformat()
            try:
                result = await client.get("https://clob.polymarket.com/book", params={"token_id": token})
                result.raise_for_status()
                value = result.json()
                assert value["asset_id"] == token
                return {
                    "token": token,
                    "started": started,
                    "received": datetime.now(UTC).isoformat(),
                    "book": value,
                }
            except (httpx.HTTPError, ValueError, AssertionError) as error:
                return {
                    "token": token,
                    "started": started,
                    "received": datetime.now(UTC).isoformat(),
                    "error": type(error).__name__,
                }

        began = time.monotonic()
        with gzip.open(HERE / "holdout.jsonl.gz", "xt") as stream:
            while time.monotonic() - began < F["duration_seconds"]:
                sample = time.monotonic()
                row = await asyncio.gather(*(get(token) for token in tokens))
                stream.write(json.dumps(row, separators=(",", ":")) + "\n")
                await asyncio.sleep(max(0, 1 - (time.monotonic() - sample)))


asyncio.run(main())
