"""Paper-only replay of the two retained Phase 56 captures."""
import gzip
import hashlib
import json
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
REST = HERE.parent / "phase56-baskets"
WS = HERE.parent / "phase56"
sys.path.insert(0, str(REST))
import scan as scanner

F = scanner.F
SIDES = ("bids", "asks")
CADENCE = 5


def read(path):
    with gzip.open(path, "rt") as stream:
        for line in stream:
            yield json.loads(line)


def stamp(ts):
    return datetime.fromtimestamp(ts, UTC).isoformat()


def ws_frames(meta):
    identity = json.loads((WS / "market-identity.json").read_text())
    fees = json.loads((WS / "fee-source.json").read_text())
    tokens = {r["token_id"] for r in meta["rows"]}
    assert tokens == {identity["primary_token_id"], identity["secondary_token_id"]}
    assert fees["c"] == identity["condition_id"] == meta["native"]["c"]
    assert fees["fd"] == meta["native"]["fd"] and fees["mos"] == meta["native"]["mos"]
    books = {}
    coverage = Counter()
    frames = []
    for row in read(WS / "holdout.jsonl.gz"):
        if row["raw"] in ("PING", "PONG"):
            continue
        now = scanner.at(row["received_at"])
        packet = json.loads(row["raw"])
        changed = False
        for event in packet if isinstance(packet, list) else [packet]:
            kind = event["event_type"]
            coverage[kind] += 1
            assert event["market"] == identity["condition_id"]
            exchange = int(event["timestamp"]) / 1000
            if kind == "book":
                edits = [event]
            elif kind == "price_change":
                edits = event["price_changes"]
            else:
                continue
            for edit in edits:
                token = edit["asset_id"]
                assert token in tokens
                prior = books.get(token)
                changed = True
                if exchange > now or (prior and exchange < prior["exchange"]):
                    coverage["noncausal_timestamp"] += 1
                    books.pop(token, None)
                    continue
                if kind == "book":
                    depth = {s: {float(x["price"]): float(x["size"]) for x in edit[s]} for s in SIDES}
                elif prior:
                    depth = {s: prior[s].copy() for s in SIDES}
                    side = {"BUY": "bids", "SELL": "asks"}[edit["side"]]
                    price, size = float(edit["price"]), float(edit["size"])
                    if size > 0:
                        depth[side][price] = size
                    else:
                        depth[side].pop(price, None)
                    if ((max(depth["bids"], default=0) != float(edit["best_bid"]))
                        or (min(depth["asks"], default=1) != float(edit["best_ask"]))):
                        coverage["top_mismatch_invalidated"] += 1
                        books.pop(token, None)
                        continue
                else:
                    coverage["delta_without_seed"] += 1
                    continue
                if depth["asks"] and depth["bids"] and min(depth["asks"]) <= max(depth["bids"]):
                    coverage["crossed_invalidated"] += 1
                    books.pop(token, None)
                    continue
                books[token] = dict(depth, receipt=now, exchange=exchange, id=edit["hash"])
        if changed:
            frames.append((now, books.copy()))
    return frames, coverage


def polls(frames, anchor):
    i = -1
    tick = anchor
    while tick <= frames[-1][0]:
        while i + 1 < len(frames) and frames[i+1][0] <= tick:
            i += 1
        if i >= 0:
            yield tick, frames[i][1]
        tick += CADENCE


class ExecutedLegs:
    """Hand the frozen unwind accounting the fills made at actual replay ticks."""

    def __init__(self, depth, fills):
        self.depth = depth
        self.fills = iter(fills)
        self.remaining_legs = 2

    def observe(self, key, levels):
        if not self.remaining_legs:
            self.depth.observe(key, levels)

    def execute(self, key, qty, rate, *, buy, limit):
        if self.remaining_legs:
            self.remaining_legs -= 1
            return next(self.fills)
        return self.depth.execute(key, qty, rate, buy=buy, limit=limit)


def settle(depth, pending, unwind, *, censored=False):
    fills = pending["arrival_fills"]
    if censored:
        fills.extend(dict(quantity=0, principal=0, fees=0) for _ in range(2-len(fills)))
    # Empty placeholder depth calls the accounting hook for both saved fills.
    outcome = scanner.attempt(
        ExecutedLegs(depth, fills), pending["tokens"], pending["rates"], pending["size"],
        [{}, {}, *unwind], pending["side"] == "asks", 0,
    )
    return dict(pending, **outcome, endpoint_censored=censored)


def replay(frames, markets, *, max_gap):
    counts = {m: Counter() for m in markets}
    active = {}
    episodes = []
    attempts = []
    depth = scanner.Depth()
    last = {}
    pending = None
    cash = F["cash"]
    unresolved = False

    def observe(books, when):
        for token, book in books.items():
            key = (token, book["receipt"], book["id"])
            if last.get(token) != key and scanner.admitted([book], when):
                for side in SIDES:
                    depth.observe((token, side == "asks"), book[side])
                last[token] = key

    def coverage_interval(current, end):
        when, books = current
        if not 0 < end - when <= max_gap:
            return
        for market, meta in markets.items():
            tokens = [r["token_id"] for r in meta["rows"]]
            pair = [books.get(t) for t in tokens]
            if scanner.admitted(pair, when) and any(
                all(sum(b[s].values()) >= meta["native"]["mos"] for b in pair) for s in (SIDES if meta.get("split_supported",True) else ("asks",))
            ):
                expiry = min(min(b["receipt"], b["exchange"]) + F["book_age_seconds"] for b in pair)
                counts[market]["priceable_seconds"] += max(0, min(end, expiry) - when)

    previous = None
    for now, books in frames:
        if previous:
            coverage_interval(previous, now)
            if now - previous[0] > max_gap:
                active.clear()
        previous = now, books
        observe(books, now)
        if pending and now >= pending["next"]:
            tokens = pending["tokens"]
            arms = [books.get(t) for t in tokens]
            fills = pending["arrival_fills"]
            i = len(fills)
            if i < 2:
                b = arms[i]
                buy = pending["side"] == "asks"
                limit = pending["size"]["legs"][i]["limit"]
                filled = dict(quantity=0, principal=0, fees=0)
                if scanner.admitted([b], now):
                    filled = depth.execute((tokens[i], buy), pending["size"]["quantity"],
                                           pending["rates"][i], buy=buy, limit=limit)
                fills.append(filled)
                pending["arrival_times"].append(now)
                pending["next"] = now + F["latency_seconds"]
            else:
                pending["arrival_times"].append(now)
                outcome = settle(depth, pending, [
                    b["bids"] if scanner.admitted([b], now) else None for b in arms
                ])
                attempts.append(outcome)
                unresolved |= outcome["net"] is None
                cash += outcome["cash_delta"]
                pending = None
        for market, meta in markets.items():
            tokens = [r["token_id"] for r in meta["rows"]]
            pair = [books.get(t) for t in tokens]
            native = meta["native"]
            rates = [native["fd"]["r"]] * 2
            minimum = native["mos"]
            valid = scanner.admitted(pair, now)
            counts[market]["samples"] += 1
            for side in (SIDES if meta.get("split_supported", True) else ("asks",)):
                key = market, side
                buy = side == "asks"
                levels = [b[side] for b in pair] if valid else []
                if not levels or any(sum(b.values()) < minimum for b in levels):
                    active.pop(key, None)
                    counts[market]["invalid_or_insufficient_" + side] += 1
                    continue
                counts[market]["priced_" + side] += 1
                top = sum((min(b) if buy else max(b)) for b in levels)
                if (buy and top >= 1 - scanner.EPS) or (not buy and top <= 1 + scanner.EPS):
                    active.pop(key, None)
                    continue
                signature = tuple(tuple(sorted(b.items())) for b in levels)
                params = dict(buy=buy, floor=1, cash=F["cash"], conversion=0)
                gross = scanner.size_search(levels, [0, 0], minimum, **params)
                if not gross or gross["gross_edge"] <= scanner.EPS:
                    active.pop(key, None)
                    continue
                if key not in active:
                    e = dict(market=market, side=side, start=now, last=now, quotes=[], max_conversion_usd=0)
                    active[key] = e, set()
                    episodes.append(e)
                e, seen = active[key]
                e["last"] = now
                if signature in seen:
                    continue
                seen.add(signature)
                net = scanner.size_search(levels, rates, minimum, **params)
                conversion = max(0, net["net"]) if net else 0
                e["quotes"].append(dict(at=now, gross=gross, net_after_fees=net,
                    provenance=[{k:b[k] for k in ("receipt","exchange","id")} for b in pair]))
                e["max_conversion_usd"] = max(e["max_conversion_usd"], conversion)
                if conversion > scanner.EPS and pending is None and not unresolved and not e.get("attempted"):
                    size = scanner.size_search(levels, rates, minimum, **(params | {"cash":cash}))
                    if size and size["net"] > scanner.EPS:
                        e["attempted"] = True
                        pending = dict(market=market, side=side, decision=now, next=now+F["latency_seconds"],
                            episode_start=e["start"], tokens=tokens, rates=rates, size=size, arrival_fills=[], arrival_times=[])
    if pending:
        attempts.append(settle(depth, pending, [None, None], censored=True))
    for e in episodes:
        e["observed_duration_s"] = e["last"] - e["start"]
    rows = {}
    for market in markets:
        relevant = [a for a in attempts if a["market"] == market]
        net = [a["net"] for a in relevant]
        rows[market] = dict(counts[market], hours=counts[market]["priceable_seconds"]/3600,
            gross_episodes=sum(e["market"]==market for e in episodes),
            after_fee_episodes=sum(e["market"]==market and e["max_conversion_usd"]>scanner.EPS for e in episodes),
            partial_baskets=sum(not a["complete"] and any(l["quantity"]>scanner.EPS for l in a["legs"]) for a in relevant),
            modeled_usd_before_unknown_conversion=None if None in net else sum(net),
            best_execution_usd_before_unknown_conversion=max((n for n in net if n is not None), default=None))
    return rows, episodes, attempts


def main():
    markets = F["markets"]
    refs = {r["token_id"]: meta for meta in markets.values() for r in meta["rows"]}
    rest = [(max(scanner.at(r["received"]) for r in sample),
             {r["token"]:b for r in sample if (b:=scanner.parse(r,refs[r["token"]]))})
            for sample in read(REST/"holdout.jsonl.gz")]
    ws, ws_counts = ws_frames(markets["7085279"])
    anchor = ws[0][0]
    sampled = list(polls(ws, anchor))
    results = {}
    ledger = {}
    for name, frames, eligible, gap in (
        ("rest", rest, markets, 2), ("websocket", ws, {"7085279":markets["7085279"]}, 15),
        ("websocket_5s", sampled, {"7085279":markets["7085279"]}, 7.5),
    ):
        stats,e,a = replay(frames,eligible,max_gap=gap)
        results[name] = dict(start=stamp(frames[0][0]), end=stamp(frames[-1][0]),
            wall_hours=(frames[-1][0]-frames[0][0])/3600, decisions=len(frames), markets=stats)
        ledger[name] = dict(episodes=e, attempts=a)
    results["between_polls"] = [
        dict(market=e["market"], side=e["side"], start=stamp(e["start"]), duration_s=e["observed_duration_s"],
             max_conversion_usd=e["max_conversion_usd"], episode_index=i)
        for i,e in enumerate(ledger["websocket"]["episodes"])
        if not any(q["market"]==e["market"] and q["side"]==e["side"]
                   and e["start"]<=q["start"]<=e["last"]
                   for q in ledger["websocket_5s"]["episodes"])
    ]
    results["websocket_integrity"] = ws_counts
    results["tape_sha256"] = {p.parent.name:hashlib.sha256(p.read_bytes()).hexdigest()
                              for p in (WS/"holdout.jsonl.gz",REST/"holdout.jsonl.gz")}
    results["cross_market"] = [dict(id=r["id"], terms=[markets[m]["rows"][0]["resolution_rules"]
        for m in r["id"].split("=>")], payoff=r["payoffs"], admitted_floor=0,
        rejection="No shared adjudication guarantee for exceptional resolutions.")
        for r in F["relationships"] if r["kind"]=="strict_implication"]
    for name,data in (("scorecard",results),("ledger",ledger)):
        (HERE/f"{name}.json").write_text(json.dumps(data,indent=2,allow_nan=False)+"\n")


if __name__ == "__main__":
    main()
