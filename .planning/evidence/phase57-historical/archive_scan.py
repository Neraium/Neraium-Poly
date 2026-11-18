"""Bounded pre-holdout archive partition. Opens committed sources read-only."""
import json
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from pathlib import Path

from neraium_poly.contracts import OrderBookSnapshot
from neraium_poly.research.archive import BookDelta, BookReceipt, apply_observation
from neraium_poly.research.phase17.provenance import ReadonlyArchive
from neraium_poly.research.phase29.costs import replay_fee

from replay import HERE, replay, scanner, stamp

START = "2026-11-18T03:07"
END = "2026-11-18T04:07"
DATA = Path("/home/ubuntu/Neraium-Poly/data")


def partition():
    archive = ReadonlyArchive(DATA / "experimental-paper")
    kinds = ("OrderBookSnapshot", "BookDelta", "BookReceipt", "MarketSnapshot", "FeeObservation")
    queries = {k: archive._catalog_rows(
        "SELECT * FROM records WHERE kind=? AND available_at>=? AND available_at<? "
        "ORDER BY available_at,id LIMIT 6001", (k, START, END),
    ) for k in kinds}
    if any(len(r) > 6000 for r in queries.values()):
        raise ValueError("archive partition exceeds row budget")
    rows = sorted((r for rr in queries.values() for r in rr), key=lambda r:(r["available_at"],r["id"]))
    books, terms, fee_cache = {}, {}, {}
    outcomes = defaultdict(set)
    fees = {}
    frames, priced, rejects = [], {}, Counter()
    source_ids = []

    @lru_cache(maxsize=128)
    def original(identifier):
        kind, payload, _ = archive.get(identifier)
        if kind != "OrderBookSnapshot":
            raise ValueError("quote base is not a full book")
        return OrderBookSnapshot.model_validate_json(payload)

    @lru_cache(maxsize=256)
    def proof(evidence, token):
        return replay_fee({"evidence_id":evidence}, archive, token_id=token,
                          as_of=fees[token]["available_at"])

    for row in rows:
        kind, raw, _ = archive._fetch(row)
        record = json.loads(raw)
        token = record["token_id"]
        if kind == "MarketSnapshot":
            if record["source"] == "https://gamma-api.polymarket.com":
                terms[token] = record
                outcomes[record["market_id"]].add(token)
            continue
        if kind == "FeeObservation":
            fees[token] = record
            continue
        if kind == "OrderBookSnapshot":
            book = OrderBookSnapshot.model_validate(record)
        else:
            delta = (BookDelta if kind == "BookDelta" else BookReceipt).model_validate(record)
            base = original(delta.full_book_id)
            if base.available_at > delta.available_at:
                raise ValueError("future quote base")
            book = apply_observation(base, delta)
        source_ids.append((row["id"],row["digest"]))
        now = book.available_at.timestamp()
        levels = {s:{p.price:p.size for p in getattr(book,s)} for s in ("asks","bids")}
        if (not book.complete or (levels["asks"] and levels["bids"] and
                                  min(levels["asks"]) <= max(levels["bids"]))):
            books.pop(token,None)
            rejects["invalid_book"] += 1
        else:
            books[token] = dict(levels, receipt=now, exchange=book.timestamp.timestamp(), id=book.id)
        market = book.market_id
        tokens = sorted(outcomes[market])
        if market in priced and priced[market]["split_supported"] is False and len(tokens)!=2:
            raise ValueError("previously admitted binary market metadata changed")
        if len(tokens)!=2 or not all(t in books for t in tokens):
            rejects["missing_both_legs"]+=1
        elif not scanner.admitted([books[t] for t in tokens],now):
            rejects["stale_or_skewed_pair"]+=1
        else:
            descriptors=[terms[t] for t in tokens]
            if (any(not r.get("resolution_rules") or r.get("status")!="active" for r in descriptors)
                or len({(r["resolution_rules"],r.get("resolution_source"),r["end_time"])
                        for r in descriptors})!=1
                or datetime.fromisoformat(descriptors[0]["end_time"]).timestamp()<=now):
                rejects["terms_or_lifecycle"]+=1
            elif any(t not in fees or now-scanner.at(fees[t]["available_at"])>300 for t in tokens):
                rejects["missing_decision_time_fee"]+=1
            else:
                proofs=[proof(fees[t]["id"],t) for t in tokens]
                if (any(p["status"]!="verified_current_protocol_curve" for p in proofs)
                    or len({(p["condition_id"],p["rate"]) for p in proofs})!=1):
                    rejects["fee_or_condition_binding"]+=1
                else:
                    p=proofs[0]
                    raw_fee=json.loads(archive.get(p["raw_response_ids"][1])[1])["payload"]
                    if {t["t"] for t in raw_fee["t"]} != set(tokens):
                        rejects["not_exact_native_binary"]+=1
                    else:
                        minimum=max(float(raw_fee["mos"]),*(r["min_order_size"] for r in descriptors))
                        meta=dict(rows=descriptors,native=dict(fd=raw_fee["fd"],mos=minimum,c=p["condition_id"]),
                                  split_supported=False)
                        if market in priced and (priced[market]["native"]!=meta["native"]
                                                or [r["token_id"] for r in priced[market]["rows"]]!=tokens):
                            raise ValueError("fee, condition or minimum changed within replay partition")
                        priced[market]=meta
                        fee_cache.setdefault(market,{})[tuple(p["fee_observation_id"] for p in proofs)]=proofs
        # Use only currently admitted fee-bound markets on each observation, even
        # when another market caused the frame. Never seed from the future.
        visible={}
        for mid,meta in priced.items():
            tt=[r["token_id"] for r in meta["rows"]]
            if (mid==market and len(tokens)!=2) or any(t not in fees or t not in books or now-scanner.at(
                fees[t]["available_at"])>300 for t in tt):
                continue
            current=tuple(fees[t]["id"] for t in tt)
            if current not in fee_cache[mid]:
                continue
            visible.update((t,books[t]) for t in tt)
        frames.append((now,visible))
    score, episodes, attempts = replay(frames, priced, max_gap=5)
    return dict(window_utc=[START,END], distinct_quote_market_count=len({m for m in outcomes}),
                rows={k:len(v) for k,v in queries.items()}, exclusions=dict(rejects),
                first_book_receipt=stamp(frames[0][0]), last_book_receipt=stamp(frames[-1][0]),
                source_ids=source_ids, markets=score, contracts={m:dict(
                    terms=v["rows"],native=v["native"],split_supported=False,
                    fee_proofs=list(fee_cache[m].values())) for m,v in priced.items()}), episodes, attempts


if __name__ == "__main__":
    result, episodes, attempts = partition()
    (HERE/"archive-coverage.json").write_text(json.dumps(result,indent=2,allow_nan=False)+"\n")
    (HERE/"archive-ledger.json").write_text(json.dumps(dict(episodes=episodes,attempts=attempts),indent=2)+"\n")
    print(json.dumps({k:v for k,v in result.items() if k not in ("source_ids","contracts")},indent=2))
