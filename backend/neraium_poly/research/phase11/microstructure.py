"""Causal quote features and bounded hypothetical executable-cost research.

No broker/account calls. A retrospective quote scenario is not a filled trade or
operational P/L. Passive queue position and adverse selection remain unobserved.
"""

from __future__ import annotations

import json
from bisect import bisect_left
from collections import Counter, defaultdict, deque
from datetime import timedelta
from itertools import pairwise
from pathlib import Path
from statistics import mean, median, pstdev

from neraium_poly.data import assess_book
from neraium_poly.experimental.account import verified_fee_rate
from neraium_poly.research.phase11.contracts import ExperimentSpec, ResearchObservation
from neraium_poly.research.phase11.dataset import load_dataset


def causal_features(observations):
    """Feature windows contain only prior observations available at decision time."""
    history, last, persistence, rejects, rows = {}, {}, {}, Counter(), []
    for raw in observations:
        obs = raw if isinstance(raw, ResearchObservation) else ResearchObservation.model_validate(raw)
        b = obs.book
        health = assess_book(b, b.available_at, expected_token=b.token_id, max_spread=0.05)
        if not health.healthy:
            rejects.update(health.reasons)
            continue
        previous = last.get(b.token_id)
        if previous is not None and (
            b.timestamp < previous.timestamp or b.available_at < previous.available_at
        ):
            rejects["out_of_order_observation"] += 1
            continue
        if previous is not None and (b.available_at - previous.available_at).total_seconds() > 120:
            history.pop(b.token_id, None)
            persistence.pop(b.token_id, None)
        window = history.setdefault(b.token_id, deque(maxlen=20))
        bid, ask = b.bids[0].price, b.asks[0].price
        top = (bid, ask)
        if (
            previous is None
            or b.token_id not in persistence
            or top != (previous.bids[0].price, previous.asks[0].price)
        ):
            persistence[b.token_id] = b.available_at
        old_bids = [r[1] for r in window]
        changes = [right - left for left, right in pairwise(old_bids)]
        bid_shares = sum(p.size for p in b.bids[:5])
        ask_shares = sum(p.size for p in b.asks[:5])
        row = {
            "book_id": b.id,
            "market_id": b.market_id,
            "token_id": b.token_id,
            "event_id": obs.market.event_id if obs.market else None,
            "timestamp": b.timestamp.isoformat(),
            "available_at": b.available_at.isoformat(),
            "bid": bid,
            "ask": ask,
            "midpoint": (bid + ask) / 2,
            "spread": ask - bid,
            "top5_bid_shares": bid_shares,
            "top5_ask_shares": ask_shares,
            "imbalance": (bid_shares - ask_shares) / (bid_shares + ask_shares),
            "best_bid_concentration": b.bids[0].size / bid_shares,
            "best_ask_concentration": b.asks[0].size / ask_shares,
            "prior_observations": len(window),
            "prior_bid_change_mean": mean(changes) if changes else None,
            "prior_bid_change_volatility": pstdev(changes) if len(changes) > 1 else None,
            "quote_persistence_seconds": (b.available_at - persistence[b.token_id]).total_seconds(),
            "source_age_seconds": (b.available_at - b.timestamp).total_seconds(),
            "history_available_through": window[-1][0].isoformat() if window else None,
        }
        rows.append(row)
        window.append((b.available_at, bid))
        last[b.token_id] = b
    return rows, dict(rejects)


def depth_quote(levels, quantity, *, participation=0.1, limit=None, buy=True):
    """Walk displayed depth with per-level participation; no queue/fill claim."""
    if quantity <= 0 or not 0 < participation <= 1:
        raise ValueError("positive quantity and bounded participation required")
    remaining, value, curve_factor = quantity, 0.0, 0.0
    for p in levels:
        if limit is not None and ((buy and p.price > limit) or (not buy and p.price < limit)):
            break
        size = min(remaining, p.size * participation)
        value += size * p.price
        curve_factor += size * p.price * (1 - p.price)
        remaining -= size
        if remaining <= 1e-9:
            break
    filled = quantity - remaining
    return {
        "quantity_available": filled,
        "requested_quantity": quantity,
        "complete": remaining <= 1e-9,
        "average_price": value / filled if filled > 0 else None,
        "notional": value,
        "exponent1_fee_factor": curve_factor,
        "unavailable_quantity": remaining,
    }


def _next_qualifying(rows, times, ready, latest, *, after=None):
    for obs in rows[bisect_left(times, ready) :]:
        b = obs.book
        if b.available_at > latest:
            break
        if (
            b.timestamp >= ready
            and (after is None or b.id != after)
            and assess_book(b, b.available_at, max_spread=0.05).healthy
        ):
            return obs
    return None


def execution_scenarios(observations, features, *, horizon=60, max_trials=6000):
    """Nonoverlapping token trials with actual post-latency entry/exit quotes.

    Fee bounds and sensitivity scenarios are separate from no-fee price movement.
    No account bankroll or portfolio is simulated; no result is realized P/L.
    """
    if horizon < 1 or not 1 <= max_trials <= 10000:
        raise ValueError("bounded horizon and trial count required")
    grouped, by_id = defaultdict(list), {}
    for obs in observations:
        grouped[obs.book.token_id].append(obs)
        by_id[obs.book.id] = obs
    for rows in grouped.values():
        rows.sort(key=lambda r: (r.book.available_at, r.book.timestamp, r.book.id))
    timelines = {t: [r.book.available_at for r in rows] for t, rows in grouped.items()}
    output, reasons, due = [], Counter(), {}
    for feature in features:
        decision = by_id[feature["book_id"]]
        at, token = decision.book.available_at, decision.book.token_id
        if at < due.get(token, at):
            continue
        due[token] = at + timedelta(seconds=horizon + 30)
        if len(output) >= max_trials:
            reasons["trial_budget_exhausted"] += 1
            break
        rows, times = grouped[token], timelines[token]
        entry = _next_qualifying(
            rows, times, at + timedelta(milliseconds=100), at + timedelta(seconds=15), after=decision.book.id
        )
        exit_obs = _next_qualifying(
            rows, times, at + timedelta(seconds=horizon), at + timedelta(seconds=horizon + 30)
        )
        if entry is None or exit_obs is None:
            reasons["post_latency_entry_or_horizon_exit_missing"] += 1
            continue
        # FeeObservation archives bind immutable evidence IDs, whereas the
        # operational cache also includes a convenience URL reference. Use the
        # actual archived evidence ID as that reference; never assume zero fee.
        entry_schedule = dict(entry.fee or {})
        exit_schedule = dict(exit_obs.fee or {})
        for schedule in (entry_schedule, exit_schedule):
            if not schedule.get("reference") and schedule.get("evidence_id"):
                schedule["reference"] = schedule["evidence_id"]
        entry_rate = verified_fee_rate(entry_schedule, entry.book.available_at)
        exit_rate = verified_fee_rate(exit_schedule, exit_obs.book.available_at)
        context = entry.market
        if (
            context is None
            or context.status != "active"
            or not context.resolution_rules
            or not context.resolution_source
            or (context.end_time is not None and context.end_time <= exit_obs.book.available_at)
            or (entry.book.available_at - context.available_at).total_seconds() > 3600
        ):
            reasons["active_rule_context_unverified_or_stale"] += 1
            continue
        min_order = context.min_order_size
        for notional in (2, 5, 15, 25):
            qty = notional / entry.book.asks[0].price
            if min_order is None or qty + 1e-9 < min_order:
                reasons["minimum_lot_unverified_or_unmet"] += 1
                continue
            buy = depth_quote(entry.book.asks, qty, limit=min(0.999999, entry.book.asks[0].price + 0.01))
            sell = depth_quote(
                exit_obs.book.bids, qty, limit=max(0.000001, exit_obs.book.bids[0].price - 0.01), buy=False
            )
            full = buy["complete"] and sell["complete"]
            cost = buy["notional"]
            proceeds = sell["notional"]
            known = entry_rate is not None and exit_rate is not None
            bound_net = proceeds * (1 - exit_rate) - cost * (1 + entry_rate) if full and known else None
            curve_supported = known and all(
                "exponent1" in (o.fee or {}).get("assumption", "") for o in (entry, exit_obs)
            )
            curve_net = (
                proceeds
                - cost
                - buy["exponent1_fee_factor"] * entry_rate
                - sell["exponent1_fee_factor"] * exit_rate
                if full and curve_supported
                else None
            )
            slip_sensitivity = {
                str(slip): bound_net - 2 * qty * slip if bound_net is not None else None
                for slip in (0, 0.005, 0.01, 0.02)
            }
            output.append(
                {
                    "decision_book_id": decision.book.id,
                    "entry_book_id": entry.book.id,
                    "exit_book_id": exit_obs.book.id,
                    "market_id": decision.book.market_id,
                    "event_id": decision.market.event_id if decision.market else None,
                    "token_id": token,
                    "decision_at": at.isoformat(),
                    "entry_at": entry.book.available_at.isoformat(),
                    "entry_source_at": entry.book.timestamp.isoformat(),
                    "exit_at": exit_obs.book.available_at.isoformat(),
                    "exit_source_at": exit_obs.book.timestamp.isoformat(),
                    "notional_target": notional,
                    "shares": qty,
                    "entry_depth": buy,
                    "exit_depth": sell,
                    "observed_price_difference_before_fees": proceeds - cost if full else None,
                    "entry_fee_rate": entry_rate,
                    "exit_fee_rate": exit_rate,
                    "entry_fee_evidence_id": (entry.fee or {}).get("evidence_id"),
                    "exit_fee_evidence_id": (exit_obs.fee or {}).get("evidence_id"),
                    "hypothetical_net_difference_after_fee_bound": bound_net,
                    "protocol_exponent1_curve_counterfactual": curve_net,
                    "additional_per_leg_slippage_sensitivity": slip_sensitivity,
                    "imbalance_at_decision": feature["imbalance"],
                    "classification": "retrospective independent quote-capacity scenario; not an order, fill or portfolio return",
                }
            )
            if not full:
                reasons["displayed_depth_insufficient"] += 1
            if not known:
                reasons["point_in_time_fee_unavailable"] += 1
    return output, dict(reasons)


def run_microstructure(observations, manifest=None):
    if manifest is None:
        manifest = json.loads((Path(observations) / "manifest.json").read_text())
        data = load_dataset(observations)
    else:
        data = list(observations)
    features, rejects = causal_features(data)
    scenarios, execution_rejects = execution_scenarios(data, features)
    by_notional = {}
    for n in (2, 5, 15, 25):
        rows = [r for r in scenarios if r["notional_target"] == n]
        known = [r for r in rows if r["hypothetical_net_difference_after_fee_bound"] is not None]
        by_notional[str(n)] = {
            "quote_scenarios": len(rows),
            "complete_known_cost_scenarios": len(known),
            "depth_complete": sum(r["entry_depth"]["complete"] and r["exit_depth"]["complete"] for r in rows),
            "median_hypothetical_net_difference": median(
                r["hypothetical_net_difference_after_fee_bound"] for r in known
            )
            if known
            else None,
            "positive_at_additional_slippage_01": sum(
                r["additional_per_leg_slippage_sensitivity"]["0.01"] > 0 for r in known
            ),
            "protocol_curve_counterfactual_median": median(
                r["protocol_exponent1_curve_counterfactual"]
                for r in rows
                if r["protocol_exponent1_curve_counterfactual"] is not None
            )
            if any(r["protocol_exponent1_curve_counterfactual"] is not None for r in rows)
            else None,
            "positive_protocol_curve_with_slippage_01": sum(
                r["protocol_exponent1_curve_counterfactual"] - 2 * r["shares"] * 0.01 > 0
                for r in rows
                if r["protocol_exponent1_curve_counterfactual"] is not None
            ),
            "portfolio_pnl": None,
            "independent_confidence_interval": None,
        }
    imbalance_groups = {}
    for label, predicate in (
        ("bid_heavy", lambda x: x >= 0.25),
        ("ask_heavy", lambda x: x <= -0.25),
        ("balanced", lambda x: abs(x) < 0.25),
    ):
        group = [
            r
            for r in scenarios
            if r["notional_target"] == 2
            and predicate(r["imbalance_at_decision"])
            and r["hypothetical_net_difference_after_fee_bound"] is not None
        ]
        imbalance_groups[label] = {
            "scenarios": len(group),
            "mean_net_difference": mean(r["additional_per_leg_slippage_sensitivity"]["0.01"] for r in group)
            if group
            else None,
            "independent_confidence_interval": None,
        }
    spec = ExperimentSpec(
        experiment_id="phase11-microstructure-execution-v1",
        hypothesis="Top-five depth imbalance and quote persistence may predict 60s bid repricing large enough to cover observed spread, fee bound and depth costs",
        dataset_sha256=manifest["dataset_sha256"],
        model_version="fixed-descriptive-imbalance-v1",
        feature_definitions={
            "imbalance": "(top5 bid shares - top5 ask shares)/(sum)",
            "spread": "actual best ask minus bid",
            "persistence": "time since last actually observed top quote change",
            "volatility": "standard deviation of prior-only bid differences over20 observations",
        },
        target_definitions={
            "mark": "First fresh bid with source and receipt at least60s after decision, at most90s receipt",
            "cost": "Actual post100ms entry asks and60s exit bids,10% displayed participation,±.01 price bounds",
        },
        split_policy="Fixed descriptive hypothesis, no optimized rule or certification; quote scenarios exploratory, labels not independent",
        grouping={
            "tokens": manifest["tokens"],
            "reported_event_groups": manifest["event_groups"],
            "independently_reviewed_events": 0,
        },
        transaction_cost_assumptions={
            "fee": "conservative observed global notional bound separately at entry/exit; unknown remainsnull",
            "participation": 0.1,
            "latency_ms": 100,
            "additional_slippage_per_leg": [0, 0.005, 0.01, 0.02],
            "maker_fills": None,
        },
        failure_conditions=(
            "Unavailable post-latency book",
            "Missing/expired fee evidence",
            "Inadequate displayed liquidity",
            "Unknown minimum lot",
            "Dependent labels do not support independent inference",
        ),
        limitations=(
            "Sampled snapshots do not identify queue priority, realized market impact or passive fills",
            "Retrospective scenarios are not operational P/L",
            "No event-independent test or causal treatment effect",
            "No calibrated terminal probabilities or promotion",
        ),
    )
    return {
        "spec": spec.model_dump(mode="json"),
        "observations": len(data),
        "valid_features": len(features),
        "feature_rejections": rejects,
        "execution_rejections": execution_rejects,
        "feature_summary": {
            "median_spread": median(r["spread"] for r in features) if features else None,
            "median_abs_imbalance": median(abs(r["imbalance"]) for r in features) if features else None,
            "median_quote_persistence_seconds": median(r["quote_persistence_seconds"] for r in features)
            if features
            else None,
        },
        "cost_sensitivity": by_notional,
        "imbalance_groups": imbalance_groups,
        "calibration": {
            "terminal_brier": None,
            "terminal_log_loss": None,
            "reason": "No independently verified point-in-time terminal target dataset",
        },
        "profitability_claim": False,
        "independent_edge_established": False,
        "passive_execution": {
            "fills": None,
            "queue_position": None,
            "reason": "Displayed snapshots do not establish queue priority or adverse-selection behavior",
        },
        "actual_orders": 0,
        "actual_fills": 0,
        "scenario_samples": scenarios[:24],
    }
