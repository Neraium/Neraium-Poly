"""Reproducible bounded multi-domain studies of authentic captured evidence.

Worker timing belongs to orchestration metadata, never numerical study outputs.
No study records a prospective forecast, trade or qualifying certification event.
"""
import hashlib
import json
import multiprocessing
import os
import resource
import shutil
from collections import Counter, defaultdict, deque
from concurrent.futures import ProcessPoolExecutor
from datetime import UTC, datetime
from itertools import pairwise
from math import log
from pathlib import Path
from statistics import stdev

from neraium_poly.contracts import MarketSnapshot
from neraium_poly.research.phase14.contracts import DomainEvidence, DomainMarket
from neraium_poly.research.phase14.discovery import DOMAINS, classify_market, classify_snapshot
from neraium_poly.research.phase14.finance import closed_candles, digest

MAX_INPUT = 32 * 1024**2
FILES = {"discovery": "discovery/fresh-metadata-v2.json", "weather": "weather/actual-adapter-evidence.json",
         "crypto": "finance/crypto-evidence-v1.json", "economics": "finance/economics-evidence-v1.json"}


def _hash(body):
    return hashlib.sha256(body).hexdigest()


def load_capture(path, *, expected_sha256=None, max_bytes=MAX_INPUT):
    """Reject aliases/oversized captures; preserve exact input bytes and hashes."""
    path = Path(path)
    if any(p.is_symlink() for p in (path, *path.parents)) or not path.is_file() or path.stat().st_nlink != 1:
        raise ValueError("research input aliases or missing files")
    if path.stat().st_size > max_bytes:
        raise ValueError("bounded research capture required")
    body = path.read_bytes()
    actual = _hash(body)
    if expected_sha256 is not None and actual != expected_sha256:
        raise ValueError("research capture changed after manifest")
    return json.loads(body), actual


def _discovery_study(files, hashes):
    captured, _ = load_capture(files["discovery"], expected_sha256=hashes["discovery"])
    baseline, _ = load_capture(files["baseline"], expected_sha256=hashes["baseline"])
    report = captured["report"]
    responses = captured["responses"]
    if not isinstance(responses, list) or not 1 <= len(responses) <= 16:
        raise ValueError("bounded discovery source responses required")
    candidates, total = {}, 0
    for response in responses:
        raw = response["raw_utf8"].encode()
        total += len(raw)
        if _hash(raw) != response["sha256"] or len(raw) != response["bytes"]:
            raise ValueError("discovery original source response hash mismatch")
        path = response["path"]
        if path != "/tags" and path != "/events" and not path.startswith("/tags/slug/"):
            raise ValueError("unapproved discovery source endpoint")
        body = json.loads(raw)
        received = datetime.fromisoformat(response["received_at"])
        if received.tzinfo is None or received > datetime.fromisoformat(report["observed_at"]):
            raise ValueError("invalid captured source availability")
        if path != "/events":
            continue
        if not isinstance(body, list) or len(body) > 500:
            raise ValueError("bounded discovery event list required")
        for event in body:
            for raw_market in event.get("markets", [])[:1000]:
                if len(candidates) >= 2000:
                    break
                merged = {**raw_market, "events": [{"id": event.get("id"), "tags": event.get("tags", []),
                                                   "category": event.get("category")}], "eventId": event.get("id")}
                try:
                    market = classify_market(merged, received)
                except (ValueError, TypeError, KeyError):
                    continue
                if market.status == "active" and raw_market.get("enableOrderBook") is not False and raw_market.get("acceptingOrders") is not False:
                    candidates.setdefault(market.market_id, market)
    buckets = defaultdict(deque)
    for m in sorted(candidates.values(), key=lambda m: (-(m.metadata["liquidity_usd"] or 0), -(m.metadata["volume_24h_usd"] or 0), m.market_id)):
        buckets[m.domain].append(m)
    selected = []
    while len(selected) < 200 and any(buckets.values()):
        for domain in DOMAINS:
            if buckets[domain] and len(selected) < 200:
                selected.append(buckets[domain].popleft())
    original = [DomainMarket.model_validate(m) for m in captured["markets"]]
    if [m.model_dump(mode="json") for m in original] != [m.model_dump(mode="json") for m in selected] or report["candidate_markets"] != len(candidates) or report["selected_markets"] != len(selected) or total != report["response_bytes"]:
        raise ValueError("discovery source normalization/selection report mismatch")
    selected_distribution, candidate_distribution = dict(Counter(m.domain for m in selected)), dict(Counter(m.domain for m in candidates.values()))
    if report["selected_categories"] != selected_distribution or report["candidate_categories"] != candidate_distribution:
        raise ValueError("discovery classification distribution mismatch")
    now = datetime.fromisoformat(report["observed_at"])
    old = {}
    for value in baseline["markets"]:
        m = MarketSnapshot.model_validate(value)
        old.setdefault(m.market_id, classify_snapshot(m, now))
    selected_ids, old_ids = {m.market_id for m in selected}, set(old)
    return {"study": "structured_market_discovery_replay", "source_responses_verified": len(responses),
            "source_bytes": total, "source_cutoff": report["observed_at"], "selected_markets": len(selected),
            "candidate_markets": len(candidates), "candidate_categories": candidate_distribution,
            "selected_categories": selected_distribution, "cached_baseline_markets": len(old),
            "cached_baseline_categories": dict(Counter(m.domain for m in old.values())),
            "new_vs_cached_market_ids": sorted(selected_ids-old_ids), "new_vs_cached_count": len(selected_ids-old_ids),
            "overlap_with_cached_count": len(selected_ids & old_ids),
            "structured_or_source_classification": dict(Counter(m.classification_basis for m in selected)),
            "classification_review_required": sum(m.classification_review_required for m in selected),
            "metadata_with_resolution_rules": sum(bool(m.resolution_rules) for m in selected),
            "metadata_with_resolution_source": sum(bool(m.resolution_source) for m in selected),
            "metadata_with_liquidity": sum(m.metadata["liquidity_usd"] is not None for m in selected),
            "verified_executable_markets": 0, "subscription_expansion_authority": False,
            "probability_forecasts_generated": 0, "brier": None, "log_loss": None, "profitability": None,
            "limitations": ["Bounded category sampling is not the entire exchange", "Metadata is not executable liquidity",
                            "Cached baseline classification has weaker missing structured metadata", "No forecast skill is measured"]}


def verify_evidence(value):
    e = DomainEvidence.model_validate(value)
    if digest(e.payload) != e.content_sha256:
        raise ValueError("domain evidence payload hash mismatch")
    raw = e.payload.get("raw_response_utf8")
    raw_hash = e.payload.get("raw_response_sha256", e.payload.get("raw_sha256"))
    if not isinstance(raw, str) or len(raw.encode()) > 512 * 1024 or _hash(raw.encode()) != raw_hash:
        raise ValueError("domain original source bytes mismatch")
    return e


def _source_study(files, hashes):
    from neraium_poly.research.phase14.contracts import DomainContract
    from neraium_poly.research.phase14.economics import FOMC_CALENDAR
    from neraium_poly.research.phase14.weather import forecast_weather

    crypto, _ = load_capture(files["crypto"], expected_sha256=hashes["crypto"])
    economics, _ = load_capture(files["economics"], expected_sha256=hashes["economics"])
    weather, _ = load_capture(files["weather"], expected_sha256=hashes["weather"])
    if len(crypto) != 1 or len(economics) != 1:
        raise ValueError("one captured source observation per financial domain required")
    c, e = verify_evidence(crypto[0]), verify_evidence(economics[0])
    rows = closed_candles(c, cutoff=c.available_at, symbol="BTCUSDT")
    weather_evidence = tuple(verify_evidence(v) for v in weather["evidence"])
    contract = DomainContract.model_validate(weather["contract"])
    result = forecast_weather(contract, weather_evidence, cutoff=max(v.available_at for v in weather_evidence))
    if result != weather["result"]:
        raise ValueError("weather station/observation qualification replay mismatch")
    if (e.domain != "economics" or e.source != FOMC_CALENDAR or e.payload.get("source_url") != FOMC_CALENDAR
        or "FOMC" not in e.payload["raw_response_utf8"] or e.payload.get("historic_vintage") is not False):
        raise ValueError("official economic context provenance mismatch")
    return {"study": "external_evidence_and_qualification_replay", "sources": {
        "crypto": {"provider": c.provider, "source": c.source, "retrieved_at": c.retrieved_at.isoformat(),
                   "payload_sha256": c.content_sha256, "closed_minutes": len(rows),
                   "first_source_open_ms": rows[0][0], "last_source_close_ms": rows[-1][1],
                   "last_actual_close": rows[-1][2],
                   "sigma_per_sqrt_minute": stdev([log(b[2]/a[2]) for a,b in pairwise(rows)]),
                   "contract_forecast_status": "withheld_unreviewed_candle_close_convention"},
        "weather": {"provider": weather_evidence[0].provider, "retrieved_at": weather_evidence[0].retrieved_at.isoformat(),
                    "payload_sha256": weather_evidence[0].content_sha256, "station": "RKSI",
                    "qualified_observations": result["qualified_observations"], "forecast_result": result},
        "economics": {"provider": e.provider, "source": e.source, "retrieved_at": e.retrieved_at.isoformat(),
                      "payload_sha256": e.content_sha256, "context_only": True, "qualified_vintage_events": 0}},
        "historical_qualification": {"independent_training_events": 0, "independent_heldout_events": 0,
                                     "required_training_events": 100, "required_heldout_events": 100},
        "forecast_records_generated": 0, "resolved_independent_cohort": 0, "brier": None, "log_loss": None,
        "calibration": None, "confidence_interval": None, "market_superiority": None, "profitability": None,
        "limitations": ["Completed underlying price candles are not independent resolved prediction-market events",
                        "Weather observations are not calibrated predictive distributions",
                        "Current official calendar is not a historical economic release vintage",
                        "Raw captures are volatile; this replay does not make them durable or execution certified"]}


def _initializer(barrier):
    barrier.wait(timeout=30)


def _worker(name, files, hashes):
    started = datetime.now(UTC)
    usage = resource.getrusage(resource.RUSAGE_SELF)
    result = _discovery_study(files, hashes) if name == "discovery" else _source_study(files, hashes)
    final = resource.getrusage(resource.RUSAGE_SELF)
    return result, {"study": name, "pid": os.getpid(), "started_at": started.isoformat(),
                    "completed_at": datetime.now(UTC).isoformat(), "peak_rss_kib": final.ru_maxrss,
                    "cpu_seconds": final.ru_utime+final.ru_stime-usage.ru_utime-usage.ru_stime,
                    "numerical_threads": 1}


def run_domain_research(output, *, workers=2, capture_root=Path("/dev/shm/neraium-poly-phase14"),
                        baseline_frame=Path("/home/ubuntu/Neraium-Poly/data/phase14-operations/frame-baseline.json")):
    """Run fixed-input studies; new output only, RAM is explicitly non-durable."""
    if type(workers) is not int or workers not in (1, 2):
        raise ValueError("domain research permits one or two workers")
    output = Path(output)
    if output.exists() or any(p.is_symlink() for p in (output, *output.parents)):
        raise ValueError("new unaliased experiment output required")
    parent = next((p for p in output.parents if p.exists()), None)
    if parent is None or shutil.disk_usage(parent).free < 8 * 1024**3:
        raise ValueError("experiment storage below existing8GiB floor")
    files = {name: str(Path(capture_root)/relative) for name, relative in FILES.items()}
    files["baseline"] = str(baseline_frame)
    total = sum(Path(p).stat().st_size for p in files.values())
    if total > MAX_INPUT:
        raise ValueError("aggregate research input exceeds32MiB")
    hashes = {name: load_capture(path)[1] for name,path in files.items()}
    for key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
        os.environ[key] = "1"
    if workers == 2:
        context = multiprocessing.get_context("spawn")
        with ProcessPoolExecutor(max_workers=2, mp_context=context, initializer=_initializer,
                                 initargs=(context.Barrier(2),)) as pool:
            pending = [pool.submit(_worker, name, files, hashes) for name in ("discovery", "sources")]
            completed = [p.result() for p in pending]
    else:
        completed = [_worker(name, files, hashes) for name in ("discovery", "sources")]
    processes = [v[1] for v in completed]
    overlap = (len({p["pid"] for p in processes}) == 2 and
               max(datetime.fromisoformat(p["started_at"]) for p in processes)
               < min(datetime.fromisoformat(p["completed_at"]) for p in processes))
    reports = {}
    output.mkdir(parents=True)
    for result, process in completed:
        encoded = (json.dumps(result, sort_keys=True, indent=2, allow_nan=False)+"\n").encode()
        if len(encoded)>4*1024**2:
            raise ValueError("bounded study report required")
        name = process["study"]+".json"
        (output/name).write_bytes(encoded)
        reports[name] = _hash(encoded)
    volatile = output.resolve().is_relative_to(Path("/dev/shm"))
    manifest = {"schema_version":"1.0", "input_hashes":hashes,"input_bytes":total,
                "source_files":files,"reports":reports,"workers_requested":workers,
                "processes":processes,"actual_overlapping_workers":2 if overlap else 1,
                "coordinator_pid":os.getpid(),"output_storage":"volatile_tmpfs" if volatile else "persistent_filesystem",
                "raw_capture_durability":"volatile; not execution-certified or qualified for durable forecasts",
                "durable_dataset":False,"forecasts_recorded":0,"certification_authority":False,
                "trading_authority":False}
    (output/"manifest.json").write_text(json.dumps(manifest,sort_keys=True,indent=2)+"\n")
    return manifest
