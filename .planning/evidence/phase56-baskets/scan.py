"""Paper-only depth scanner and bounded sequential basket replay."""

import gzip
import json
import math
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
EPS = 1e-8
F = json.loads((ROOT / "freeze.json").read_text())


def at(value):
    return datetime.fromisoformat(value).timestamp()


def compatible_rules(markets, keys):
    rules = [markets[k]["rows"][0] for k in keys]
    return len({(r["resolution_rules"], r["resolution_source"], r["end_time"]) for r in rules}) == 1


def payout_floor(rows):
    if not rows or len({len(r) for r in rows}) != 1:
        raise ValueError("explicit payoff states required")
    if any(not 0 <= p <= 1 for row in rows for p in row):
        raise ValueError("invalid payoff")
    return min(map(sum, rows))


def fill(levels, quantity, rate, *, buy, limit):
    filled = principal = fees = 0.0
    worst = None
    for price, depth in sorted(levels.items(), reverse=not buy):
        if (buy and price > limit + EPS) or (not buy and price < limit - EPS):
            break
        q = min(depth, quantity - filled)
        if q <= EPS:
            break
        filled += q
        principal += price * q
        fees += math.ceil(q * rate * price * (1 - price) * 1e5 - EPS) / 1e5
        worst = price
    return {"quantity": filled, "principal": principal, "fees": fees, "limit": worst}


def size_search(books, rates, minimum, *, buy, floor, cash, conversion):
    """Walk equal-size depth in cent-share steps. Break once marginal economics cannot improve."""
    capacity = min(sum(b.values()) for b in books)
    if not buy:
        capacity = min(capacity, cash - conversion)
    cap = math.floor((capacity + EPS) * 100)
    start = math.ceil(minimum * 100 - EPS)
    best = None
    profitable_max = 0
    top = sum((min(b) if buy else max(b)) for b in books)
    no_edge_at_top = (top >= floor) if buy else (top <= 1)
    for units in range(start, cap + 1):
        q = units / 100
        legs = [
            fill(b, q, rate, buy=buy, limit=1 if buy else 0) for b, rate in zip(books, rates, strict=True)
        ]
        principal = sum(l["principal"] for l in legs)
        fees = sum(l["fees"] for l in legs)
        capital = (principal + fees if buy else q) + conversion
        if capital > cash + EPS:
            break
        gross = q * floor - principal if buy else principal - q
        net = gross - fees - conversion
        candidate = {
            "quantity": q,
            "legs": legs,
            "gross_edge": gross,
            "net": net,
            "fees": fees,
            "minimum_payout": q * floor if buy else q,
            "capital": capital,
        }
        if best is None or net > best["net"] + EPS:
            best = candidate
        if net > EPS:
            profitable_max = q
        if no_edge_at_top:
            break
        worst = sum(l["limit"] for l in legs)
        if ((worst >= floor) if buy else (worst <= 1)) and net < -EPS:
            break
    return None if best is None else {**best, "largest_profitable_shares": profitable_max}


class Depth:
    """A repeated snapshot cannot restore consumed quantity."""

    def __init__(self):
        self.last = {}
        self.remaining = {}

    def observe(self, key, levels):
        old = self.last.get(key, {})
        remaining = self.remaining.get(key, {})
        self.remaining[key] = {
            p: min(q, remaining.get(p, 0) + max(0, q - old.get(p, 0))) for p, q in levels.items()
        }
        self.last[key] = levels

    def execute(self, key, qty, rate, *, buy, limit):
        levels = self.remaining.get(key, {})
        result = fill(levels, qty, rate, buy=buy, limit=limit)
        left = result["quantity"]
        for price in sorted(levels, reverse=not buy):
            take = min(left, levels[price])
            levels[price] -= take
            left -= take
            if left < EPS:
                break
        return result


def attempt(depth, tokens, rates, decision, arrivals, buy, conversion, floor=1):
    """Synthetic/paper transaction primitive. Missing arrival quotes yield no leg fill."""
    q = decision["quantity"]
    results = []
    for token, rate, leg, arrival in zip(tokens, rates, decision["legs"], arrivals[:2], strict=True):
        if arrival is None:
            results.append({"quantity": 0, "principal": 0, "fees": 0})
            continue
        depth.observe((token, buy), arrival)
        results.append(depth.execute((token, buy), q, rate, buy=buy, limit=leg["limit"]))
    quantities = [l["quantity"] for l in results]
    if buy:
        cash_delta = -sum(l["principal"] + l["fees"] for l in results)
        matched = min(quantities)
        left = [v - matched for v in quantities]
        cash_delta += matched * floor
    else:
        cash_delta = sum(l["principal"] - l["fees"] for l in results) - q
        matched = min(q - v for v in quantities)
        cash_delta += matched
        left = [q - v - matched for v in quantities]
    unwinds = []
    for i, (token, rate, amount) in enumerate(zip(tokens, rates, left, strict=True)):
        if amount <= EPS or arrivals[2 + i] is None:
            continue
        depth.observe((token, False), arrivals[2 + i])
        sale = depth.execute((token, False), amount, rate, buy=False, limit=0)
        left[i] -= sale["quantity"]
        cash_delta += sale["principal"] - sale["fees"]
        unwinds.append(sale)
    cash_delta -= conversion
    return {
        "complete": all(v >= q - EPS for v in quantities),
        "legs": results,
        "unwinds": unwinds,
        "residual_shares": left,
        "net": cash_delta if max(left) <= EPS else None,
        "cash_delta": cash_delta,
    }


def admitted(arrays, now, *, age=15, skew=2):
    if not all(arrays):
        return False
    return max(r["receipt"] for r in arrays) - min(r["receipt"] for r in arrays) <= skew and all(
        0 <= now - r["receipt"] <= age and 0 <= now - r["exchange"] <= age for r in arrays
    )


def parse(row, index):
    book = row.get("book")
    if not book or book.get("market") != index["native"]["c"] or book.get("neg_risk") is not False:
        return None
    levels = {key: {float(p["price"]): float(p["size"]) for p in book[key]} for key in ("asks", "bids")}
    if any(
        not (0 < p < 1 and math.isfinite(q) and q > 0) for side in levels.values() for p, q in side.items()
    ):
        return None
    if levels["asks"] and levels["bids"] and min(levels["asks"]) <= max(levels["bids"]):
        return None
    return {
        **levels,
        "receipt": at(row["received"]),
        "exchange": int(book["timestamp"]) / 1000,
        "id": book.get("hash"),
        "available_at": row["received"],
    }


def scan():
    refs = {r["token_id"]: meta for meta in F["markets"].values() for r in meta["rows"]}
    seen = set()
    rows = []
    attempts = []
    rejects = Counter()
    receipts = []
    depth = Depth()
    cash = F["cash"]
    peak = 0
    pending = None
    with gzip.open(ROOT / "holdout.jsonl.gz", "rt") as stream:
        for line in stream:
            sample = json.loads(line)
            now = max(at(r["received"]) for r in sample)
            receipts.append(now)
            snapshots = {r["token"]: parse(r, refs[r["token"]]) for r in sample}
            if pending and now >= pending["decision_timestamp"] + F["latency_seconds"]:
                record = pending
                arms = [snapshots.get(t) for t in record["tokens"]]
                # Use a later completed synchronous batch, with a separate next
                # batch for the second leg and a third one for residual unwinds.
                if len(record["arrivals"]) < 2:
                    i = len(record["arrivals"])
                    row = arms[i]
                    arrival_min = record["decision_timestamp"] + F["latency_seconds"] * (i + 1)
                    record["arrivals"].append(
                        row[record["side"]]
                        if admitted([row], now) and row["receipt"] >= arrival_min
                        else None
                    )
                else:
                    record["arrivals"].extend(row["bids"] if admitted([row], now) else None for row in arms)
                    result = attempt(
                        depth,
                        record["tokens"],
                        record["rates"],
                        record,
                        record.pop("arrivals"),
                        record["side"] == "asks",
                        F["conversion_cost_sensitivity"],
                    )
                    cash += result["cash_delta"]
                    attempts.append({**record, **result})
                    pending = None
            for relationship in F["relationships"]:
                tokens = relationship["legs"]
                pair = [snapshots.get(t) for t in tokens]
                if not admitted(pair, now):
                    rejects["stale_missing_or_skewed_pair"] += 1
                    continue
                rates = [refs[t]["native"]["fd"]["r"] for t in tokens]
                minimum = max(float(refs[t]["native"]["mos"]) for t in tokens)
                if relationship["kind"] == "complete_set":
                    floor = payout_floor(relationship["payoffs"])
                else:
                    if not compatible_rules(F["markets"], relationship["id"].split("=>")):
                        rejects["cross_condition_mismatched_terms"] += 1
                        continue
                    states = relationship["payoffs"]
                    floor = payout_floor(
                        [
                            *states["price_regions_low_mid_high"],
                            states["both_invalid_half"],
                            states["differential_exception"],
                        ]
                    )
                    if floor < 1:
                        rejects["cross_condition_exception_floor"] += 1
                        continue
                for side in ("asks", "bids"):
                    key = (relationship["id"], side, tuple(tuple(sorted(b[side].items())) for b in pair))
                    if key in seen:
                        rejects["repeat_book_depth"] += 1
                        continue
                    seen.add(key)
                    if not all(b[side] for b in pair):
                        rejects["empty_side"] += 1
                        continue
                    evaluation = size_search(
                        [b[side] for b in pair],
                        rates,
                        minimum,
                        buy=side == "asks",
                        floor=floor,
                        cash=cash,
                        conversion=F["conversion_cost_sensitivity"],
                    )
                    if evaluation is None:
                        rejects["insufficient_depth_or_cash"] += 1
                        continue
                    result = {
                        **evaluation,
                        "side": side,
                        "market": relationship["id"],
                        "tokens": tokens,
                        "rates": rates,
                        "decision_timestamp": now,
                        "original_receipts": [
                            {k: v for k, v in b.items() if k not in ("asks", "bids")} for b in pair
                        ],
                        "reason": "conversion_cost_unverified"
                        if evaluation["net"] > EPS
                        else "nonpositive_net",
                    }
                    rows.append(result)
                    if (
                        evaluation["net"] > EPS
                        and pending is None
                        and not any(max(a["residual_shares"]) > EPS for a in attempts)
                    ):
                        pending = {**result, "arrivals": []}
                        peak = max(peak, result["capital"])
    incomplete_at_end = pending is not None
    if pending:
        arrivals = pending.pop("arrivals")
        result = attempt(
            depth,
            pending["tokens"],
            pending["rates"],
            pending,
            arrivals + [None] * (4 - len(arrivals)),
            pending["side"] == "asks",
            F["conversion_cost_sensitivity"],
        )
        attempts.append({**pending, **result, "endpoint_censored": True})
    (ROOT / "opportunities.jsonl").write_text("".join(json.dumps(row) + "\n" for row in rows))
    out = {
        "polls": len(receipts),
        "markets": len(F["markets"]),
        "hours": (max(receipts) - min(receipts)) / 3600,
        "distinct_priceable_baskets": len(rows),
        "priceable_markets": sorted({r["market"] for r in rows}),
        "best_net_before_conversion": max(
            (r["net"] + F["conversion_cost_sensitivity"] for r in rows), default=None
        ),
        "positive_after_assumed_conversion": sum(r["net"] > EPS for r in rows),
        "distinct_qualified": sum(r["net"] > EPS and F["conversion_cost_verified"] for r in rows),
        "rejects": dict(rejects),
        "attempts": attempts,
        "unconfirmed_at_endpoint": incomplete_at_end,
        "peak_capital": peak,
        "completed": sum(a["complete"] for a in attempts),
        "incomplete": sum(not a["complete"] for a in attempts),
        "net_paper_under_conversion_sensitivity": None
        if any(a["net"] is None for a in attempts)
        else sum(a["net"] for a in attempts),
        "conversion_verified": F["conversion_cost_verified"],
        "unpriced_residual_attempts": sum(a["net"] is None for a in attempts),
        "cash_benchmark": 0,
        "closest": sorted(rows, key=lambda r: r["net"], reverse=True)[:3],
    }
    (ROOT / "scorecard.json").write_text(json.dumps(out, indent=2) + "\n")


if __name__ == "__main__":
    scan()
