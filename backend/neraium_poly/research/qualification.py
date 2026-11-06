"""Versioned evidence qualification. It cannot issue strategy certification."""

from __future__ import annotations

import hashlib
import json
import multiprocessing
import os
import time
from concurrent.futures import ProcessPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

from neraium_poly.research.history import load_bundle
from neraium_poly.research.settlement_evidence import canonical


def _market(raw, market_id):
    queue = [raw]
    visited = 0
    while queue:
        item = queue.pop()
        visited += 1
        if visited > 20000:
            raise ValueError("metadata traversal budget exceeded")
        if isinstance(item, list):
            queue.extend(item)
        elif isinstance(item, dict):
            if str(item.get("id", "")) == market_id and item.get("conditionId"):
                return item
            queue.extend(v for v in item.values() if isinstance(v, (list, dict)))
    raise ValueError("original market identity not found")


def _load_proofs(directory):
    if directory is None:
        return {}, None
    directory = Path(directory)
    manifest_raw = (directory / "manifest.json").read_bytes()
    manifest = json.loads(manifest_raw)
    report_raw = (directory / "proofs.json").read_bytes()
    report = json.loads(report_raw)
    if hashlib.sha256(manifest_raw).hexdigest() != report["manifest_sha256"]:
        raise ValueError("chain evidence manifest changed")
    for row in manifest["responses"]:
        path = (directory / row["response_path"]).resolve()
        if not path.is_relative_to(directory.resolve()):
            raise ValueError("chain raw path escapes acquisition")
        raw = path.read_bytes()
        if len(raw) != row["bytes"] or hashlib.sha256(raw).hexdigest() != row["response_sha256"]:
            raise ValueError("chain evidence raw checksum mismatch")
    # Replay all proof assertions from exact archived JSON-RPC responses.
    by_method = {}
    received_by_method = {}
    for row in manifest["responses"]:
        response = json.loads((directory / row["response_path"]).read_bytes())
        request = row["request"]
        if response.get("id") != request["id"] or response.get("jsonrpc") != "2.0" or "error" in response:
            raise ValueError("corrupt chain response binding")
        key = (request["method"], json.dumps(request["params"], sort_keys=True))
        by_method[key] = response.get("result")
        received_by_method[key] = datetime.fromisoformat(row["received_at"])
    if by_method.get(("eth_chainId", "[]")) != "0x89":
        raise ValueError("chain evidence is not Polygon137")
    from neraium_poly.research.settlement_evidence import corroborate_resolution

    finalized = by_method[("eth_getBlockByNumber", '["finalized", false]')]
    logs = []
    for (method, _), result in by_method.items():
        if method == "eth_getLogs":
            logs.extend(result)
    proofs = {}
    for proof in report["proofs"]:
        matching = [
            l
            for l in logs
            if l.get("transactionHash") == proof["transaction_hash"]
            and l.get("logIndex") == proof["log_index"]
        ]
        if len(matching) != 1:
            raise ValueError("ambiguous archived resolution log")
        log = matching[0]
        get = lambda method, params: by_method[(method, json.dumps(params, sort_keys=True))]
        inputs = [
            ("eth_chainId", "[]"),
            ("eth_getBlockByNumber", '["finalized", false]'),
            ("eth_getTransactionReceipt", json.dumps([proof["transaction_hash"]])),
            ("eth_getBlockByHash", json.dumps([proof["block_hash"], False])),
            ("eth_getBlockByNumber", json.dumps([log["blockNumber"], False])),
        ]
        inputs.extend(key for key, result in by_method.items() if key[0] == "eth_getLogs" and log in result)
        acquired = datetime.fromisoformat(proof["available_at"])
        if acquired.tzinfo is None or not max(
            received_by_method[key] for key in inputs
        ) <= acquired <= datetime.now(UTC):
            raise ValueError("chain proof availability backdated or in future")
        replay = corroborate_resolution(
            proof["condition_id"],
            log,
            get("eth_getTransactionReceipt", [proof["transaction_hash"]]),
            get("eth_getBlockByHash", [proof["block_hash"], False]),
            get("eth_getBlockByNumber", [log["blockNumber"], False]),
            finalized,
            available_at=datetime.fromisoformat(proof["available_at"]),
        )
        if replay != proof:
            raise ValueError("normalized chain proof differs from raw replay")
        if proof["condition_id"] in proofs:
            raise ValueError("duplicate resolution proof")
        proofs[proof["condition_id"]] = proof
    return proofs, hashlib.sha256(report_raw).hexdigest()


def _qualify_worker(events, markets, proofs, barrier):
    # Each worker is a distinct single-threaded CPU process. Barrier proves overlap.
    barrier.wait(timeout=30)
    started = time.time_ns()
    rows = []
    for event in events:
        raw = markets[event["market_id"]]
        condition = raw["conditionId"].lower()
        proof = proofs.get(condition)
        prices = event.pop("_price_count")
        token_ids = raw.get("positionIds") if raw.get("version") == "v2" else raw.get("clobTokenIds", [])
        if isinstance(token_ids, str):
            token_ids = json.loads(token_ids)
        index = token_ids.index(event["token_id"]) if event["token_id"] in token_ids else None
        matched = bool(proof and index in (0, 1) and event["outcome"] == proof["payouts"][index])
        reasons = [
            "predecision_availability_not_verified",
            "historical_executable_depth_not_qualified",
            "independent_external_context_not_qualified",
            "historical_rule_version_not_verified",
            "cross_event_dependency_review_required",
        ]
        if not event["outcome_verified"]:
            reasons.append("official_source_outcome_not_verified")
        if not matched:
            reasons.append("exact_finalized_resolution_timing_not_corroborated")
        if not prices:
            reasons.append("pre_resolution_price_history_missing")
        category = event["category"]
        asset = next(
            (
                a
                for a in ("Bitcoin", "Ethereum", "Solana", "XRP", "Dogecoin", "BNB", "Cardano", "Hyperliquid")
                if a.casefold() in event["question"].casefold()
            ),
            None,
        )
        rows.append(
            {
                "schema_version": "1.0",
                "event_id": event["event_id"],
                "market_id": event["market_id"],
                "token_id": event["token_id"],
                "condition_id": condition,
                "category": category,
                "source_record_sha256": hashlib.sha256(canonical(event)).hexdigest(),
                "source_record_id": event["id"],
                "source_raw_sha256": event["raw_sha256"],
                "original_outcome": event["outcome"],
                "official_source_outcome_verified": event["outcome_verified"],
                "chain_payout_matches_selected_outcome": matched,
                "settlement_at": proof["settlement_at"] if matched else None,
                "settlement_evidence_available_at": proof["available_at"] if matched else None,
                "settlement_transaction": proof["transaction_hash"] if matched else None,
                "settlement_block_hash": proof["block_hash"] if matched else None,
                "settlement_log_index": proof["log_index"] if matched else None,
                "availability_basis": event["availability_basis"],
                "source_available_at": event["available_at"],
                "resolution_rules_sha256": hashlib.sha256(event["resolution_rules"].encode()).hexdigest(),
                "historical_rules_verified": False,
                "historical_depth_qualified": False,
                "dependency_group_proposal": f"asset:{asset}" if asset else f"parent:{event['event_id']}",
                "dependency_group_reviewed": False,
                "certification_eligible": False,
                "historical_price_rows": prices,
                "deficiencies": sorted(reasons),
            }
        )
    return {
        "pid": os.getpid(),
        "start_ns": started,
        "end_ns": time.time_ns(),
        "cpu_threads": 1,
        "events_processed": len(rows),
        "rows": rows,
    }


def qualify_history(source_dir, output_dir, *, rpc_evidence_dir=None, workers=2):
    """Integrity-check the source then write an independent qualification dataset.

    The numeric certification policy is neither imported for modification nor
    rewritten. Qualification never creates training rows from repeated books.
    """
    if workers != 2:
        raise ValueError("qualification uses exactly two bounded independent CPU workers")
    for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
        os.environ[name] = "1"
    source, output = Path(source_dir).resolve(), Path(output_dir).resolve()
    if output == source or output.is_relative_to(source):
        raise ValueError("qualification output must not modify source acquisition")
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise ValueError("new versioned qualification directory required")
    bundle = load_bundle(source)
    proofs, proof_digest = _load_proofs(rpc_evidence_dir)
    markets = {}
    counts = {}
    for price in bundle.prices:
        counts[price.event_id] = counts.get(price.event_id, 0) + 1
    events = []
    for event in bundle.events:
        relative = event.raw_ref.split("#")[0]
        path = (source / relative).resolve()
        if not path.is_relative_to(source):
            raise ValueError("original raw path escapes acquisition")
        raw = json.loads(path.read_bytes())
        markets[event.market_id] = _market(raw, event.market_id)
        row = event.model_dump(mode="json")
        row["_price_count"] = counts.get(event.event_id, 0)
        events.append(row)
    context = multiprocessing.get_context("spawn")
    with context.Manager() as manager:
        manager_pid = manager._process.pid
        from multiprocessing import resource_tracker

        tracker_pid = resource_tracker._resource_tracker._pid
        barrier = manager.Barrier(2)
        with ProcessPoolExecutor(max_workers=2, mp_context=context) as pool:
            tasks = [pool.submit(_qualify_worker, events[i::2], markets, proofs, barrier) for i in range(2)]
            results = [task.result(timeout=120) for task in tasks]
    rows = sorted((row for result in results for row in result.pop("rows")), key=lambda row: row["event_id"])
    pids = {r["pid"] for r in results}
    overlap = max(r["start_ns"] for r in results) < min(r["end_ns"] for r in results)
    if len(pids) != 2 or not overlap:
        raise ValueError("two worker execution overlap was not observed")
    payload = b"".join(canonical(row) + b"\n" for row in rows)
    (output / "events.jsonl").write_bytes(payload)
    now = datetime.now(UTC).isoformat()
    manifest = {
        "schema_version": "1.0",
        "dataset_version": "phase9-qualification-v1",
        "created_at": now,
        "source_bundle_sha256": hashlib.sha256((source / "bundle.json").read_bytes()).hexdigest(),
        "source_manifest_sha256": bundle.manifest_sha256,
        "rpc_proofs_sha256": proof_digest,
        "events_sha256": hashlib.sha256(payload).hexdigest(),
        "events_bytes": len(payload),
        "source_path": str(source),
        "chain_evidence_path": str(rpc_evidence_dir) if rpc_evidence_dir else None,
        "workers": results,
        "observed_worker_processes": len(pids),
        "worker_overlap_observed": overlap,
        "numerical_threads_per_worker": 1,
        "coordinator_pid": os.getpid(),
        "manager_pid": manager_pid,
        "resource_tracker_pid": tracker_pid,
        "observed_job_processes": 4 + int(tracker_pid is not None),
        "control_processes": "one manager and one resource tracker (when present); neither is a CPU worker",
    }
    (output / "manifest.json").write_bytes(canonical(manifest))
    report = {
        "schema_version": "1.0",
        "created_at": now,
        "events": len(rows),
        "official_verified_outcome_groups": sum(r["official_source_outcome_verified"] for r in rows),
        "chain_corroborated_exact_settlement_groups": sum(
            r["chain_payout_matches_selected_outcome"] for r in rows
        ),
        "point_in_time_qualified_events": 0,
        "historical_depth_qualified_events": 0,
        "reviewed_independent_events": 0,
        "certifiable_training_events": 0,
        "certifiable_heldout_events": 0,
        "certification_status": "blocked",
        "owner_approval_required": True,
        "strategy_promotion_authority": False,
        "required_training_events": 100,
        "required_heldout_events": 100,
        "cpu_worker_processes": len(pids),
        "worker_overlap_observed": overlap,
        "limitations": [
            "Block event-time does not backdate historical availability",
            "Source/API labels remain distinct from independently linked finalized CTF proof",
            "Publisher L2 rows remain separate and not execution-certified",
            "Asset/window and parent-event deduplication do not prove independence",
            "No current metadata rule text is asserted to be its historical version",
        ],
        "manifest_sha256": hashlib.sha256(canonical(manifest)).hexdigest(),
    }
    (output / "report.json").write_bytes(canonical(report))
    return report
