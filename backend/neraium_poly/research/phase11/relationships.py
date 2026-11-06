"""Persistent paired-market structural research; never infers enforceable payoffs."""

from bisect import bisect_left
from collections import Counter, defaultdict, deque
from datetime import datetime, timedelta
from statistics import mean, pstdev

from neraium_poly.data import assess_book
from neraium_poly.research.phase11.contracts import ExperimentSpec
from neraium_poly.research.phase11.models import _observations


def run_relationships(observations, dataset_manifest):
    rows = _observations(observations)
    known, latest, states = {}, {}, {}
    counts = Counter()
    findings, pair_ids = [], set()
    by_token = defaultdict(list)
    for row in rows:
        if assess_book(row.book, row.book.available_at, max_spread=0.05).healthy:
            by_token[row.book.token_id].append(row.book)
    for row in rows:
        book, market = row.book, row.market
        now = book.available_at
        if market is None:
            counts["missing_point_in_time_metadata"] += 1
            continue
        if (
            market.outcome.casefold() != "yes"
            or market.status != "active"
            or (market.end_time is not None and market.end_time <= now)
        ):
            known.pop(book.token_id, None)
            latest.pop(book.token_id, None)
            counts["unsupported_outcome_or_lifecycle"] += 1
            continue
        if not market.resolution_rules or not market.resolution_source:
            counts["missing_resolution_semantics"] += 1
            continue
        known[book.token_id] = market
        latest[book.token_id] = book
        candidates = sorted(
            t for t, m in known.items() if m.event_id == market.event_id and m.market_id != market.market_id
        )
        for other_token in candidates:
            pair = tuple(sorted((book.token_id, other_token)))
            if pair not in states and len(states) >= 200:
                counts["bounded_pair_capacity"] += 1
                continue
            left, right = latest[pair[0]], latest[pair[1]]
            if any(
                known[token].status != "active"
                or (known[token].end_time is not None and known[token].end_time <= now)
                for token in pair
            ):
                counts["known_peer_inactive_or_ended"] += 1
                continue
            if not all(assess_book(b, now, max_spread=0.05).healthy for b in (left, right)):
                counts["stale_or_incomplete_pair"] += 1
                continue
            if abs((left.timestamp - right.timestamp).total_seconds()) > 5:
                counts["source_timestamp_skew"] += 1
                continue
            identity = (left.id, right.id)
            state = states.setdefault(
                pair,
                {
                    "baseline": deque(maxlen=20),
                    "last_at": None,
                    "last_pair": None,
                    "last_sources": None,
                    "persistence": 0,
                    "direction": 0,
                },
            )
            if identity == state["last_pair"]:
                counts["reused_pair"] += 1
                continue
            if state["last_pair"] and (left.id == state["last_pair"][0] or right.id == state["last_pair"][1]):
                counts["both_legs_must_refresh"] += 1
                continue
            if state["last_sources"] and (
                left.timestamp <= state["last_sources"][0] or right.timestamp <= state["last_sources"][1]
            ):
                counts["out_of_order_or_reused_source_pair"] += 1
                continue
            if state["last_at"] and (now - state["last_at"]).total_seconds() > 120:
                state["persistence"], state["direction"] = 0, 0
                counts["persistence_gap_reset"] += 1
            state["last_at"], state["last_pair"] = now, identity
            state["last_sources"] = (left.timestamp, right.timestamp)
            residual = (
                left.bids[0].price + left.asks[0].price - right.bids[0].price - right.asks[0].price
            ) / 2
            counts["paired_observations"] += 1
            pair_ids.add(pair)
            if len(state["baseline"]) < 20:
                state["baseline"].append(residual)
                counts["baseline_learning"] += 1
                continue
            center = mean(state["baseline"])
            scale = max(0.005, pstdev(state["baseline"]))
            departure = residual - center
            direction = 1 if departure > 0 else -1
            changed = abs(departure) >= 0.03 and abs(departure) / scale >= 3
            if changed:
                state["persistence"] = state["persistence"] + 1 if state["direction"] == direction else 1
                state["direction"] = direction
                counts["structural_departure"] += 1
            else:
                state["persistence"], state["direction"] = 0, 0
                state["baseline"].append(residual)
                counts["ordinary_variation"] += 1
            if changed and state["persistence"] == 3:
                counts["persistent_findings"] += 1
                # Even a persistent contextual finding is NOT a probability or price target.
                if len(findings) < 100:
                    findings.append(
                        {
                            "event_id": market.event_id,
                            "pair": pair,
                            "decision_at": now.isoformat(),
                            "left_book_id": left.id,
                            "right_book_id": right.id,
                            "residual": residual,
                            "baseline_mean": center,
                            "baseline_scale": scale,
                            "standardized_departure": abs(departure) / scale,
                            "persistence": state["persistence"],
                            "confidence": "descriptive_unvalidated",
                            "logical_constraint": False,
                            "net_edge": None,
                            "source": "authentic_paired_book_midpoints",
                        }
                    )
    # Follow-up marks are diagnostic outcomes, never used to create earlier findings.
    matured = []
    for finding in findings:
        at = datetime.fromisoformat(finding["decision_at"])
        values = by_token[finding["pair"][0]]
        times = [b.available_at for b in values]
        target = at + timedelta(seconds=60)
        j = bisect_left(times, target)
        while (
            j < len(values)
            and values[j].available_at <= target + timedelta(seconds=30)
            and values[j].timestamp < target
        ):
            j += 1
        initial = next((b for b in values if b.id == finding["left_book_id"]), None)
        if initial and j < len(values) and values[j].available_at <= target + timedelta(seconds=30):
            matured.append(values[j].bids[0].price - initial.bids[0].price)
    spec = ExperimentSpec(
        experiment_id="phase11-persistent-relationship-v1",
        hypothesis="Persistent changes in contextual same-event YES relationships identify a distinct repricing regime",
        dataset_sha256=dataset_manifest["dataset_sha256"],
        model_version="paired-residual-persistence-v1",
        feature_definitions={
            "residual": "Current aligned actual midpoint difference; distinct market same-event YES pairs",
            "baseline": "20 earlier usable paired residuals",
            "persistence": "3 separately refreshed paired departures;120s maxgap",
        },
        target_definitions={"followup": "Actual60s future bid change; unavailable outcome stays absent"},
        split_policy="Forward-only descriptive baseline/update; no learned profitable strategy or certification",
        grouping={"observed_pairs": len(pair_ids), "reviewed_independent_events": 0},
        transaction_cost_assumptions={
            "net_edge": None,
            "reason": "Relationship departure is not an exit-price model",
        },
        failure_conditions=(
            "Missing aligned refreshed legs",
            "Insufficient baseline",
            "No independent causal context or payoff review",
        ),
        limitations=(
            "Same-event statistical membership is not logically exhaustive",
            "No independently calibrated probability target",
            "No false-positive conclusion without independently labelled structural changes",
            "Multiple tested pairs; significance is descriptive only",
        ),
    )
    return {
        "spec": spec.model_dump(mode="json"),
        "status": "descriptive_evaluated",
        "counts": dict(counts),
        "findings": findings,
        "findings_sample_limit": 100,
        "matured_sample_followups": len(matured),
        "sample_mean_followup_bid_change": mean(matured) if matured else None,
        "simple_unchanged_bid_baseline_change": 0.0 if matured else None,
        "logical_constraints_verified": 0,
        "executable_arbitrage": None,
        "false_positive_rate": None,
        "net_edge": None,
        "confidence_interval": None,
        "confidence_interval_reason": "No independently labelled structural regimes or event-independence review",
        "promotion_allowed": False,
        "credible_cost_adjusted_advantage": False,
    }
