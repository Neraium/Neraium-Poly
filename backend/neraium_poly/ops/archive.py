"""Public archive dashboard: actual observations, no implicit model activation."""

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from neraium_poly.contracts import MarketSnapshot, OrderBookSnapshot
from neraium_poly.data import assess_book
from neraium_poly.ops.runtime import ResearchRuntime


class PublicArchiveRuntime(ResearchRuntime):
    def __init__(self, path: Path):
        super().__init__()
        if not path.is_file():
            raise ValueError("Run collect first; public archive does not exist")
        self.archive = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True, check_same_thread=False)

    def run_scenario(self):
        raise ValueError(
            "Public archive mode cannot run synthetic scenarios; use a separate research session"
        )

    def state(self):
        self.clock = datetime.now(UTC)
        state = super().state()
        rows = self.archive.execute(
            "SELECT kind,payload FROM events WHERE kind IN ('MarketSnapshot','OrderBookSnapshot') "
            "ORDER BY available_at DESC,id DESC LIMIT 5000"
        ).fetchall()
        markets, books = {}, {}
        for kind, payload in rows:
            if kind == "MarketSnapshot":
                record = MarketSnapshot.model_validate_json(payload)
                markets.setdefault(record.token_id, record)
            else:
                record = OrderBookSnapshot.model_validate_json(payload)
                books.setdefault(record.token_id, record)
        state["markets"] = [r.model_dump(mode="json") for r in markets.values()]
        state["mode"] = "public_readonly"
        state["scenario"] = "Public market archive · paper analysis withheld until model approval"
        state["health"] = [
            {
                "component": r.token_id,
                "status": "healthy" if assess_book(r, self.clock).healthy else "withheld",
                "detail": str(assess_book(r, self.clock).reasons),
            }
            for r in books.values()
        ]
        state["alerts"] = [
            "Public observations only. No real-data model has been approved.",
            "Archive view uses the latest 5,000 market/book records; coverage is bounded.",
        ]
        state["replay_digest"] = "public-archive"
        return state
