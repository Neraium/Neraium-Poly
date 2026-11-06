"""Reproducible bounded CPU research; no order/account/promotion interfaces."""

import hashlib
import json
import multiprocessing as mp
import os
import resource
import shutil
import time
from concurrent.futures import ProcessPoolExecutor
from datetime import UTC, datetime
from multiprocessing import resource_tracker
from pathlib import Path

from neraium_poly.research.phase11.adaptive import ResearchRegistry, canonical
from neraium_poly.research.phase11.contracts import ExperimentSpec

STUDIES = ("microstructure", "models", "relationships")


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def source_identity():
    return {p.name: _sha(p) for p in sorted(Path(__file__).parent.glob("*.py"))}


def _worker(study, dataset):
    # Set before any numerical/model import in spawned workers.
    for key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
        os.environ[key] = "1"
    from importlib import import_module

    from neraium_poly.research.phase11.dataset import load_dataset

    start = datetime.now(UTC).isoformat()
    manifest = json.loads((Path(dataset) / "manifest.json").read_text())
    observations = load_dataset(dataset)
    result = getattr(import_module("neraium_poly.research.phase11." + study), "run_" + study)(
        observations, manifest
    )
    ExperimentSpec.model_validate(result["spec"])
    if result["spec"]["dataset_sha256"] != manifest["dataset_sha256"]:
        raise ValueError("study dataset identity mismatch")
    return result, {
        "study": study,
        "pid": os.getpid(),
        "started_at": start,
        "completed_at": datetime.now(UTC).isoformat(),
        "numerical_threads": 1,
        "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
    }


def run_studies(dataset, *, workers=2):
    if workers not in (1, 2) or (workers == 2 and (os.cpu_count() or 1) < 4):
        raise ValueError("one or two bounded workers; leave service capacity")
    with ProcessPoolExecutor(max_workers=workers, mp_context=mp.get_context("spawn")) as pool:
        futures = {s: pool.submit(_worker, s, str(dataset)) for s in STUDIES}
        pairs = {s: f.result() for s, f in futures.items()}
    observations = [v[1] for v in pairs.values()]
    events = sorted(
        [(r["started_at"], 1) for r in observations] + [(r["completed_at"], -1) for r in observations]
    )
    peak = active = 0
    for _, delta in events:
        active += delta
        peak = max(peak, active)
    return {s: r[0] for s, r in pairs.items()}, {
        "coordinator_pid": os.getpid(),
        "resource_tracker_pid": resource_tracker._resource_tracker._pid,
        "requested_workers": workers,
        "actual_cpu_worker_pids": sorted({r["pid"] for r in observations}),
        "peak_concurrent_tasks": peak,
        "tasks": observations,
        "control_processes": "Coordinator plus multiprocessing resource tracker; not CPU workers",
    }


def _budget(output, *, max_bytes=512 * 1024 * 1024):
    # Check the destination filesystem even when intermediate directories do not exist.
    ancestor = output.absolute()
    while not ancestor.exists():
        ancestor = ancestor.parent
    if shutil.disk_usage(ancestor).free < 8 * 1024**3:
        raise ValueError("research free-disk floor reached")
    if output.exists() and sum(p.stat().st_size for p in output.rglob("*") if p.is_file()) >= max_bytes:
        raise ValueError("research artifact storage budget exhausted; preserve prior runs")


def publish_summary(path, report):
    if report.get("certification_authority") is not False or report.get("automatic_promotion") is not False:
        raise ValueError("research summary cannot grant trading authority")
    payload = canonical(report)
    envelope = canonical(
        {"schema_version": "1.0", "report": report, "sha256": hashlib.sha256(payload.encode()).hexdigest()}
    )
    if len(envelope) > 2 * 1024 * 1024:
        raise ValueError("research summary budget exhausted")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".pending")
    with temporary.open("x") as handle:
        handle.write(envelope + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def load_summary(path, *, now=None, max_age_seconds=3600):
    path = Path(path)
    if not path.is_file():
        return {
            "status": "unavailable",
            "reason": "No completed research experiment",
            "certification_authority": False,
            "automatic_promotion": False,
        }
    try:
        if path.stat().st_size > 2 * 1024 * 1024 or path.is_symlink():
            raise ValueError("unsafe or oversized research summary")
        envelope = json.loads(path.read_text())
        report = envelope["report"]
        if (
            envelope["schema_version"] != "1.0"
            or hashlib.sha256(canonical(report).encode()).hexdigest() != envelope["sha256"]
            or report.get("certification_authority") is not False
            or report.get("automatic_promotion") is not False
        ):
            raise ValueError("invalid research integrity or authority")
        generated = datetime.fromisoformat(report["generated_at"])
        current = now or datetime.now(UTC)
        if generated.tzinfo is None or current.tzinfo is None or generated > current or max_age_seconds <= 0:
            raise ValueError("invalid research report generation time")
        age = (current - generated).total_seconds()
        if age > max_age_seconds:
            return {
                **report,
                "status": "stale",
                "report_status": report.get("status"),
                "age_seconds": age,
                "reason": "Research report requires a new observed-data evaluation",
            }
        return report
    except (OSError, ValueError, KeyError, TypeError):
        return {
            "status": "unavailable",
            "reason": "Research report integrity check failed",
            "certification_authority": False,
            "automatic_promotion": False,
        }


def _summary(studies, manifest, registry, experiment_id):
    models = studies["models"]
    selected = models.get("validation_selected_mark_model")
    comparisons = models.get("adaptive_comparisons", [])
    best = next((m for m in comparisons if m.get("model") == selected), None)
    if best:
        best = {
            **best,
            "summary": f"{selected} retained"
            if selected == "unchanged_bid"
            else f"{selected} vs unchanged bid",
        }
    rows = []
    reasons = {
        "short_horizon": ("exploratory_only", "No independently demonstrated cost-adjusted edge"),
        "persistent_relationship": (
            "exploratory_only",
            "Persistent context and executable edge both required",
        ),
        "cross_market_consistency": (
            "suspended_research",
            "Reviewed exhaustive payoff scope and multi-leg execution absent",
        ),
        "liquidity_spread": (
            "suspended_research",
            "Passive queue, adverse selection and two-sided inventory unsupported",
        ),
        "event_driven": ("suspended_research", "Independent timestamped predecision event context absent"),
        "calibrated_forecast": (
            "suspended_research",
            "Independent terminal labels, context and calibrated outcomes absent",
        ),
    }
    for strategy, (status, why) in reasons.items():
        rows.append(
            {
                "strategy_id": strategy,
                "evaluations": None,
                "candidate_signals": None,
                "qualification_rate": None,
                "estimated_net_edge": None,
                "calibration_status": "terminal outcome calibration unavailable",
                "evidence_status": "insufficient independent point-in-time events",
                "experimental_status": "operational gates unchanged",
                "confidence": "exploratory; no credible advantage established",
                "baseline_comparison": best if strategy == "short_horizon" else None,
                "research_status": status,
                "bottleneck": why,
            }
        )
    return {
        "status": "research_complete_no_certified_edge",
        "generated_at": datetime.now(UTC).isoformat(),
        "experiment_id": experiment_id,
        "dataset_sha256": manifest["dataset_sha256"],
        "dataset_interval": manifest.get("availability_interval"),
        "strategies": rows,
        "best_supported_model": selected,
        "calibration_status": "direction only; terminal unavailable",
        "baseline_comparison": best,
        "adaptive": registry.status(),
        "independent_training_events": 0,
        "independent_heldout_events": 0,
        "limitations": [
            "Exploratory observations are dependent; no automatic strategy or account changes",
            "Direction forecasts are not terminal outcome probabilities",
            "Execution sensitivities are research estimates, not account orders or profits",
        ],
        "certification_authority": False,
        "automatic_promotion": False,
    }


def run_experiment(*, dataset, output, workers=2):
    from neraium_poly.research.phase11.dataset import load_dataset

    dataset, output = Path(dataset).resolve(), Path(output).resolve()
    _budget(output)
    if output.exists():
        raise ValueError("new experiment output required; prior runs preserved")
    # Verification before launching workers; malformed datasets cannot become report inputs.
    load_dataset(dataset)
    manifest = json.loads((dataset / "manifest.json").read_text())
    identity = source_identity()
    experiment_id = hashlib.sha256(canonical([manifest["dataset_sha256"], identity]).encode()).hexdigest()[
        :32
    ]
    studies, processes = run_studies(dataset, workers=workers)
    output.mkdir(parents=True)
    hashes = {}
    for name, result in studies.items():
        file = output / (name + ".json")
        file.write_text(canonical(result) + "\n")
        hashes[file.name] = _sha(file)
    registry = ResearchRegistry(output.parent / "research.sqlite")
    try:
        at = datetime.fromisoformat(manifest["availability_interval"][1])
        if at.tzinfo is None:
            raise ValueError("aware research dataset availability required")
        registry.register(
            version_id=experiment_id,
            dataset_sha256=manifest["dataset_sha256"],
            available_at=at,
            metrics=studies["models"].get("adaptive_comparisons", []),
            provenance={"source_files": identity, "study_files": hashes},
        )
        summary = _summary(studies, manifest, registry, experiment_id)
        (output / "summary.json").write_text(canonical(summary) + "\n")
        hashes["summary.json"] = _sha(output / "summary.json")
    finally:
        registry.close()
    record = {
        "schema_version": "1.0",
        "experiment_id": experiment_id,
        "dataset": str(dataset),
        "dataset_sha256": manifest["dataset_sha256"],
        "source_files": identity,
        "result_files": hashes,
        "processes": processes,
        "created_at": datetime.now(UTC).isoformat(),
        "certification_authority": False,
        "automatic_promotion": False,
    }
    (output / "manifest.json").write_text(canonical(record) + "\n")
    publish_summary(output.parent / "latest.json", summary)
    return record


def watch_research(*, database, output, cycles=1, interval=300, limit=20000, workers=2):
    """New immutable windows, bounded runs, persistent drift; no background service deployment."""
    from neraium_poly.research.phase11.dataset import extract_dataset

    if cycles < 0 or interval < 30 or not 100 <= limit <= 30000:
        raise ValueError("bounded cycle/interval/window required")
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    count = 0
    while cycles == 0 or count < cycles:
        _budget(output)
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        dataset = output / ("dataset-" + stamp)
        extract_dataset(database, dataset, limit=limit)
        yield run_experiment(dataset=dataset, output=output / ("run-" + stamp), workers=workers)
        count += 1
        if cycles == 0 or count < cycles:
            time.sleep(interval)
