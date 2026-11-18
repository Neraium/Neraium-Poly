"""Verify that completed benchmark journals preserve the frozen heads as prefixes."""

import json
import sqlite3
import sys
from collections import Counter
from contextlib import closing
from pathlib import Path
from threading import RLock

from state import EventForecastLedger, SportsForecastJournal, ro

here = Path(__file__).resolve().parent
frozen = json.loads((here / "frozen-state.json").read_bytes())["journals"]
scratch = Path(sys.argv[1])
output = {}

for name in sys.argv[2:]:
    roots = [scratch / "runs" / name / "upper", scratch / "seed"]
    if name == "live":
        roots = [Path("/home/ubuntu/Neraium-Poly/data")]
    report = {}
    for suffix, anchor in frozen.items():
        relative = Path("experimental-paper/event-intelligence") / suffix
        path = next(root / relative for root in roots if (root / relative).is_file())
        if suffix == "sports/prospective.sqlite":
            journal = SportsForecastJournal.__new__(SportsForecastJournal)
            table = "records"
        else:
            journal = EventForecastLedger.__new__(EventForecastLedger)
            journal.max_records = 100000
            table = "journal"
        journal._lock = RLock()
        with closing(ro(path)) as db:
            journal.db = db
            db.row_factory = sqlite3.Row
            db.execute("BEGIN")
            assert db.execute("PRAGMA quick_check").fetchone()[0] == "ok"
            current = journal.verify()
            prefix = db.execute(
                f"SELECT chain FROM {table} ORDER BY seq LIMIT 1 OFFSET ?",
                (anchor["records"] - 1,),
            ).fetchone()
            assert prefix is not None and prefix[0] == anchor["head_sha256"]
            appended = Counter(
                row["kind"] for row in db.execute(
                    f"SELECT kind FROM {table} ORDER BY seq LIMIT -1 OFFSET ?",
                    (anchor["records"],),
                )
            )
            assert sum(appended.values()) == current["records"] - anchor["records"]
        report[suffix] = {
            "frozen_prefix_verified": True,
            "current_head": current,
            "append_counts_by_kind": dict(appended),
        }
    output[name] = report
print(json.dumps(output, indent=2))
