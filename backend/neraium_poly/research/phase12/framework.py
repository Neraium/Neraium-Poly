"""Versioned event-outcome research reports and actual bounded CPU workers."""

import hashlib
import json
import multiprocessing as mp
import os
import resource
import shutil
from concurrent.futures import ProcessPoolExecutor
from datetime import UTC, datetime
from multiprocessing import resource_tracker
from pathlib import Path


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _worker(study, directory):
    for name in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
        os.environ[name] = "1"
    started = datetime.now(UTC).isoformat()
    from neraium_poly.research.phase12.dataset import load_dataset

    dataset = load_dataset(directory)
    if study == "models":
        from neraium_poly.research.phase12.models import run_event_models

        result = run_event_models(dataset)
    elif study == "relationships":
        from neraium_poly.research.phase12.relationships import run_event_relationships

        result = run_event_relationships(dataset)
    elif study == "categories":
        from neraium_poly.research.phase12.categories import run_categories

        result = run_categories(dataset)
    else:
        raise ValueError("unsupported event study")
    return result, {
        "study": study,
        "pid": os.getpid(),
        "started_at": started,
        "completed_at": datetime.now(UTC).isoformat(),
        "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "numerical_threads": 1,
    }


def run_event_research(dataset, output, *, workers=2):
    dataset, output = Path(dataset).resolve(), Path(output).resolve()
    if workers not in (1, 2) or (workers == 2 and (os.cpu_count() or 1) < 4):
        raise ValueError("one or two bounded CPU workers required")
    if output.exists():
        raise ValueError("new event research output required")
    output.parent.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(output.parent).free < 8 * 1024**3:
        raise ValueError("event research disk floor reached")
    source = {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(Path(__file__).parent.glob("*.py"))
    }
    input_manifest_bytes = (dataset / "manifest.json").read_bytes()
    input_manifest = json.loads(input_manifest_bytes)
    studies = ("models", "relationships", "categories")
    with ProcessPoolExecutor(max_workers=workers, mp_context=mp.get_context("spawn")) as pool:
        futures = {name: pool.submit(_worker, name, str(dataset)) for name in studies}
        results = {name: future.result() for name, future in futures.items()}
    output.mkdir()
    files = {}
    for name, (result, _) in results.items():
        payload = (canonical(result) + "\n").encode()
        if len(payload) > 8 * 1024 * 1024:
            raise ValueError("event report byte budget exceeded")
        path = output / (name + ".json")
        path.write_bytes(payload)
        files[path.name] = hashlib.sha256(payload).hexdigest()
    tasks = [r[1] for r in results.values()]
    active = peak = 0
    for _, delta in sorted([(t["started_at"], 1) for t in tasks] + [(t["completed_at"], -1) for t in tasks]):
        active += delta
        peak = max(peak, active)
    manifest = {
        "schema_version": "1.0",
        "generated_at": datetime.now(UTC).isoformat(),
        "hypothesis": "Independent point-in-time event evidence may improve terminal-outcome forecasts over contemporaneous market probabilities",
        "dataset_manifest_sha256": hashlib.sha256(input_manifest_bytes).hexdigest(),
        "dataset_sha256": input_manifest.get("dataset_sha256"),
        "source_files": source,
        "output_sha256": files,
        "workers": {
            "requested": workers,
            "actual_pids": sorted({t["pid"] for t in tasks}),
            "coordinator_pid": os.getpid(),
            "resource_tracker_pid": resource_tracker._resource_tracker._pid,
            "peak_concurrent_tasks": peak,
            "tasks": tasks,
        },
        "certification_authority": False,
        "automatic_promotion": False,
        "performance_is_operational_pnl": False,
    }
    from neraium_poly.research.phase11.adaptive import ResearchRegistry
    from neraium_poly.research.phase11.framework import publish_summary
    from neraium_poly.research.phase12.dataset import load_dataset

    verified = load_dataset(dataset)
    source_at = max(r.available_at for key in ("events", "evidence", "outcomes") for r in verified[key])
    model_report = results["models"][0]
    heldout = (model_report.get("results") or {}).get("heldout", {})
    baseline = heldout.get("market_implied", {}).get("brier")
    names = (
        "historical_frequency",
        "bayesian_frequency",
        "independent_logistic",
        "calibrated_independent_logistic",
    )
    comparisons = [
        {
            "model": name,
            "metric": "terminal_brier",
            "value": heldout.get(name, {}).get("brier"),
            "baseline_value": baseline,
            "sample_count": model_report.get("split_counts", {}).get("heldout", 0),
        }
        for name in names
    ]
    identity = hashlib.sha256(canonical([input_manifest, source]).encode()).hexdigest()
    registry = ResearchRegistry(output.parent / "event-research.sqlite")
    try:
        registry.register(
            version_id=identity,
            dataset_sha256=input_manifest["dataset_sha256"],
            available_at=source_at,
            metrics=comparisons,
            provenance={"source_files": source, "result_files": files},
        )
        model_summary = {
            "status": model_report.get("status"),
            "generated_at": datetime.now(UTC).isoformat(),
            "dataset_sha256": input_manifest["dataset_sha256"],
            "model_version_id": identity,
            "funnel": model_report.get("funnel"),
            "split_counts": model_report.get("split_counts"),
            "terminal_probability": model_report.get("terminal_probability"),
            "confidence_interval": model_report.get("confidence_interval"),
            "adaptive": registry.status(),
            "certification_authority": False,
            "automatic_promotion": False,
        }
    finally:
        registry.close()
    publish_summary(output.parent / "latest.json", model_summary)
    manifest["model_version_id"] = identity
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest
