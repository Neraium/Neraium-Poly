"""Aggregate nonoverlapping tape windows. The 5s counterfactual is excluded."""
import json
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASKETS = HERE.parent / "phase56-baskets"
archive = json.loads((HERE/"archive-coverage.json").read_text())
captures = json.loads((HERE/"scorecard.json").read_text())
frozen = json.loads((BASKETS/"freeze.json").read_text())
rows = defaultdict(list)
contracts = dict(frozen["markets"], **archive["contracts"])
for label, stats in (
    ("archive",archive["markets"]),("rest",captures["rest"]["markets"]),("websocket",captures["websocket"]["markets"]),
):
    for market, row in stats.items():
        rows[market].append(dict(row,partition=label))


def aggregate(stats):
    amounts = [r["modeled_usd_before_unknown_conversion"] for r in stats]
    best = [r["best_execution_usd_before_unknown_conversion"] for r in stats
            if r["best_execution_usd_before_unknown_conversion"] is not None]
    hours = sum(r["hours"] for r in stats)
    return dict(priceable_market_hours=hours, coverage="thin" if hours else "unpriceable",
                gross_episodes=sum(r["gross_episodes"] for r in stats),
                distinct_after_fee=sum(r["after_fee_episodes"] for r in stats),
                modeled_usd_before_unknown_conversion=None if None in amounts else sum(amounts),
                best_episode_usd_before_unknown_conversion=max(best,default=None))


groups = defaultdict(list)
ranked = []
for market, stats in rows.items():
    term = (contracts[market].get("rows") or contracts[market]["terms"])[0]
    groups[term["event_id"]].extend(stats)
    ranked.append(dict(market=market, event=term["event_id"], question=term["question"], **aggregate(stats)))
rank = lambda row: (-row["distinct_after_fee"], -row["priceable_market_hours"])
ranked.sort(key=rank)
families = sorted((dict(event=event, **aggregate(stats)) for event,stats in groups.items()),key=rank)
all_stats = [row for stats in rows.values() for row in stats]
result = dict(markets_scanned=len(rows),priceable_markets=sum(r["priceable_market_hours"]>0 for r in ranked),
    event_families=len(groups), priceable_event_families=sum(r["priceable_market_hours"]>0 for r in families),
    **aggregate(all_stats), markets=ranked, event_ranking=families,
    admitted_forward_candidate=None, forward_reason="No positive gross episode in the scoped historical replay.")
(HERE/"ranking.json").write_text(json.dumps(result,indent=2)+"\n")
