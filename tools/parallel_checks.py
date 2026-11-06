"""Run disjoint pytest partitions in two real single-threaded CPU worker processes.

Records actual PIDs, launch/completion times and exit codes. No synthetic results.
"""

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path


def main():
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence-dir", type=Path, default=Path(".planning/evidence/phase9"))
    args = parser.parse_args()
    target = root / args.evidence_dir
    target.mkdir(parents=True, exist_ok=True)
    files = sorted(str(p.relative_to(root)) for p in (root / "tests").glob("test_*.py"))
    env = dict(
        os.environ,
        OMP_NUM_THREADS="1",
        OPENBLAS_NUM_THREADS="1",
        MKL_NUM_THREADS="1",
        NUMEXPR_NUM_THREADS="1",
        PAPER_TRADING="true",
        LIVE_TRADING_ENABLED="false",
    )
    logical = os.cpu_count() or 1
    if logical < 4:
        raise SystemExit("Two test workers require at least four logical CPUs; preserve service capacity")
    jobs = []
    for i in range(2):
        output = target / f"backend-worker-{i + 1}.txt"
        handle = output.open("w")
        start = datetime.now(UTC).isoformat()
        process = subprocess.Popen(
            [sys.executable, "-m", "pytest", "-q", *files[i::2]],
            cwd=root,
            env=env,
            stdout=handle,
            stderr=subprocess.STDOUT,
        )
        jobs.append(
            {
                "pid": process.pid,
                "started_at": start,
                "process": process,
                "handle": handle,
                "output": str(output.relative_to(root)),
                "files": files[i::2],
            }
        )
    peak = sum(j["process"].poll() is None for j in jobs)
    while any(j["process"].poll() is None for j in jobs):
        peak = max(peak, sum(j["process"].poll() is None for j in jobs))
        time.sleep(0.1)
    records = []
    for job in jobs:
        job["handle"].close()
        records.append(
            {k: v for k, v in job.items() if k not in ("process", "handle")}
            | {"exit_code": job["process"].returncode, "completed_observed_at": datetime.now(UTC).isoformat()}
        )
    report = {
        "logical_cpus_detected": logical,
        "actual_test_processes": 2,
        "peak_observed_concurrent_processes": peak,
        "numerical_threads_per_worker": 1,
        "workers": records,
    }
    (target / "parallel-tests.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    raise SystemExit(any(r["exit_code"] for r in records))


if __name__ == "__main__":
    main()
