"""Matched passive-entry replay from exchange prints and observed book updates."""

import gzip
import json
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
IDENTITY = json.loads((ROOT / "market-identity.json").read_text())
NATIVE = json.loads((ROOT / "fee-source.json").read_text())
UP, DOWN = IDENTITY["secondary_token_id"], IDENTITY["primary_token_id"]
assert NATIVE["c"] == IDENTITY["condition_id"] and {(r["t"], r["o"]) for r in NATIVE["t"]} == {
    (UP, "Up"),
    (DOWN, "Down"),
}
assert NATIVE["fd"]["to"] and NATIVE["fd"]["e"] == 1 and NATIVE["mos"] == 5
RATE = NATIVE["fd"]["r"]
EPS = 1e-9


def seconds(text):
    return datetime.fromisoformat(text).timestamp()


def take(bids, qty):
    amount = qty
    value = fees = 0.0
    fills = []
    for price, depth in sorted(bids.items(), reverse=True):
        q = min(qty, depth)
        if q <= EPS:
            continue
        fee = round(q * RATE * price * (1 - price), 5)
        value += q * price
        fees += fee
        fills.append((price, q))
        qty -= q
    return amount - qty, value, fees, fills


def consume(order, trade_time, price, quantity):
    if (
        not order["effective"]
        <= trade_time
        < min(order["expires"], order.get("cancel_effective", float("inf")))
    ):
        return 0.0
    if abs(order["price"] - price) > EPS:
        return 0.0
    ahead = min(order["ahead"], quantity)
    order["ahead"] -= ahead
    q = min(order["left"], quantity - ahead)
    order["left"] -= q
    return q


def load_tape():
    frames = []
    counts = Counter()
    printed = set()
    with gzip.open(ROOT / "holdout.jsonl.gz", "rt") as stream:
        for line in stream:
            r = json.loads(line)
            if r["raw"] in ("PING", "PONG"):
                continue
            received = seconds(r["received_at"])
            packet = json.loads(r["raw"])
            for item in packet if isinstance(packet, list) else [packet]:
                kind = item.get("event_type", "unknown")
                counts[kind] += 1
                if kind not in ("book", "price_change", "last_trade_price"):
                    continue
                if item["market"] != IDENTITY["condition_id"]:
                    raise ValueError("unexpected condition")
                exchange = float(item["timestamp"]) / 1000
                if kind == "last_trade_price":
                    print_id = json.dumps(item, sort_keys=True)
                    if print_id in printed:
                        counts["duplicate_print"] += 1
                        continue
                    printed.add(print_id)
                if exchange > received + 0.1:
                    counts["future_timestamp"] += 1
                    continue
                frames.append((received, exchange, kind, item))
    return frames, counts


def run(frames, candidate, full_depth):
    books = {x: {"BUY": {}, "SELL": {}, "updated": None} for x in (UP, DOWN)}
    depth_credit = {}
    orders = {}
    cancels = []
    ledger = []
    cash = 500.0
    inventory = basis = realized = drawdown = 0.0
    peak = 500.0
    entry_time = None
    lot_id = None
    order = block = None
    complete = 0
    test_end = frames[-1][0] - 30
    last = None
    veto = Counter()
    pending_exit = None
    for index, (t, x, kind, item) in enumerate(frames):
        if order and t >= order["effective"] and "ahead" not in order:
            b = books[UP]
            if not b["SELL"] or min(b["SELL"]) <= order["price"] or not b["updated"] or t - b["updated"] > 15:
                veto["stale_or_marketable_at_activation"] += 1
                order = None
            else:
                order["ahead"] = b["BUY"].get(order["price"], 0.0) if full_depth else 0.0
                order["down_at_entry"] = max(books[DOWN]["BUY"], default=None)
        # Print execution is ordered by exchange time. Expired orders stay in the
        # bounded registry so that a later-arriving earlier print can be detected.
        if kind == "last_trade_price" and item.get("asset_id") == UP and item.get("side") == "SELL":
            price = float(item["price"])
            eligible = [
                o
                for o in orders.values()
                if "ahead" in o
                and o["left"] > EPS
                and o["effective"] <= x < min(o["expires"], o.get("cancel_effective", float("inf")))
            ]
            if len(eligible) > 1 or (eligible and eligible[0] is not order):
                veto["late_or_ambiguous_print"] += 1
            elif eligible and item.get("size") is not None:
                if (
                    abs(x - eligible[0]["effective"]) <= 0.1
                    or abs(x - eligible[0].get("cancel_effective", float("inf"))) <= 0.1
                ):
                    veto["clock_boundary_print"] += 1
                    continue
                if price < eligible[0]["price"] - EPS:
                    veto["trade_through_at_different_price_not_attributed"] += 1
                q = consume(eligible[0], x, price, float(item["size"]))
                if q > EPS:
                    inventory += q
                    lot_id = order["id"]
                    cost = q * price
                    cash -= cost
                    basis += cost
                    if entry_time is None:
                        entry_time = t
                    ledger.append(
                        {
                            "type": "maker_fill",
                            "id": order["id"],
                            "qty": q,
                            "price": price,
                            "received": t,
                            "exchange": x,
                            "during_cancel_latency": "cancel_effective" in order,
                        }
                    )
            elif eligible:
                veto["unquantified_print"] += 1
        if kind == "book":
            token = item["asset_id"]
            if token not in books:
                raise ValueError("unexpected token")
            for key, field in (("BUY", "bids"), ("SELL", "asks")):
                books[token][key] = {float(p["price"]): float(p["size"]) for p in item[field]}
            books[token]["updated"] = min(t, x)
            touched = {token}
        elif kind == "price_change":
            touched = set()
            for delta in item["price_changes"]:
                token = delta["asset_id"]
                if token not in books:
                    raise ValueError("unexpected token")
                levels = books[token][delta["side"]]
                p, q = float(delta["price"]), float(delta["size"])
                if q > 0:
                    levels[p] = q
                else:
                    levels.pop(p, None)
                if books[token]["updated"] is not None:
                    books[token]["updated"] = min(t, x)
                touched.add(token)
        else:
            touched = set()
        up, down = books[UP], books[DOWN]
        b = max(up["BUY"], default=None)
        a = min(up["SELL"], default=None)
        d = max(down["BUY"], default=None)
        valid = (
            b is not None
            and a is not None
            and b < a
            and up["updated"] is not None
            and t - up["updated"] <= 15
        )
        related = (
            d is not None
            and down["updated"] is not None
            and t - down["updated"] <= 15
            and down["BUY"][d] >= 5
        )
        if UP in touched:
            previous = {} if last is None else last
            depth_credit = {
                p: min(q, depth_credit.get(p, 0) + max(0, q - previous.get(p, 0)))
                for p, q in up["BUY"].items()
            }
            last = dict(up["BUY"])
        if (
            candidate
            and order
            and "ahead" in order
            and order["left"] > EPS
            and "cancel_effective" not in order
            and t < order["expires"]
            and related
            and DOWN in touched
            and order["down_at_entry"] is not None
            and d - order["down_at_entry"] >= 0.02 - EPS
        ):
            order["cancel_effective"] = t + 0.5
            block = (order["expires"], order["down_at_entry"] + 0.02)
            cancels.append(
                {
                    "id": order["id"],
                    "request_at": t,
                    "effective_at": t + 0.5,
                    "up_bid": b,
                    "down_bid": d,
                    "exchange_event_at": x,
                    "left": order["left"],
                }
            )
        if order and (
            order["left"] <= EPS or t >= min(order["expires"], order.get("cancel_effective", float("inf")))
        ):
            order = None
        if inventory > EPS and valid and entry_time is not None:
            sale_quantity, value, fees, _ = take(depth_credit, inventory)
            if pending_exit is None and (
                sale_quantity >= inventory - EPS and value - fees >= basis - EPS or t - entry_time >= 120
            ):
                pending_exit = t + 0.5
            if pending_exit is not None and t >= pending_exit and UP in touched:
                q, value, fees, used = take(depth_credit, inventory)
                if q > EPS:
                    allocation = basis * q / inventory
                    cash += value - fees
                    realized += value - fees - allocation
                    inventory -= q
                    basis -= allocation
                    for p, size in used:
                        depth_credit[p] -= size
                    ledger.append(
                        {
                            "type": "bid_exit",
                            "id": lot_id,
                            "qty": q,
                            "value": value,
                            "fees": fees,
                            "net": value - fees - allocation,
                            "received": t,
                        }
                    )
                    if inventory <= EPS:
                        complete += 1
                        pending_exit = entry_time = None
        if block and (t >= block[0] or related and d < block[1] - EPS):
            block = None
        if (
            order is None
            and inventory <= EPS
            and block is None
            and t < test_end
            and UP in touched
            and valid
            and related
            and 0.02 - EPS <= a - b <= 0.20 + EPS
            and cash >= 5 * b
        ):
            order = {"id": index, "price": b, "effective": t + 0.5, "expires": t + 30.5, "left": 5.0}
            orders[index] = order
        if inventory <= EPS:
            liquidation = 0.0
        elif valid:
            marked, value, fees, _ = take(up["BUY"], inventory)
            liquidation = value - fees if marked >= inventory - EPS else None
        else:
            liquidation = None
        if liquidation is not None:
            equity = cash + liquidation
            peak = max(peak, equity)
            drawdown = max(drawdown, peak - equity)
    return {
        "cash": cash,
        "realized": realized,
        "inventory": inventory,
        "open_basis": basis,
        "liquidation": liquidation,
        "net_after_liquidation": cash + liquidation - 500 if liquidation is not None else None,
        "max_observed_drawdown": drawdown,
        "round_trips": complete,
        "fills": sum(r["type"] == "maker_fill" for r in ledger),
        "rebates": 0,
        "orders": len(orders),
        "cancels": cancels,
        "ledger": ledger,
        "ambiguities": dict(veto),
    }


def quote_points(frames):
    bids = {}
    times = []
    for t, _, kind, item in frames:
        if kind == "book" and item["asset_id"] == UP:
            bids = {float(p["price"]): float(p["size"]) for p in item["bids"]}
        elif kind == "price_change":
            change = [x for x in item["price_changes"] if x["asset_id"] == UP and x["side"] == "BUY"]
            if not change:
                continue
            for delta in change:
                p, q = float(delta["price"]), float(delta["size"])
                if q:
                    bids[p] = q
                else:
                    bids.pop(p, None)
        else:
            continue
        times.append((t, max(bids, default=None)))
    return times


def main():
    frames, counts = load_tape()
    assert frames and frames[-1][0] - frames[0][0] > 250
    quotes = quote_points(frames)
    score = {}
    for label, full in [("displayed_ahead", True), ("zero_ahead", False)]:
        a, b = run(frames, False, full), run(frames, True, full)
        for c in b["cancels"]:
            hits = [r for r in a["ledger"] if r["type"] == "maker_fill" and r["id"] == c["id"]]
            c["baseline_matched_order_fills"] = hits
            c["after_effective_fill_quantity"] = sum(
                r["qty"] for r in hits if r["exchange"] >= c["effective_at"]
            )
            c["paired_saved_dollars"] = None
            for delay in (5, 30):
                target = c["request_at"] + delay
                last = next((p for t, p in reversed(quotes) if target - 15 <= t <= target), None)
                c[f"bid_move_{delay}s"] = None if last is None or c["up_bid"] is None else last - c["up_bid"]
        largest = None
        for c in b["cancels"]:
            if not c["after_effective_fill_quantity"]:
                continue
            histories = []
            for arm in (a, b):
                fills = sum(
                    r["qty"] for r in arm["ledger"] if r["id"] == c["id"] and r["type"] == "maker_fill"
                )
                exits = [r for r in arm["ledger"] if r["id"] == c["id"] and r["type"] == "bid_exit"]
                histories.append(
                    sum(r["net"] for r in exits) if abs(fills - sum(r["qty"] for r in exits)) <= EPS else None
                )
            if None not in histories:
                savings = histories[1] - histories[0]
                c["paired_saved_dollars"] = savings
                if savings > 0:
                    largest = max(largest or 0, savings)
        score[label] = {
            "largest_observable_paired_gain": largest,
            "baseline": a,
            "candidate": b,
            "cash": {"fills": 0, "realized": 0, "max_observed_drawdown": 0, "net_after_liquidation": 0},
            "candidate_minus_baseline": (
                b["net_after_liquidation"] - a["net_after_liquidation"]
                if a["net_after_liquidation"] is not None and b["net_after_liquidation"] is not None
                else None
            ),
            "without_only_market": {"baseline": 0, "candidate": 0, "cash": 0},
        }
    (ROOT / "scorecard.json").write_text(
        json.dumps({"event_counts": counts, "scenarios": score}, indent=2) + "\n"
    )


if __name__ == "__main__":
    main()
