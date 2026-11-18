import datetime
import gzip
import itertools
import json
from pathlib import Path

import httpx

here = Path(__file__).resolve().parent
tape = Path("/home/ubuntu/phase55-forward.9kSESh/forward-tape.jsonl.gz")
with gzip.open(tape, "rt") as f:
    frame = next(r["frame"] for l in f if "frame" in (r := json.loads(l)))
ids = ["7085279", "6967637", "6967639", "6967641", "6967642"]
markets = {}
root = "https://clob.polymarket.com"
with httpx.Client(timeout=8, trust_env=False) as client:
    for mid in ids:
        rows = [m for m in frame["markets"] if m["market_id"] == mid]
        assert len(rows) == 2 and rows[0]["resolution_rules"] == rows[1]["resolution_rules"]
        tokens = [m["token_id"] for m in rows]
        p = client.get(f"{root}/markets-by-token/{tokens[0]}")
        p.raise_for_status()
        b = p.json()
        f = client.get(f"{root}/clob-markets/{b['condition_id']}")
        f.raise_for_status()
        native = f.json()
        assert (
            set(tokens) == {t["t"] for t in native["t"]} == {b["primary_token_id"], b["secondary_token_id"]}
        )
        assert (
            native["c"] == b["condition_id"]
            and native["fd"]["e"] == 1
            and native["fd"]["to"]
            and 0 <= native["fd"]["r"] <= 1
        )
        markets[mid] = {
            "rows": rows,
            "token_source": b,
            "native": native,
            "fee_available_at": datetime.datetime.now(datetime.UTC).isoformat(),
            "fee_urls": [str(p.url), str(f.url)],
        }
threshold = ids[1:]
assert len({markets[k]["rows"][0]["resolution_rules"] for k in threshold}) == 1
relationships = []
for k, v in markets.items():
    tokens = [m["token_id"] for m in v["rows"]]
    relationships.append(
        {"id": k, "legs": tokens, "kind": "complete_set", "payoffs": [[1, 0], [0, 1], [0.5, 0.5]], "floor": 1}
    )
for low, high in itertools.combinations(threshold, 2):
    lookup = lambda m, outcome: next(r["token_id"] for r in markets[m]["rows"] if r["outcome"] == outcome)
    relationships.append(
        {
            "id": f"{low}=>{high}",
            "legs": [lookup(low, "Yes"), lookup(high, "No")],
            "kind": "strict_implication",
            "payoffs": {
                "price_regions_low_mid_high": [[0, 1], [1, 1], [1, 0]],
                "both_invalid_half": [0.5, 0.5],
                "differential_exception": [0, 0],
            },
            "floor": 0,
            "blocked": "Actual close rules prove implication on the shared observed candle. No binding cross-condition exceptional adjudication guarantee recovered.",
        }
    )
(here / "freeze.json").write_text(
    json.dumps(
        {
            "markets": markets,
            "relationships": relationships,
            "cash": 500,
            "conversion_cost_sensitivity": 0.10,
            "conversion_cost_verified": False,
            "latency_seconds": 0.5,
            "book_age_seconds": 15,
            "receipt_skew_seconds": 2,
            "duration_seconds": 90,
            "size_step": 0.01,
            "fee": "round up per level to 0.00001",
            "rebates": 0,
        },
        indent=2,
    )
    + "\n"
)
