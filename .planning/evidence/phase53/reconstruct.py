"""Join retained polls to reports, producer/processing frames and sampler requests."""

import gzip
import json
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from statistics import median

EVIDENCE = Path(__file__).resolve().parents[1]
HERE = Path(__file__).resolve().parent


def rows(path):
    with gzip.open(path, "rt") as source:
        return list(map(json.loads, source))


def seconds(end, start):
    return (datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds()


samples = rows(EVIDENCE / "phase52/freshness-polls.jsonl.gz")
classified = rows(EVIDENCE / "phase52/freshness-summary.traces.jsonl.gz")
legacy = rows(EVIDENCE / "phase49/baseline/summary.traces.jsonl.gz")
requests, frames, processing, reports = {}, {}, {}, {}
joined_polls = []
by_window = defaultdict(list)


def add_request(receipt):
    if not receipt or "read_started_at" not in receipt:
        return None
    request = receipt["read_started_at"]
    fields = {k: v for k, v in receipt.items() if k not in ("decision_at", "processing_frame_id")}
    original = requests.setdefault(request, {})
    for key, value in fields.items():
        assert key not in original or original[key] == value, (request, key)
        original[key] = value
    if frame := receipt.get("frame_id"):
        facts = (receipt["source_timestamp"], receipt["source_available_at"], receipt["producer_health"])
        assert frames.setdefault(frame, facts) == facts
    if derived := receipt.get("processing_frame_id"):
        assert processing.setdefault(derived, receipt["frame_id"]) == receipt["frame_id"]
    return request


for sample, verdict in zip(samples, classified, strict=True):
    report = sample["research"]
    sampler = report["freshness_sample"]["reference"]
    health = sample["health"]["research_reference"]
    for observed in (health, sampler):
        for receipt in observed.get("recent_reads", []):
            add_request(receipt)
        add_request(observed.get("accepted_frame"))
    trace = report["freshness_trace"]
    initial = add_request(trace["initial_read"])
    decisions = [add_request(read) for read in trace["decision_reads"]]
    failure = report["freshness_sample"].get("last_processing_failure")
    if failure:
        add_request(failure.get("initial_read"))
        for decision in failure.get("decision_reads", []):
            add_request(decision)
    published = trace["published_at"]
    document = {
        "initial_request": initial,
        "decision_requests": decisions,
        "decision_reads": [
            {
                "request": read["read_started_at"],
                "decided_at": read["decision_at"],
                "processing_frame_id": read["processing_frame_id"],
            }
            for read in trace["decision_reads"]
        ],
        "journal_processing_frame": verdict["journal_processing_frame"],
        "scheduled_at": trace["scheduled_at"],
        "worker_started_at": trace["worker_started_at"],
        "source_age_at_publication_seconds": trace["source_age_at_publication_seconds"],
        "cycle_seconds": verdict["cycle_seconds"],
    }
    assert reports.setdefault(published, document) == document
    boundary = verdict["observed_boundary"]
    failing_request = None
    if boundary in ("reference_timeout", "producer_degraded"):
        last = sampler["last_failure"]
        matches = [
            r
            for r in sampler["recent_reads"]
            if r.get("read_completed_at") == last["at"] and r.get("error") == last["reason"]
        ]
        assert len(matches) <= 1
        failing_request = add_request(matches[0]) if matches else None
    poll = {
        "at": verdict["at"],
        "window": sample["window"] + 1,
        "report": published,
        "boundary": boundary,
        "veto_request": failing_request,
        "report_age_since_publication": seconds(verdict["at"], published),
        "sampler_accepted_request": add_request(sampler.get("accepted_frame")),
        "latest_processing_failure_at": failure.get("failed_at") if failure else None,
    }
    by_window[poll["window"]].append(poll)
    joined_polls.append(poll)

boundaries = {}
for category, count in Counter(p["boundary"] for p in joined_polls).items():
    group = [p for p in joined_polls if p["boundary"] == category]
    identities = {p["veto_request"] for p in group if p["veto_request"]}
    durations = [seconds(requests[r]["read_completed_at"], r) for r in identities]
    boundaries[category] = {
        "polls": count,
        "unique_report_ids": len({p["report"] for p in group}),
        "distinct_veto_requests": len(identities),
        "unjoined_poll_count": sum(p["veto_request"] is None for p in group)
        if category in ("reference_timeout", "producer_degraded")
        else None,
        "veto_request_duration_seconds": {
            "min": min(durations),
            "median": median(durations),
            "max": max(durations),
        }
        if durations
        else None,
        "veto_requests_with_producer_frame": sum(bool(requests[r].get("frame_id")) for r in identities),
    }
    if category == "producer_degraded":
        boundaries[category]["producer_error_values"] = dict(
            Counter(str(requests[r].get("producer_error")) for r in identities)
        )

# Outage episodes join consecutive failed attempts in the deduplicated request history.
# A known acceptance breaks the episode. Observation gaps never imply contiguity.
ordered = sorted(requests)
episodes = []
group = []
for key in ordered:
    row = requests[key]
    if row.get("status") != "withheld":
        if group:
            episodes.append(group)
        group = []
        continue
    if group and seconds(key, group[-1]) > 10:
        episodes.append(group)
        group = []
    group.append(key)
if group:
    episodes.append(group)
episode_rows = [
    {
        "first_started_at": e[0],
        "last_finished_at": requests[e[-1]]["read_completed_at"],
        "requests": e,
        "reason_counts": dict(Counter(requests[k]["error"] for k in e)),
    }
    for e in episodes
]

expired = [p for p in joined_polls if p["boundary"] == "after_publication_before_sample"]
expiry_details = []
for poll in expired:
    report = reports[poll["report"]]
    ages = [seconds(poll["at"], requests[key]["source_available_at"]) for key in report["decision_requests"]]
    expiry_details.append(
        {
            "poll_at": poll["at"],
            "report": poll["report"],
            "publication_source_age_seconds": report["source_age_at_publication_seconds"],
            "poll_source_age_seconds": max(ages),
            "poll_delay_after_publication_seconds": poll["report_age_since_publication"],
        }
    )
assert sum(v["polls"] for k, v in boundaries.items() if k != "fresh_at_sample") == 107
producer_probe = [
    json.loads(line) for line in (EVIDENCE / "phase49/producer-probe.jsonl").read_text().splitlines()
]
legacy_reports = {}
legacy_failures = {}
legacy_polls = []
for row in legacy:
    if identity := row.get("as_of"):
        document = {
            "processing_available_at": row["processing_frame_available_at"],
            "journal_processing_frame": row["journal_processing_frame"],
            "published_at": row["published_at"],
            "cycle_seconds": row["cycle_seconds"],
        }
        assert legacy_reports.setdefault(identity, document) == document
    observed = row.get("reference_failure")
    failure_at = observed.get("at") if observed else None
    if failure_at:
        assert legacy_failures.setdefault(failure_at, observed) == observed
    legacy_polls.append(
        {
            "at": row["at"],
            "window": row["window"] + 1,
            "legacy_report_as_of": identity,
            "frozen_failure_observation_at": failure_at,
            "status": row["status"],
            "boundary": row["observed_boundary"],
        }
    )
summary = {
    "phase49": {
        "separate_producer_probe_count": len(producer_probe),
        "separate_producer_probe_read_timeouts": sum(
            "ReadTimeout" in r.get("error", "") for r in producer_probe
        ),
        "polls": len(legacy),
        "reports_deduped_by_as_of": len(legacy_reports),
        "journal_processing_frame_ids": len(
            {
                report["journal_processing_frame"]["processing_frame_id"]
                for report in legacy_reports.values()
                if report["journal_processing_frame"]
            }
        ),
        "distinct_failure_timestamps_in_frozen_reports": len(legacy_failures),
        "boundaries": dict(Counter(x["observed_boundary"] for x in legacy)),
        "request_join_gap": "Baseline retains diagnostic counter snapshots without per-request receipts.",
    },
    "phase52": {
        "polls": len(samples),
        "reports": len(reports),
        "producer_frames": len(frames),
        "receipt_processing_frames": len(processing),
        "requests": len(requests),
        "request_states": dict(Counter(x.get("status", "unknown") for x in requests.values())),
        "withheld_request_reasons": dict(
            Counter(x["error"] for x in requests.values() if x.get("status") == "withheld")
        ),
        "boundaries": boundaries,
        "windows": {n: dict(Counter(p["boundary"] for p in ps)) for n, ps in by_window.items()},
        "observed_withholding_episodes": len(episodes),
        "longest_observed_episode_seconds": max(
            seconds(e["last_finished_at"], e["first_started_at"]) for e in episode_rows
        ),
        "episodes_containing_timeout": sum(
            any("ReadTimeout" in requests[k]["error"] for k in e) for e in episodes
        ),
        "oldest_post_publication_expiry_seconds": max(d["poll_source_age_seconds"] for d in expiry_details),
        "expiry_publication_ages_seconds": [
            min(d["publication_source_age_seconds"] for d in expiry_details),
            max(d["publication_source_age_seconds"] for d in expiry_details),
        ],
        "same_report_both_fresh_and_stale": sum(
            len(status) > 1
            for status in (
                {p["boundary"] == "fresh_at_sample" for p in joined_polls if p["report"] == r}
                for r in reports
            )
        ),
    },
}
(HERE / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
data = {
    "phase49_baseline": {
        "reports_keyed_by_as_of": legacy_reports,
        "polls": legacy_polls,
        "failures_observed_in_frozen_reports": legacy_failures,
        "unpaired_producer_probe": producer_probe,
    },
    "requests": requests,
    "producer_frames": frames,
    "derived_processing_frames": processing,
    "reports": reports,
    "polls": joined_polls,
    "episodes": episode_rows,
    "post_publication_expiries": expiry_details,
}
(HERE / "timeline.json.gz").write_bytes(
    gzip.compress(json.dumps(data, separators=(",", ":")).encode(), mtime=0)
)
print(json.dumps(summary, indent=2))
