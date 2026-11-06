"""Cost-aware experimental monitoring and bounded real-archive diagnostics.

Simulated results never become independent resolution evidence or certification.
Historical diagnostics score monetary forecasts only; missing historical fees,
strategy scope or fills leave executable P/L null.
"""

from __future__ import annotations

import argparse
import json
import math
import multiprocessing as mp
import os
import shutil
import sqlite3
import time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from statistics import mean

from neraium_poly.contracts import OrderBookSnapshot
from neraium_poly.data import assess_book
from neraium_poly.experimental.strategies import ExperimentalStrategyEngine, QuotePoint
from neraium_poly.research.archive import BookDelta, BookReceipt, apply_observation


class AdaptiveResearchTracker:
    """Descriptive net-result tracking; suspension never grants model approval."""

    def __init__(
        self, bankroll=500.0, strategy_loss_fraction=0.05, drawdown_fraction=0.1, losing_streak_limit=5
    ):
        if (
            not math.isfinite(bankroll)
            or bankroll <= 0
            or not 0 < strategy_loss_fraction <= 0.05
            or not 0 < drawdown_fraction <= 0.1
            or not 1 <= losing_streak_limit <= 20
        ):
            raise ValueError("invalid conservative research monitoring policy")
        self.policy = {
            "bankroll": bankroll,
            "strategy_loss_fraction": strategy_loss_fraction,
            "drawdown_fraction": drawdown_fraction,
            "losing_streak_limit": losing_streak_limit,
        }
        self.results = {}
        self.states = {}

    def record(self, strategy_id, result_id, net_realized_pnl, fees, now, evidence_ids):
        if (
            now.tzinfo is None
            or not result_id
            or not strategy_id
            or not evidence_ids
            or not all(math.isfinite(v) for v in (net_realized_pnl, fees))
            or fees < 0
        ):
            raise ValueError("audited finite cost-adjusted result required")
        payload = {
            "strategy_id": strategy_id,
            "result_id": result_id,
            "net_realized_pnl": net_realized_pnl,
            "fees": fees,
            "timestamp": now.isoformat(),
            "evidence_ids": list(evidence_ids),
        }
        digest = sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
        if result_id in self.results:
            if self.results[result_id] != digest:
                raise ValueError("changed experimental result identity")
            return False
        if len(self.results) >= 100000 or (strategy_id not in self.states and len(self.states) >= 100):
            raise ValueError("monitoring result capacity exceeded")
        state = self.states.setdefault(
            strategy_id,
            {
                "trades": 0,
                "net_realized_pnl": 0.0,
                "fees": 0.0,
                "peak": 0.0,
                "max_drawdown": 0.0,
                "losing_streak": 0,
                "suspended": False,
                "reasons": [],
            },
        )
        state["trades"] += 1
        state["net_realized_pnl"] += net_realized_pnl
        state["fees"] += fees
        state["peak"] = max(state["peak"], state["net_realized_pnl"])
        state["max_drawdown"] = max(state["max_drawdown"], state["peak"] - state["net_realized_pnl"])
        state["losing_streak"] = state["losing_streak"] + 1 if net_realized_pnl < 0 else 0
        reasons = set(state["reasons"])
        if state["net_realized_pnl"] <= -self.policy["bankroll"] * self.policy["strategy_loss_fraction"]:
            reasons.add("strategy_loss_limit")
        if state["max_drawdown"] >= self.policy["bankroll"] * self.policy["drawdown_fraction"]:
            reasons.add("strategy_drawdown_limit")
        if state["losing_streak"] >= self.policy["losing_streak_limit"]:
            reasons.add("losing_streak_suspension")
        state["reasons"] = sorted(reasons)
        state["suspended"] = bool(reasons)
        self.results[result_id] = digest
        return True

    def summary(self):
        return {
            "baseline": {
                "id": "cash_hold_no_trade",
                "initial_bankroll": self.policy["bankroll"],
                "simulated_pnl": 0.0,
                "trades": 0,
            },
            "rankings": [
                {
                    "strategy_id": name,
                    **state,
                    "validation_status": "unvalidated",
                    "certification_eligible": False,
                    "candidate_for_formal_research": state["trades"] >= 20
                    and state["net_realized_pnl"] > 0
                    and not state["suspended"],
                }
                for name, state in sorted(self.states.items(), key=lambda x: -x[1]["net_realized_pnl"])
            ],
            "independent_evidence": False,
            "automatic_certified_promotion": False,
            "limits": "Correlated simulated trades are not independent outcomes or proof of edge",
        }

    def checkpoint(self):
        return json.loads(
            json.dumps(
                {"version": "1.0", "policy": self.policy, "results": self.results, "states": self.states},
                allow_nan=False,
            )
        )

    def restore(self, checkpoint):
        if checkpoint.get("version") != "1.0" or checkpoint.get("policy") != self.policy:
            raise ValueError("monitoring checkpoint policy mismatch")
        if len(checkpoint["results"]) > 100000 or len(checkpoint["states"]) > 100:
            raise ValueError("monitoring checkpoint capacity exceeded")
        for state in checkpoint["states"].values():
            if (
                state["trades"] < 0
                or state["fees"] < 0
                or state["max_drawdown"] < 0
                or not all(
                    math.isfinite(state[k]) for k in ("net_realized_pnl", "fees", "peak", "max_drawdown")
                )
            ):
                raise ValueError("invalid monitoring checkpoint")
        self.results = dict(checkpoint["results"])
        self.states = json.loads(json.dumps(checkpoint["states"], allow_nan=False))


_WORKER_BARRIER = None


def _initialize_worker(barrier):
    global _WORKER_BARRIER
    _WORKER_BARRIER = barrier
    for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
        os.environ[name] = "1"


def _reconstruct(connection, kind, payload, digest):
    if sha256(payload.encode()).hexdigest() != digest:
        raise ValueError("archive payload integrity failure")
    if kind == "OrderBookSnapshot":
        return OrderBookSnapshot.model_validate_json(payload)
    record = (BookDelta if kind == "BookDelta" else BookReceipt).model_validate_json(payload)
    raw = connection.execute(
        "SELECT payload,digest FROM events WHERE id=? AND kind='OrderBookSnapshot'", (record.full_book_id,)
    ).fetchone()
    if raw is None or sha256(raw[0].encode()).hexdigest() != raw[1]:
        raise ValueError("archive baseline integrity failure")
    base = OrderBookSnapshot.model_validate_json(raw[0])
    if base.available_at > record.available_at:
        raise ValueError("archive reference availability failure")
    return apply_observation(base, record)


def _archive_worker(args):
    if _WORKER_BARRIER is not None:
        _WORKER_BARRIER.wait(timeout=30)
    started, cpu_started = time.time(), time.process_time()
    directory, high_water, max_rows, horizon = args
    path = Path(directory).resolve()
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        rows = connection.execute(
            """SELECT kind,payload,digest FROM events WHERE rowid<=?
            AND kind IN ('OrderBookSnapshot','BookDelta','BookReceipt')
            AND json_extract(payload,'$.source') IN
              ('https://clob.polymarket.com','wss://ws-subscriptions-clob.polymarket.com/ws/market')
            ORDER BY rowid DESC LIMIT ?""",
            (high_water, max_rows),
        ).fetchall()
        if sum(len(row[1]) for row in rows) > 100 * 1024 * 1024:
            raise ValueError("bounded archive diagnostic byte budget exceeded")
        window_hash = sha256()
        token_rows = {}
        exclusions = Counter()
        for kind, payload, digest in reversed(rows):
            window_hash.update((kind + payload + digest).encode())
            book = _reconstruct(connection, kind, payload, digest)
            health = assess_book(book, book.available_at, max_spread=0.05)
            if not health.healthy:
                exclusions.update(health.reasons)
                continue
            token_rows.setdefault(book.token_id, {})[book.id] = QuotePoint(
                book.id,
                book.timestamp.isoformat(),
                book.available_at.isoformat(),
                book.bids[0].price,
                book.asks[0].price,
            )
        selected = sorted(token_rows, key=lambda t: (-len(token_rows[t]), t))[:4]
        model_errors, baseline_errors, forecasts = [], [], []
        for token in selected:
            books = sorted(token_rows[token].values(), key=lambda b: (b.available_at, b.timestamp, b.id))
            engine = ExperimentalStrategyEngine(enabled=["short_horizon"], horizon_seconds=horizon)
            seen = []
            for book in books:
                if seen and book.at <= seen[-1].at:
                    exclusions["nonmonotonic_or_duplicate_source_time"] += 1
                    continue
                seen.append(book)
                engine._remember_point(token, book)
                forecast, _ = engine._horizon(token, datetime.fromisoformat(book.available_at))
                if forecast is not None:
                    forecasts.append(
                        {
                            "token": token,
                            "entry": book,
                            "forecast": forecast["forecast"],
                            "reference": book.bid,
                        }
                    )
            by_token = {token: seen}
            for forecast in [r for r in forecasts if r["token"] == token]:
                entry = forecast["entry"]
                eligible = [
                    b
                    for b in by_token[token]
                    if b.at >= datetime.fromisoformat(entry.available_at) + timedelta(seconds=horizon)
                    and b.at <= datetime.fromisoformat(entry.available_at) + timedelta(seconds=horizon + 30)
                    and b.available_at > entry.available_at
                ]
                if not eligible:
                    continue
                future = eligible[0]
                model_errors.append(abs(future.bid - forecast["forecast"]))
                baseline_errors.append(abs(future.bid - forecast["reference"]))
        return {
            "pid": os.getpid(),
            "started_at_unix": started,
            "finished_at_unix": time.time(),
            "cpu_seconds": time.process_time() - cpu_started,
            "horizon_seconds": horizon,
            "snapshot_high_water_rowid": high_water,
            "archive_window_sha256": window_hash.hexdigest(),
            "raw_records_checked": len(rows),
            "tokens_in_window": len(token_rows),
            "selected_tokens": selected,
            "selected_observations": sum(len(token_rows[t]) for t in selected),
            "scored_monetary_forecasts": len(model_errors),
            "future_bid_mae": mean(model_errors) if model_errors else None,
            "unchanged_current_bid_baseline_mae": mean(baseline_errors) if baseline_errors else None,
            "model_comparison": "Monetary forecast diagnostic, not terminal probability calibration or profit",
            "exclusions": dict(exclusions),
            "simulated_orders": None,
            "simulated_fills": None,
            "execution_pnl": None,
            "certification_status": "blocked",
            "deficiencies": [
                "historical_fee_observations_not_bound",
                "sampled_not_complete_tick_history",
                "event_independence_and_rules_not_reviewed",
                "no_certified_execution_simulation",
            ],
            "numerical_threads": {
                name: os.environ.get(name)
                for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS")
            },
        }
    finally:
        connection.close()


def run_archive_diagnostics(archive, output, *, max_rows=24000, high_water_rowid=None):
    """Actually run two independent CPU processes against a fixed readonly window."""
    path = Path(archive).resolve()
    if not path.is_file() or not 100 <= max_rows <= 50000:
        raise ValueError("bounded real archive path and row count required")
    if shutil.disk_usage(path.parent).free < 8 * 1024**3:
        raise ValueError("free disk floor prevents diagnostic work")
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    high_water = connection.execute("SELECT max(rowid) FROM events").fetchone()[0]
    connection.close()
    if high_water_rowid is not None:
        if not isinstance(high_water_rowid, int) or not 0 < high_water_rowid <= high_water:
            raise ValueError("invalid archive snapshot high-water row")
        high_water = high_water_rowid
    context = mp.get_context("spawn")
    barrier = context.Barrier(2)
    with ProcessPoolExecutor(
        max_workers=2, mp_context=context, initializer=_initialize_worker, initargs=(barrier,)
    ) as pool:
        results = list(
            pool.map(_archive_worker, [(str(path), high_water, max_rows, horizon) for horizon in (60, 120)])
        )
    overlap = min(r["finished_at_unix"] for r in results) > max(r["started_at_unix"] for r in results)
    actual_pids = sorted({r["pid"] for r in results})
    report = {
        "version": "1.0",
        "observed_at": datetime.now(UTC).isoformat(),
        "source_archive": str(path),
        "read_only": True,
        "workers_requested": 2,
        "worker_pids": actual_pids,
        "workers_observed": len(actual_pids),
        "overlapping_work_intervals": overlap,
        "max_concurrent_workers_observed": 2 if len(actual_pids) == 2 and overlap else 1,
        "results": results,
        "activation_authority": False,
        "actual_trade_profits_claimed": False,
    }
    target = Path(output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    return report


def main():
    parser = argparse.ArgumentParser(description="Bounded readonly experimental forecast diagnostics")
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-rows", type=int, default=24000)
    parser.add_argument("--high-water-rowid", type=int)
    args = parser.parse_args()
    print(
        json.dumps(
            run_archive_diagnostics(
                args.archive, args.output, max_rows=args.max_rows, high_water_rowid=args.high_water_rowid
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
