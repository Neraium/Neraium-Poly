"""Verify that both injected read timeouts joined a later producer completion."""

import json
from datetime import datetime, timedelta
from pathlib import Path

root = Path(__file__).resolve().parent / "c"
out = root.parent / "isolated-calibration.json"
requests = list(map(json.loads, (root / "experimental-requests.jsonl").read_text().splitlines()))
producer = {}
for line in (root / "producer.log").read_text().splitlines():
    if "market_frame_timing " in line:
        event = json.loads(line.split("market_frame_timing ", 1)[1])
        producer[event["request_id"]] = event

joins = []
for request in requests:
    if not request.get("error", "").startswith("ReadTimeout:"):
        continue
    span = producer[request["request_id"]]
    finish = datetime.fromisoformat(span["asgi_arrived_at"]) + timedelta(
        seconds=span["stage_seconds"]["final_body_sent"]
    )
    client_finished = datetime.fromisoformat(request["wall_finished_at"])
    late = (finish - client_finished).total_seconds()
    assert late > 0
    joins.append(
        {
            "request_id": request["request_id"],
            "ordinal": request["ordinal"],
            "client_failure_stage": request["http_failure_stage"],
            "read_timeout_seconds": request["duration_seconds"],
            "producer_finished_after_timeout_seconds": late,
        }
    )
assert [(r["ordinal"], r["client_failure_stage"]) for r in joins] == [
    (1, "receive_response_headers"),
    (3, "receive_response_body"),
]
out.write_text(
    json.dumps(
        {"scope": "injected-only positive control, separate from primary study", "joined_timeouts": joins},
        indent=2,
    )
    + "\n"
)
print(out.read_text())
