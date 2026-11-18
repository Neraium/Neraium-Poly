"""Summarize the matched replay and join completed producer records after drain."""

import json
import math
import statistics
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent


def rows(path):
    return list(map(json.loads, path.read_text().splitlines()))


def stats(values):
    values = sorted(values)
    if not values:
        return None
    return {
        "p50": statistics.median(values),
        "p95": values[math.ceil(0.95 * len(values)) - 1],
        "max": values[-1],
    }


def at(t):
    return datetime.fromisoformat(t)


def admission(row):
    return row["status"] == "accepted"


summary = {}
joins = []
for arm, sha in (
    ("a", "8d9756ff8a514ad87947646ffc330f0c3e10efc8"),
    ("b", "cf52778988d26e3d2016bb01cbfe85d212b3f64d"),
    ("d", (HERE / "repair-sha.txt").read_text().strip()),
):
    root = HERE / arm
    requests = rows(root / "experimental-requests.jsonl")
    polls = rows(root / "experimental-polls.jsonl")
    workload = rows(root / "reference-workload.jsonl")
    began = workload[0]
    final = workload[-1]
    assert final["elapsed"] >= 300 and len(requests) >= 55 and len(polls) >= 55
    assert [row["ordinal"] for row in requests] == list(range(1, len(requests) + 1))
    for role, capacity, tasks in (("reference", 1073741824, 64), ("experimental", 2147483648, 32)):
        resource = rows(root / f"{role}-resources.jsonl")[-1]
        assert resource["cpu.max"].strip() == "100000 100000"
        assert int(resource["memory.max"]) == capacity and int(resource["pids.max"]) == tasks
        assert dict(x.split() for x in resource["memory.events"].splitlines())["oom_kill"] == "0"
    rlog = (root / "producer.log").read_text().splitlines()
    traces = [
        json.loads(line.split("market_frame_timing ", 1)[1])
        for line in rlog
        if "market_frame_timing " in line
    ]
    byid = {row["request_id"]: row for row in traces}
    assert len(byid) == len(traces)
    ids = {request["request_id"] for request in requests if request.get("request_id")}
    if arm in ("b", "d"):
        assert len(ids) == len(requests), "client-side request identity collision"
    phases = Counter()
    timings = {
        key: []
        for key in (
            "client_to_asgi",
            "asgi_to_handler",
            "lock_wait",
            "frame_build_under_lock",
            "handler_to_headers",
            "server_body_send",
            "client_headers_to_body_finish",
            "decode",
        )
    }
    for request in requests:
        request_id = request.get("request_id")
        producer = byid.get(request_id)
        stages = request.get("http_stage_seconds", {})
        if "body_complete" in stages and "http11.receive_response_headers.complete" in stages:
            timings["client_headers_to_body_finish"].append(
                stages["body_complete"] - stages["http11.receive_response_headers.complete"]
            )
        if "decoded" in stages and "body_complete" in stages:
            timings["decode"].append(stages["decoded"] - stages["body_complete"])
        if not producer:
            if request_id:
                joins.append({"request_id": request_id, "client": request, "producer": None})
            continue
        if request.get("frame_id"):
            assert producer["frame_id"] == request["frame_id"]
            assert producer["source_available_at"] == request["source_available_at"]
        s = producer["stage_seconds"]
        arrive = at(producer["asgi_arrived_at"])
        timings["client_to_asgi"].append((arrive - at(request["wall_started_at"])).total_seconds())
        for label, end, begin in (
            ("asgi_to_handler", "handler_started", None),
            ("lock_wait", "lock_acquired", "lock_wait_started"),
            ("frame_build_under_lock", "frame_built", "lock_acquired"),
            ("handler_to_headers", "response_start", "handler_returned"),
            ("server_body_send", "final_body_sent", "response_start"),
        ):
            if end in s and (begin is None or begin in s):
                timings[label].append(s[end] - (s[begin] if begin else 0))
        timeout = request.get("error", "").startswith("ReadTimeout:")
        after = None
        if "final_body_sent" in s:
            after = arrive + timedelta(seconds=s["final_body_sent"]) > at(request["wall_finished_at"])
        if timeout and after:
            phases["timeout_before_producer_final_send"] += 1
        joins.append(
            {
                "request_id": request_id,
                "client": request,
                "producer": producer,
                "server_completed_after_client": after,
            }
        )

    timed_out = [r for r in requests if r.get("error", "").startswith("ReadTimeout:")]
    summary[arm] = {
        "source": sha,
        "requests": len(requests),
        "accepted": sum(map(admission, requests)),
        "read_timeouts": len(timed_out),
        "timeout_ordinals": [r["ordinal"] for r in timed_out],
        "withheld": dict(Counter(r["error"] for r in requests if not admission(r))),
        "latency_seconds_all": stats(r["duration_seconds"] for r in requests),
        "latency_seconds_accepted": stats(r["duration_seconds"] for r in requests if admission(r)),
        "fresh_polls": sum(r.get("status") == "fresh" for r in polls),
        "polls": len(polls),
        "poll_outcomes": dict(Counter(r.get("status", r.get("http_error", "missing")) for r in polls)),
        "distinct_published_reports_observed": len(
            {r["report_as_of"] for r in polls if r.get("report_as_of")}
        ),
        "accepted_fresh_books": stats(r["fresh_books"] for r in requests if admission(r)),
        "baseline_market_count": began["warm_markets"],
        "baseline_book_count": began["warm_books"],
        "updates_applied": final["applied"],
        "reference_native_quotes_archived": final["quote_writes"],
        "joined_by_request_id": len(ids & byid.keys()),
        "instrumented_unjoined": len(ids - byid.keys()),
        "producer_unjoined": len(byid.keys() - ids),
        "timeout_with_late_producer_finish": phases["timeout_before_producer_final_send"],
        "timing_seconds": {label: stats(values) for label, values in timings.items()},
    }
(HERE / "measurement.json").write_text(json.dumps(summary, indent=2) + "\n")
with (HERE / "request-joins.jsonl").open("w") as out:
    for item in joins:
        out.write(json.dumps(item, separators=(",", ":")) + "\n")
print(json.dumps(summary, indent=2))
