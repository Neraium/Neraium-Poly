"""Score chronological retained response receipts in a new private paper-research journal."""

import argparse
import gzip
import hashlib
import json
import shutil
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from neraium_poly.data import EventStore
from neraium_poly.experimental.contracts import SharedMarketFrame
from neraium_poly.experimental.feed import SharedFeedClient
from neraium_poly.research.phase14.relationships import digest
from neraium_poly.research.phase17.provenance import ReadonlyArchive
from neraium_poly.research.phase29.costs import replay_fee
from neraium_poly.research.phase42.controller import Controller
from neraium_poly.research.phase44.native import replay as verify_native

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
LOCK = json.loads((HERE / "prospective-lock.json").read_text())


def at(value):
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("Original timezone required")
    return parsed


def run(tape, archive_path, output, proof_paths=()):
    for path, expected in LOCK["file_sha256"].items():
        if hashlib.sha256((ROOT / path).read_bytes()).hexdigest() != expected:
            raise ValueError(f"frozen code differs: {path}")
    start, end = map(at, (LOCK["start"], LOCK["end"]))
    if datetime.now(UTC) < end:
        raise ValueError("Frozen evaluation endpoint has not elapsed")
    output = output.resolve()
    live = Path("/home/ubuntu/Neraium-Poly/data").resolve()
    if output.is_relative_to(live):
        raise ValueError("A new private replay directory is required")
    known = json.loads((HERE / "historical-scorecard.json").read_text())
    prior_markets = set(known["known_prior_market_ids"])
    prior_events = set(known["known_prior_events"])
    output.mkdir(exist_ok=False)

    def can_write():
        return (
            shutil.disk_usage(output).free > 100 * 1024**3 + 16 * 1024**2
            and sum(f.stat().st_size for f in output.iterdir() if f.is_file()) < 1024**3
        )

    archive = ReadonlyArchive(archive_path)
    store = EventStore(output / "shadow.sqlite")
    risk = json.loads((ROOT / "config/experimental-paper.example.json").read_text())["risk_limits"]
    current = [start]
    controller = None
    audit = Counter()
    peak_basis = {}
    seen = set()
    previous = None
    try:
        with gzip.open(tape, "rt") as stream:
            for line in stream:
                if len(line) > 9 * 1024**2 or len(seen) >= 18000:
                    raise ValueError("bounded tape exceeded")
                row = json.loads(line)
                decision = at(row["received_at"])
                if not start <= decision < end or previous is not None and decision <= previous:
                    raise ValueError("out-of-window or nonmonotonic receipt")
                previous = decision
                current[0] = decision
                if row.get("error"):
                    audit["withheld_capture:" + row["error"]] += 1
                    continue
                raw = row["frame"]
                if not isinstance(raw.get("id"), str) or not raw["id"]:
                    raise ValueError("original frame identity required")
                if digest(raw) != row["sha256"]:
                    raise ValueError("frame digest mismatch")
                try:
                    frame = SharedFeedClient.validate(SharedMarketFrame.model_validate(raw), decision)
                except ValueError:
                    audit["stale_identity_or_producer_veto"] += 1
                    continue
                if frame.id in seen:
                    audit["repeated_frame"] += 1
                    continue
                seen.add(frame.id)
                eligible = tuple(
                    m
                    for m in frame.markets
                    if m.market_id not in prior_markets and m.event_id not in prior_events
                )
                audit["known_prior_token_rows"] += len(frame.markets) - len(eligible)
                tokens = {m.token_id for m in eligible}
                frame = frame.model_copy(
                    update={
                        "markets": eligible,
                        "books": tuple(b for b in frame.books if b.token_id in tokens),
                    }
                )
                audit["receipts_with_no_eligible_market"] += not eligible
                for identity in row.get("source_study_ids", []):
                    if not can_write():
                        raise ValueError("private replay capacity reached")
                    record = archive.get(identity)
                    if not record:
                        raise ValueError("missing frozen source record")
                    kind, payload, hash_ = record
                    obj = json.loads(payload)
                    if (
                        kind
                        not in {
                            "DomainResearchStudy",
                            "ChallengerStudy",
                            "RefreshDomainStudy",
                            "RefreshCryptoStudy",
                        }
                        or at(obj["available_at"]) > decision
                        or at(obj["timestamp"]) > decision
                        or hashlib.sha256(payload.encode()).hexdigest() != hash_
                    ):
                        raise ValueError("invalid causal study")
                    store._append_payload(
                        identity,
                        kind,
                        at(obj["available_at"]).isoformat(),
                        at(obj["timestamp"]).isoformat(),
                        payload,
                    )
                fees = {
                    token: replay_fee({"evidence_id": identity}, archive, token_id=token, as_of=decision)
                    for token, identity in row.get("fee_observation_ids", {}).items()
                }
                if controller is None:
                    controller = Controller(
                        store,
                        risk_limits=risk,
                        clock=lambda: current[0],
                        can_write=can_write,
                        directory=output / "native",
                    )
                controller.tick(frame, fees)
                audit["evaluated_frames"] += 1
                for profile_name, profile in controller.explorer.state["profiles"].items():
                    for strategy in controller.explorer.definitions:
                        key = (profile_name, strategy)
                        basis = sum(
                            p["cost"] for p in profile["positions"].values() if p["strategy"] == strategy
                        )
                        peak_basis[key] = max(peak_basis.get(key, 0.0), basis)
        if proof_paths:
            if controller is None or len(proof_paths) > 128:
                raise ValueError("bounded replay requires evaluated frames")
            proofs = {}
            for path in proof_paths:
                proof = verify_native(path)
                if at(proof["available_at"]) > end or at(proof["resolved_at"]) > end:
                    raise ValueError("native proof outside frozen evaluation horizon")
                identity = proof["forecast_id"]
                if identity in proofs and proofs[identity] != proof:
                    raise ValueError("conflicting native payout")
                proofs[identity] = proof
            current[0] = end
            controller.explorer.settle(proofs)
        report = controller.explorer.report() if controller else None
        outcomes = {}
        if controller:
            for name, profile in controller.explorer.state["profiles"].items():
                outcomes[name] = {}
                for strategy in controller.explorer.definitions:
                    events = {}
                    equity = peak = drawdown = 0.0
                    for closed in profile["closed"]:
                        if closed["strategy"] != strategy:
                            continue
                        amount = closed["pnl"]
                        equity += amount
                        peak = max(peak, equity)
                        drawdown = max(drawdown, peak - equity)
                        parent = closed["event_id"]
                        events[parent] = events.get(parent, 0.0) + amount
                    trades = [
                        t
                        for t in report["loss_attribution"]["trades"]
                        if t["profile"] == name and t["strategy"] == strategy
                    ]
                    completed = [t for t in trades if t["remaining_quantity"] <= 1e-8]
                    closed_net = sum(t["modeled_exit_pnl"] + t["native_settlement_pnl"] for t in completed)
                    known_gross = sum(
                        t["gross_price_pnl"]
                        + (
                            t["native_payout_value"] - t["entry_principal"] + t["allocated_entry_principal"]
                            if "native_payout_value" in t
                            else 0.0
                        )
                        for t in trades
                    )
                    outcomes[name][strategy] = {
                        "net_by_parent_event": events,
                        "filled_order_ids": len(trades),
                        "completed_orders": len(completed),
                        "peak_filled_principal_at_risk": peak_basis.get((name, strategy), 0.0),
                        "gross_executable_price_before_costs": known_gross,
                        "net_per_completed_order": closed_net / len(completed) if completed else None,
                        "completed_with_verified_entry_fee": sum(bool(t["fee_verified"]) for t in completed),
                        "fill_sensitivity": "fixed modeled participation; venue fills and a stricter fill counterfactual are unobserved",
                        "veto_counts": {
                            k.split(":", 1)[1]: v
                            for k, v in profile["rejects"].items()
                            if k.startswith(strategy + ":")
                        },
                        "net_without_best_event": equity - max(events.values()) if events else None,
                        "realized_only_drawdown": drawdown,
                        "no_trade_benchmark_dollars": 0,
                        "risk_note": "actual portfolio drawdown also reflects open positions when marked; see engine report",
                    }
        (output / "scorecard.json").write_text(
            json.dumps(
                {
                    "baseline_net_dollars": 0,
                    "frozen_window": LOCK,
                    "funnel": dict(audit),
                    "explorer": report,
                    "concentration_and_realized_drawdown": outcomes,
                    "end_of_tape": previous.isoformat() if previous else None,
                    "limitations": "report follows the supplied recorded receipts only; no forced exit or synthesized native settlement; no multiplicity-adjusted winner declared",
                },
                indent=2,
            )
            + "\n"
        )
    finally:
        store.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("tape", "archive", "output"):
        parser.add_argument(name, type=Path)
    parser.add_argument("--native-proof", type=Path, action="append", default=[])
    args = parser.parse_args()
    run(args.tape, args.archive, args.output, args.native_proof)
