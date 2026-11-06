"""Reproducible independent sports evidence studies, never trading activation."""

import hashlib
import json
import multiprocessing
import os
import resource
import subprocess
from concurrent.futures import ProcessPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

from neraium_poly.research.phase13.contracts import SportsGame


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _study(name, dataset, frame_path, cutoff):
    from neraium_poly.contracts import MarketSnapshot, OrderBookSnapshot
    from neraium_poly.data import assess_book
    from neraium_poly.research.phase13.mapping import map_market
    from neraium_poly.research.phase13.models import predict_game, verify_prediction
    from neraium_poly.research.phase13.sources import load_sports

    started = datetime.now(UTC)
    data = load_sports(dataset)
    games = [SportsGame.model_validate(g.model_dump() if isinstance(g, SportsGame) else g) for g in data["games"]]
    if name == "qualification":
        result = {
            "dataset_sha256": data["manifest_sha256"],
            "games": len(games), "publisher_reported_final": sum(g.status == "final" for g in games),
            "scheduled": sum(g.status == "scheduled" for g in games),
            "independently_verified_sports_results": 0,
            "earliest_verified_availability": min((g.available_at for g in games), default=None),
            "retrospective_point_in_time_training_events": 0,
            "qualified_certification_training_events": 0, "qualified_certification_heldout_events": 0,
            "certification_requirement": {"training": 100, "heldout": 100},
            "reason": "Retrieval-time records do not establish historical feature vintages, independent verification or calibration",
            "missing_fields": ["historical_availability_vintages", "reviewed_independent_groups",
                               "independent_result_corroboration", "historical_executable_depth",
                               "heldout_model_calibration", "injuries_and_lineups"],
        }
        if result["earliest_verified_availability"]:
            result["earliest_verified_availability"] = result["earliest_verified_availability"].isoformat()
    else:
        raw = json.loads(Path(frame_path).read_text())
        books = {b["token_id"]: OrderBookSnapshot.model_validate(b) for b in raw["books"]}
        estimates, rejected = [], {}
        for value in raw["markets"][:800]:
            market = MarketSnapshot.model_validate(value)
            try:
                mapping = map_market(market, games, now=cutoff)
                game = next(g for g in games if g.game_id == mapping.game_id and g.provider == mapping.provider)
                prediction = predict_game(games, game, mapping.selected_team_id, cutoff, method="frequency")
                if verify_prediction(prediction, games, game) is not True:
                    raise ValueError("model_replay_failed")
                book = books.get(market.token_id)
                valid = assess_book(book, cutoff, expected_token=market.token_id, max_spread=0.05).healthy
                estimates.append({
                    "mapping": mapping.model_dump(mode="json"), "prediction": prediction.model_dump(mode="json"),
                    "market_quote": book.model_dump(mode="json") if valid else None,
                    "market_win_probability": None,
                    "quote_interpretation": "expected fractional contract payout, not unconditional win probability",
                    "binary_forecast_ledger_admissible": False,
                    "prospective_forecast_recorded": False,
                    "status": "unrecorded_ternary_research_estimate; not paper activity",
                })
            except ValueError as error:
                reason = str(error)[:180]
                rejected[reason] = rejected.get(reason, 0) + 1
        result = {
            "dataset_sha256": data["manifest_sha256"], "cutoff": cutoff.isoformat(),
            "hypothesis": "External participant/opponent historical form can inform future win/tie/loss forecasts",
            "estimates": estimates, "rejections": rejected,
            "brier": None, "log_loss": None, "calibration": None, "confidence_interval": None,
            "market_baseline_skill_comparison": None, "cost_adjusted_trading_performance": None,
            "reason": "No prospectively verified resolved independent cohort; single payout quote is not a ternary probability distribution",
            "training_interval": "Explicit per-prediction causal two-year lookback, first-observed availability required",
            "validation_interval": None, "heldout_interval": None,
            "trading_authority": False, "certification_authority": False,
        }
    completed = datetime.now(UTC)
    return result, {"study": name, "pid": os.getpid(), "started_at": started.isoformat(),
                    "completed_at": completed.isoformat(), "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                    "numerical_threads": 1}


def run_sports_research(dataset, frame_path, output, *, workers=2, cutoff=None):
    """Read verified source artifacts and frozen actual frame using bounded CPU jobs."""
    if type(workers) is not int or workers not in (1, 2):
        raise ValueError("sports research permits one or two workers")
    output = Path(output)
    if output.exists():
        raise ValueError("new immutable research output required")
    dataset, frame_path = Path(dataset).resolve(), Path(frame_path).resolve()
    if frame_path.stat().st_size > 16 * 1024**2:
        raise ValueError("bounded authentic market frame required")
    cutoff = cutoff or datetime.now(UTC)
    if cutoff.tzinfo is None or cutoff > datetime.now(UTC):
        raise ValueError("aware nonfuture cutoff required")
    for key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
        os.environ[key] = "1"
    names = ("qualification", "models")
    if workers == 2:
        with ProcessPoolExecutor(max_workers=2, mp_context=multiprocessing.get_context("spawn")) as pool:
            jobs = [pool.submit(_study, name, str(dataset), str(frame_path), cutoff) for name in names]
            values = [f.result() for f in jobs]
    else:
        values = [_study(name, str(dataset), str(frame_path), cutoff) for name in names]
    output.mkdir(parents=True)
    hashes, processes = {}, []
    for name, (result, process) in zip(names, values, strict=True):
        text = json.dumps(result, sort_keys=True, indent=2, allow_nan=False) + "\n"
        (output / (name + ".json")).write_text(text)
        hashes[name] = hashlib.sha256(text.encode()).hexdigest()
        processes.append(process)
    overlap = (workers == 2 and len({p["pid"] for p in processes}) == 2
               and max(p["started_at"] for p in processes) < min(p["completed_at"] for p in processes))
    manifest = {
        "schema_version": "1.0", "cutoff": cutoff.isoformat(), "dataset": str(dataset),
        "market_frame_sha256": hashlib.sha256(frame_path.read_bytes()).hexdigest(),
        "git_head": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "reports": hashes, "workers_requested": workers, "processes": processes,
        "actual_overlapping_studies": 2 if overlap else 1,
        "certification_authority": False, "automatic_promotion": False,
    }
    from neraium_poly.research.phase11.adaptive import ResearchRegistry

    registry = ResearchRegistry(output / "research-models.sqlite")
    try:
        registry.register(
            version_id=_hash(hashes), dataset_sha256=values[0][0]["dataset_sha256"],
            available_at=cutoff,
            metrics=[{"model": "external-sports-frequency", "value": None, "baseline_value": None,
                      "reason": "No prospectively verified resolved cohort"}],
            provenance={"reports": hashes, "git_head": manifest["git_head"],
                        "estimand": "win/tie/loss distribution; payout comparator distinct",
                        "model_hashes": sorted({r["prediction"]["model_sha256"]
                                                for r in values[1][0]["estimates"]}),
                        "rollback": "ResearchRegistry.rollback records research selection only"},
        )
        manifest["model_registry"] = registry.status()
    finally:
        registry.db.close()
        registry.owner.close()
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest
