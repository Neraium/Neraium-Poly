"""Bounded read-only Phase 10 diagnostics; never creates trading authority.

A sampled numerical valuation is not a signal census or an executable return.
All freshness is evaluated against the captured decision time, never wall-clock
replay time. Independent event qualification remains separate from quote counts.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import multiprocessing as mp
import os
import sqlite3
import time
from bisect import bisect_left
from collections import Counter, deque
from datetime import datetime, timedelta
from multiprocessing import resource_tracker
from pathlib import Path
from statistics import mean
from urllib.parse import urlparse

from neraium_poly.contracts import MarketSnapshot, OrderBookSnapshot
from neraium_poly.data import assess_book
from neraium_poly.experimental.strategies import ExperimentalStrategyEngine, QuotePoint
from neraium_poly.research.qualification import _load_proofs


def category(reason):
    """Categorize observed rejection causes without changing any admission rule."""
    if reason in {
        "multi_leg_execution_and_hedging_not_supported",
        "two_sided_inventory_execution_not_supported",
    }:
        return "STRATEGY LIMITATION"
    if reason == "independent_context_verified_labels_and_calibration_required":
        return "CERTIFICATION DEPENDENCY"
    if reason.startswith(
        ("independent", "persistent_contextual", "validated_queue", "insufficient", "unknown")
    ):
        return "MISSING EVIDENCE"
    if reason in {
        "conservative_roundtrip_edge_insufficient",
        "stale_book",
        "missing_book",
        "missing_liquidity",
        "large_spread",
        "out_of_order_book",
    }:
        return "MARKET CONDITION"
    return "UNCLASSIFIED_REQUIRES_REVIEW"


def frame_quality(frame, selected_tokens, fees, checkpoint, now):
    """Audit all exported tokens and the fixed experimental subset separately."""
    if now.tzinfo is None or frame.get("mode") != "real_market_data":
        raise ValueError("authentic real-market frame and aware audit time required")
    markets = [MarketSnapshot.model_validate(x) for x in frame["markets"]]
    books = {x["token_id"]: OrderBookSnapshot.model_validate(x) for x in frame["books"]}
    if len(books) != len(frame["books"]):
        raise ValueError("duplicate book tokens")
    selected = set(selected_tokens)
    engine = ExperimentalStrategyEngine(**checkpoint["policy"])
    engine.restore(checkpoint)
    peers = {}
    for m in markets:
        if m.outcome.casefold() == "yes":
            peers.setdefault(m.event_id, set()).add(m.market_id)
    counts = {"source": Counter(), "experimental": Counter(), "unselected": Counter()}
    rows = []
    for m in markets:
        b = books.get(m.token_id)
        health = assess_book(b, now, max_spread=0.05, expected_token=m.token_id)
        official_book = bool(
            b
            and urlparse(b.source).hostname in {"clob.polymarket.com", "ws-subscriptions-clob.polymarket.com"}
            and urlparse(b.source).scheme in {"https", "wss"}
            and b.market_id == m.market_id
        )
        metadata = bool(
            m.status == "active"
            and m.resolution_rules
            and m.resolution_source
            and (m.end_time is None or m.end_time > now + timedelta(seconds=120))
        )
        fee, fee_reason = engine._fee(fees.get(m.token_id), now)
        horizon, history_reasons = engine._horizon(m.token_id, now)
        bid, ask = (b.bids[0].price, b.asks[0].price) if b and b.bids and b.asks else (None, None)
        minimum_notional = ask * m.min_order_size if ask is not None else None
        # Same maximum 10% participation; this is a quote capacity diagnostic,
        # not a fill, queue estimate, or promise that liquidity survives latency.
        top_depth = b.asks[0].size * ask * 0.1 if ask is not None else 0
        edge = (
            horizon["lower"] * (1 - fee) - ask * (1 + fee) - 0.02
            if horizon and fee is not None and ask is not None
            else None
        )
        flags = {
            "tokens": True,
            "official_book_identity": official_book,
            "active": m.status == "active",
            "metadata_eligible": metadata,
            "rules_and_source_present": bool(m.resolution_rules and m.resolution_source),
            "past_end": bool(m.end_time and m.end_time <= now),
            "fresh_source": bool(b and 0 <= (now - b.timestamp).total_seconds() <= 15),
            "fresh_receipt": bool(b and 0 <= (now - b.available_at).total_seconds() <= 15),
            "healthy_book": health.healthy,
            "known_fresh_fee": fee is not None,
            "matured_forecast_context": horizon is not None,
            "same_event_yes_peer": len(peers.get(m.event_id, ())) >= 2 and m.outcome.casefold() == "yes",
            "minimum_lot_within_standard_cap": minimum_notional is not None and minimum_notional <= 5,
            "top_depth_supports_two_dollars": top_depth >= 2,
            "static_operationally_eligible": metadata
            and health.healthy
            and official_book
            and fee is not None
            and minimum_notional is not None
            and minimum_notional <= 5
            and top_depth >= max(2, minimum_notional),
            "modeled_edge_above_existing_threshold": edge is not None and edge >= 0.03,
        }
        for scope in ("source", "experimental" if m.token_id in selected else "unselected"):
            counts[scope].update(k for k, v in flags.items() if v)
        rows.append(
            {
                "market_id": m.market_id,
                "token_id": m.token_id,
                "event_id": m.event_id,
                "selected": m.token_id in selected,
                "book_id": b.id if b else None,
                "source_timestamp": b.timestamp.isoformat() if b else None,
                "receipt_timestamp": b.available_at.isoformat() if b else None,
                "bid": bid,
                "ask": ask,
                "spread": health.spread,
                "quality_reasons": health.reasons,
                "minimum_lot_notional": minimum_notional,
                "top_ask_capacity_at_ten_percent": top_depth,
                "fee_rate": fee,
                "fee_rejection": fee_reason,
                "history_rejections": history_reasons,
                "modeled_lower_value": horizon["lower"] if horizon else None,
                "modeled_net_edge": edge,
                "flags": flags,
            }
        )
    return {
        "captured_at": now.isoformat(),
        "frame_id": frame["id"],
        "market_count": len({m.market_id for m in markets}),
        "token_count": len(markets),
        "selected_token_count": len(selected),
        "counts": {k: dict(v) for k, v in counts.items()},
        "fee_scope_note": "Locally observed fee cache may only cover selected tokens; unknown outside it is not exchange zero fees.",
        "relationship_scope_note": "Same-event YES peers measure possible statistical graph coverage, never logical completeness or qualified evidence.",
        "expansion_decision": "No automatic expansion: unselected tokens have no matured local forecast context; more market breadth alone supplies no independently demonstrated edge.",
        "volume_and_historical_liquidity": None,
        "volume_limitation": "Exported normalized frame contains no volume; current depth is observed liquidity only.",
        "rows": rows,
    }


def cycle_window(database, *, limit=250, high_water=None):
    """Exact aggregates for bounded stored cycles; numerical samples stay samples."""
    if not 1 <= limit <= 2000:
        raise ValueError("cycle limit must be 1..2000")
    with sqlite3.connect(f"file:{Path(database).resolve()}?mode=ro", uri=True) as conn:
        high_water = high_water or conn.execute("select max(rowid) from events").fetchone()[0]
        raw = conn.execute(
            "select rowid,payload,digest from events where kind='ExperimentalCycle' and rowid<=? order by rowid desc limit ?",
            (high_water, limit),
        ).fetchall()
    reasons, samples, times = Counter(), {}, []
    signals = qualified = 0
    digests = []
    for rowid, payload, digest in reversed(raw):
        # Store encoding may include whitespace; bind exact stored bytes here.
        digests.append(
            {
                "rowid": rowid,
                "stored_digest": digest,
                "payload_sha256": hashlib.sha256(payload.encode()).hexdigest(),
            }
        )
        x = json.loads(payload)
        times.append(x["timestamp"])
        reasons.update(x["rejection_counts"])
        signals += x["signal_count"]
        qualified += x["eligible_count"]
        for s in x.get("representative_rejections", ()):
            bucket = samples.setdefault(
                s["strategy_id"], {"observed_representative_count": 0, "numeric": [], "representatives": []}
            )
            bucket["observed_representative_count"] += 1
            if s.get("estimated_net_edge") is not None:
                bucket["numeric"].append(s["estimated_net_edge"])
            if len(bucket["representatives"]) < 3:
                bucket["representatives"].append(
                    {
                        k: s.get(k)
                        for k in (
                            "id",
                            "timestamp",
                            "market_id",
                            "token_id",
                            "estimated_net_edge",
                            "forecast_value",
                            "lower_value",
                            "upper_value",
                            "fee_rate",
                            "reasons",
                            "diagnostics",
                        )
                    }
                )
    for s in samples.values():
        values = s.pop("numeric")
        s["numeric_sample_count"] = len(values)
        s["numeric_sample_edge_min"] = min(values) if values else None
        s["numeric_sample_edge_max"] = max(values) if values else None
        s["numeric_sample_edge_mean"] = mean(values) if values else None
    categories = Counter()
    for reason, count in reasons.items():
        categories[category(reason)] += count
    return {
        "high_water_rowid": high_water,
        "cycle_limit": limit,
        "cycles": len(raw),
        "first_timestamp": times[0] if times else None,
        "last_timestamp": times[-1] if times else None,
        "new_deduplicated_signals": signals,
        "qualified_opportunities": qualified,
        "rejection_reason_counts": dict(reasons),
        "root_cause_category_counts": dict(categories),
        "strategy_representatives": samples,
        "source_rows": digests,
        "scope": "Stored cycles in fixed high-water window; signals are new deduplicated signal records, reasons nonexclusive. Representative samples cannot estimate full valuation distribution.",
        "false_positive_rate": None,
        "false_positive_limitation": "No qualified, independently outcome-labelled opportunities in this diagnostic.",
        "simulated_execution_return": None,
    }


def historical_audit(dataset, chain):
    directory = Path(dataset)
    manifest = json.loads((directory / "manifest.json").read_bytes())
    data = (directory / "events.jsonl").read_bytes()
    if hashlib.sha256(data).hexdigest() != manifest["events_sha256"]:
        raise ValueError("qualified dataset hash mismatch")
    proofs, digest = _load_proofs(chain)
    rows = [json.loads(x) for x in data.splitlines()]
    deficiencies = Counter(r for x in rows for r in x["deficiencies"])
    return {
        "events": len(rows),
        "official_outcomes": sum(x["official_source_outcome_verified"] for x in rows),
        "replayed_verified_chain_proofs": len(proofs),
        "chain_proofs_sha256": digest,
        "exact_settlement_groups": sum(x["chain_payout_matches_selected_outcome"] for x in rows),
        "missing_conditions": [
            x["condition_id"]
            for x in rows
            if x["official_source_outcome_verified"] and not x["chain_payout_matches_selected_outcome"]
        ],
        "deficiency_counts": dict(deficiencies),
        "certifiable_training_events": 0,
        "certifiable_heldout_events": 0,
        "required_training_events": 100,
        "required_heldout_events": 100,
        "certification_status": "blocked",
        "brier_score": None,
        "log_loss": None,
        "cost_adjusted_performance": None,
        "source_events_sha256": manifest["events_sha256"],
    }


def forecast_baseline_audit(checkpoint, markets):
    """Chronological quote-prefix scoring, without historical fee backdating.

    Scores overlap within a token, and outcomes share events. Therefore labels
    are not independent events and a confidence interval is deliberately null.
    This does not reuse simulated P/L as ground truth.
    """
    engine = ExperimentalStrategyEngine(**checkpoint["policy"])
    engine.restore(checkpoint)
    identities = {m["token_id"]: (m["market_id"], m["event_id"]) for m in markets}
    horizons = engine.horizon_seconds
    all_scores, token_results = [], []
    for token, raw in checkpoint["history"].items():
        rows = [QuotePoint(**point) for point in raw]
        source_times = [point.at.timestamp() for point in rows]
        scores = []
        for i in range(40, len(rows)):
            decision = datetime.fromisoformat(rows[i].available_at)
            if not 0 <= (decision - rows[i].at).total_seconds() <= 15:
                continue
            if any(datetime.fromisoformat(point.available_at) > decision for point in rows[: i + 1]):
                continue
            target = decision.timestamp() + horizons
            j = bisect_left(source_times, target)
            if j >= len(rows) or source_times[j] > target + 30:
                continue
            label_available = datetime.fromisoformat(rows[j].available_at)
            if not 0 <= (label_available - rows[j].at).total_seconds() <= 15:
                continue
            engine.history[token] = deque(rows[: i + 1], maxlen=engine.history_size)
            prediction, _ = engine._horizon(token, decision)
            if prediction is None:
                continue
            truth = rows[j].bid
            scores.append(
                {
                    "decision_id": rows[i].id,
                    "decision_available_at": decision.isoformat(),
                    "label_id": rows[j].id,
                    "label_event_at": rows[j].timestamp,
                    "label_available_at": rows[j].available_at,
                    "forecast": prediction["forecast"],
                    "baseline_bid": rows[i].bid,
                    "observed_future_bid": truth,
                    "forecast_absolute_error": abs(prediction["forecast"] - truth),
                    "baseline_absolute_error": abs(rows[i].bid - truth),
                    "empirical_band_contains_label": prediction["lower"] <= truth <= prediction["upper"],
                    "label_source_delay_after_target_seconds": source_times[j] - target,
                }
            )
        if scores:
            market, event = identities.get(token, (None, None))
            token_results.append(
                {
                    "token_id": token,
                    "market_id": market,
                    "event_id": event,
                    "labels": len(scores),
                    "model_mae": mean(x["forecast_absolute_error"] for x in scores),
                    "unchanged_bid_mae": mean(x["baseline_absolute_error"] for x in scores),
                    "first_decision_at": scores[0]["decision_available_at"],
                    "last_label_at": scores[-1]["label_available_at"],
                    "representatives": scores[:2],
                }
            )
            all_scores.extend(scores)
    n = len(all_scores)
    return {
        "algorithm_version": "chronological-prefix-baseline-v1",
        "strategy_source_sha256": hashlib.sha256(
            (Path(__file__).parent.parent / "experimental" / "strategies.py").read_bytes()
        ).hexdigest(),
        "horizon_seconds": horizons,
        "scored_labels": n,
        "tokens_with_labels": len(token_results),
        "observed_event_ids": len({x["event_id"] for x in token_results if x["event_id"] is not None}),
        "independently_reviewed_events": 0,
        "model_mae": mean(x["forecast_absolute_error"] for x in all_scores) if n else None,
        "unchanged_bid_mae": mean(x["baseline_absolute_error"] for x in all_scores) if n else None,
        "model_less_baseline_absolute_error": mean(
            x["forecast_absolute_error"] - x["baseline_absolute_error"] for x in all_scores
        )
        if n
        else None,
        "empirical_band_label_coverage": mean(x["empirical_band_contains_label"] for x in all_scores)
        if n
        else None,
        "confidence_interval": None,
        "uncertainty_limitation": "Overlapping horizon labels and unreviewed cross-event dependencies preclude an independent-event confidence interval; empirical band coverage is not calibrated probability coverage.",
        "execution_returns": None,
        "historical_fees": None,
        "execution_limitation": "No point-in-time historical fee/fill/slippage path is reconstructed; no execution or P/L claims.",
        "token_results": token_results,
    }


def _worker(kind, args, barrier, output):
    for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
        os.environ[name] = "1"
    barrier.wait(timeout=30)
    start = time.time_ns()
    try:
        result = (
            {
                "quality": frame_quality(*args[0]),
                "cycles": cycle_window(args[1], high_water=args[2]),
                "baseline": forecast_baseline_audit(args[0][3], args[0][0]["markets"]),
            }
            if kind == "quality"
            else historical_audit(*args)
        )
        output.put(
            {
                "kind": kind,
                "pid": os.getpid(),
                "start_ns": start,
                "end_ns": time.time_ns(),
                "cpu_time_seconds": time.process_time(),
                "numerical_threads": 1,
                "result": result,
            }
        )
    except (ValueError, KeyError, TypeError, OSError) as exc:
        output.put({"kind": kind, "error": repr(exc), "pid": os.getpid()})


def run(inputs, database, dataset, chain, output, high_water=None):
    """Two real spawned workers, one bounded cycle/quality and one chain replay."""
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    files = {
        name: json.loads((Path(inputs) / f"{name}.json").read_bytes())
        for name in ("frame", "selected_tokens", "observed_fees", "strategy_engine", "experimental")
    }
    now = datetime.fromisoformat(files["experimental"]["generated_at"])
    quality_args = (
        files["frame"],
        files["selected_tokens"],
        files["observed_fees"],
        files["strategy_engine"],
        now,
    )
    context = mp.get_context("spawn")
    barrier, queue = context.Barrier(2), context.Queue()
    processes = [
        context.Process(
            target=_worker, args=("quality", (quality_args, database, high_water), barrier, queue)
        ),
        context.Process(target=_worker, args=("history", (dataset, chain), barrier, queue)),
    ]
    for process in processes:
        process.start()
    results = [queue.get(timeout=120) for _ in processes]
    for process in processes:
        process.join(timeout=5)
        if process.is_alive():
            process.terminate()
            process.join()
            raise RuntimeError("bounded diagnostic worker timeout")
    if any("error" in r for r in results):
        raise ValueError(results)
    overlap = max(r["start_ns"] for r in results) < min(r["end_ns"] for r in results)
    report = {
        "schema_version": "1.0",
        "dataset_version": "phase10-diagnostics-v1",
        "coordinator_pid": os.getpid(),
        "cpu_workers": 2,
        "resource_tracker_pid": resource_tracker._resource_tracker._pid,
        "observed_job_processes": 3 + int(resource_tracker._resource_tracker._pid is not None),
        "process_count_scope": "coordinator, two spawned CPU workers, multiprocessing resource tracker; queue feeder is a thread",
        "worker_execution_overlap_observed": overlap,
        "worker_processes": [{k: v for k, v in r.items() if k != "result"} for r in results],
        "input_sha256": {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in Path(inputs).glob("*.json")
        },
        "account": {
            k: files["experimental"][k]
            for k in (
                "account_id",
                "cash",
                "equity",
                "simulated_pnl",
                "orders_attempted",
                "orders_submitted",
                "fills",
                "positions",
            )
        },
    }
    for result in results:
        report.update(result["result"] if result["kind"] == "quality" else {"history": result["result"]})
    (output / "report.json").write_text(json.dumps(report, indent=2, sort_keys=True))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for argument in ("inputs", "database", "dataset", "chain", "output"):
        parser.add_argument(f"--{argument}", required=True)
    parser.add_argument("--high-water", type=int)
    run(**vars(parser.parse_args()))
