"""Coverage and gross episodes alongside the unchanged Phase 56 paper replay."""

import gzip
import hashlib
import importlib.util
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SCANNER = ROOT.parent / "phase56-baskets" / "scan.py"
spec = importlib.util.spec_from_file_location("frozen_scan", SCANNER)
scanner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scanner)
F = json.loads((ROOT / "freeze.json").read_text())


def dump(path, data):
    path.write_text(json.dumps(data, indent=2, allow_nan=False) + "\n")


def measure(tape, status):
    records = {}
    active = {}
    episodes = []
    errors = Counter()
    markets = F["markets"]
    for key, meta in markets.items():
        records[key] = dict(category=meta["category"], seconds=0.0, polls=Counter())
    interval = F["capture_interval_seconds"]
    prev_time = None
    prev_priced = []
    with gzip.open(tape, "rt") as stream:
        for line in stream:
            rows = {row["token"]: row for row in json.loads(line)}
            errors.update(row["error"] for row in rows.values() if "error" in row)
            now = max(scanner.at(row["received"]) for row in rows.values())
            contiguous = prev_time is not None and 0 < now - prev_time <= interval * 1.5
            if contiguous:
                for market in prev_priced:
                    records[market]["seconds"] += min(interval, now - prev_time)
            else:
                active.clear()
            prev_time = now
            prev_priced = []
            for rel in F["relationships"]:
                market = rel["id"]
                meta = markets[market]
                native = meta["native"]
                minimum = float(native["mos"])
                rate = native["fd"]["r"]
                pair = [scanner.parse(rows[t], meta) for t in rel["legs"]]
                decision = "priceable"
                if not all(pair):
                    decision = "missing_or_invalid"
                elif not scanner.admitted(pair, now, age=F["book_age_seconds"], skew=F["receipt_skew_seconds"]):
                    decision = "stale_or_skewed"
                else:
                    # Priceable means at least one executable complete-set direction.
                    directions = [side for side in ("asks", "bids") if all(
                        sum(b[side].values()) + scanner.EPS >= minimum for b in pair
                    )]
                    if not directions:
                        decision = "empty_side" if any(not b[s] for b in pair for s in ("asks", "bids")) else "insufficient_depth"
                records[market]["polls"][decision] += 1
                if decision == "priceable":
                    prev_priced.append(market)
                for side in ("asks", "bids"):
                    key = (market, side)
                    buy = side == "asks"
                    gross = None
                    if decision == "priceable" and side in directions:
                        books = [b[side] for b in pair]
                        top = sum((min(b) if buy else max(b)) for b in books)
                        floor = scanner.payout_floor(rel["payoffs"])
                        if (buy and top < floor) or (not buy and top > 1):
                            gross = scanner.size_search(
                                books, [0, 0], minimum, buy=buy, floor=floor, cash=F["cash"], conversion=0
                            )
                    if gross is None or gross["gross_edge"] <= scanner.EPS:
                        active.pop(key, None)
                        continue
                    sample = {
                        "decision_timestamp": now,
                        "books": [dict(hash=b["id"], exchange=b["exchange"], receipt=b["receipt"]) for b in pair],
                        "gross_optimum": gross,
                        "fee_at_gross_size": sum(scanner.fill(
                            levels, gross["quantity"], rate, buy=buy, limit=1 if buy else 0
                        )["fees"] for levels in books),
                        "net_optimum_under_conversion_sensitivity": scanner.size_search(
                            books, [rate, rate], minimum, buy=buy, floor=floor,
                            cash=F["cash"], conversion=F["conversion_cost_sensitivity"],
                        ),
                    }
                    if key not in active:
                        episode = dict(market=market, category=meta["category"], side=side, start=now, last=now,
                                       polls=0, conversion_verified=F["conversion_cost_verified"],
                                       conversion_sensitivity=F["conversion_cost_sensitivity"], quotes=[])
                        episodes.append(episode)
                        active[key] = episode, set()
                    episode, seen = active[key]
                    episode["last"] = now
                    episode["polls"] += 1
                    signature = tuple(tuple(sorted(levels.items())) for levels in books)
                    if signature not in seen:
                        seen.add(signature)
                        episode["quotes"].append(sample)
    categories = {}
    for market in records.values():
        category = categories.setdefault(market["category"], dict(eligible_market_hours=0.0, priceable_market_hours=0.0))
        market["priceable_market_hours"] = market.pop("seconds") / 3600
        market["eligible_market_hours"] = status["elapsed_seconds"] / 3600
        category["priceable_market_hours"] += market["priceable_market_hours"]
        category["eligible_market_hours"] += market["eligible_market_hours"]
    for episode in episodes:
        episode["observed_span_seconds"] = episode["last"] - episode["start"]
    return dict(markets=records, categories=categories, priceable_market_hours=sum(
        c["priceable_market_hours"] for c in categories.values()
    ), distinct_positive_gross_discrepancies=len(episodes), book_request_errors=dict(errors)), episodes


def main(path, export):
    tape = path / "holdout.jsonl.gz"
    status = json.loads((path / "status.json").read_text())
    if status["state"] not in {"complete", "storage_guard"} or not status["polls"]:
        raise SystemExit("No closed observation tape")
    coverage, episodes = measure(tape, status)
    scanner.ROOT = path
    scanner.F = F
    scanner.scan()
    result = json.loads((path / "scorecard.json").read_text())
    for episode in episodes:
        episode["attempts"] = [
            i for i, a in enumerate(result["attempts"])
            if (a["market"], a["side"]) == (episode["market"], episode["side"])
            and episode["start"] <= a["decision_timestamp"] <= episode["last"]
        ]
    dump(export / "opportunity-ledger.json", episodes)
    with tape.open("rb") as stream:
        tape_hash = hashlib.file_digest(stream, "sha256").hexdigest()
    dump(export / "scorecard.json", dict(
        capture=status, tape_sha256=tape_hash,
        scanner_sha256=hashlib.sha256(SCANNER.read_bytes()).hexdigest(),
        freeze_sha256=hashlib.sha256((ROOT / "freeze.json").read_bytes()).hexdigest(),
        coverage=coverage, frozen_replay=result,
    ))


if __name__ == "__main__":
    main(*(Path(s) for s in sys.argv[1:]))
