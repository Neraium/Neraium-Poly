"""Height-aware loopback SSH monitor; unavailable observations never become zero."""

import asyncio
import math
import re
import unicodedata
from datetime import UTC, datetime

import httpx
from rich.console import Console
from rich.live import Live
from rich.text import Text

from neraium_poly.experimental.feed import loopback_url

# Strip terminal commands as well as C0/C1 and Unicode direction controls.
_ESCAPE = re.compile(r"\x1b\][^\x07]*(?:\x07|\x1b\\)|(?:\x1b\[|\x9b)[0-?]*[ -/]*[@-~]")


def _clean(value):
    text = _ESCAPE.sub("", str(value))
    return "".join(c for c in text if unicodedata.category(c) not in {"Cc", "Cf", "Cs", "Zl", "Zp"})[:180]


def _number(value, money=False):
    if value is None:
        return "—"
    try:
        parsed = float(value)
        if isinstance(value, bool) or not math.isfinite(parsed) or (not money and parsed < 0):
            return "unknown"
        return f"${parsed:.2f}" if money else f"{int(parsed):,}"
    except (ValueError, TypeError, OverflowError):
        return "unknown"


def _flag(value, yes="ACTIVE", no="clear"):
    return yes if value is True else no if value is False else "unknown"


def _mapping(value):
    return value if isinstance(value, dict) else {}


def _count(value):
    return len(value) if isinstance(value, (list, tuple, dict)) else value


def _seen(value):
    try:
        at = datetime.fromisoformat(value)
        return at.astimezone(UTC).strftime("%m-%d %H:%M:%SZ") if at.tzinfo is not None else "unknown"
    except (ValueError, TypeError, AttributeError):
        return "unknown"


def _strategy_rows(experimental):
    rows = experimental.get("strategies", [])
    if isinstance(rows, dict):
        rows = [{"strategy_id": key, **_mapping(value)} for key, value in rows.items()]
    rows = [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []
    engine = _mapping(experimental.get("strategy_engine"))
    enabled = engine.get("enabled", engine.get("enabled_strategies", []))
    if not rows and isinstance(enabled, list):
        rows = [{"strategy_id": value, "enabled": True} for value in enabled if isinstance(value, str)]
    elif isinstance(enabled, list) and ("enabled" in engine or "enabled_strategies" in engine):
        rows = [{**row, "enabled": row.get("strategy_id", row.get("id")) in enabled} for row in rows]

    def score(row):
        value = row.get("simulated_realized_pnl", row.get("realized_pnl"))
        try:
            return float(value) if math.isfinite(float(value)) else float("-inf")
        except (ValueError, TypeError, OverflowError):
            return float("-inf")

    return sorted(rows, key=score, reverse=True)


def _short_name(value):
    names = {
        "cross_market_consistency": "Cross-market",
        "persistent_relationship": "Relationship",
        "persistent_relationship_repricing": "Relationship",
        "liquidity_spread": "Spread",
        "liquidity_maker": "Spread",
        "event_driven": "Event-driven",
        "event_repricing": "Event-driven",
        "short_horizon": "Short-horizon",
        "microstructure": "Microstructure",
        "calibrated_forecast": "Forecast",
        "calibrated_probability": "Forecast",
    }
    return names.get(str(value), _clean(value).replace("_", " "))


def render_monitor(
    certified=None, experimental=None, *, width=40, height=24, errors=(), view="summary", scope="cycle"
):
    """Fit every critical account label within a phone's actual terminal height.

    The viewport is bounded before Rich Live renders it, preserving safety/status
    rows that would otherwise scroll offscreen. Larger terminals show more
    strategy/rejection/activity details. Numbers are never synthesized for gaps.
    """
    width, height = max(30, min(int(width), 160)), max(12, min(int(height or 24), 100))
    certified, experimental = _mapping(certified), _mapping(experimental)
    if view not in {"summary", "strategies", "rejections", "research", "events"} or scope not in {
        "cycle",
        "epoch",
    }:
        raise ValueError("monitor view or scope invalid")
    if view == "events":
        return _render_events(certified, experimental, width, height, errors)
    if view == "research":
        return _render_research(certified, experimental, width, height, errors, scope)
    if view != "summary":
        return _render_detail(certified, experimental, width, height, errors, view, scope)
    operation = _mapping(certified.get("operation"))
    connection = _mapping(operation.get("connectivity"))
    live = certified.get("mode") == "live_market_paper"
    core = []

    def line(text, style="white", priority=1):
        core.append((str(text), style, priority))

    line("REAL MARKET DATA", "bold cyan", 0)
    if live:
        line(
            f"Markets {_number(_mapping(operation.get('scan')).get('discovered_markets'))} Fresh {_fresh(operation.get('fresh_books'), _source_tokens(operation, experimental))}"
        )
        line(
            f"WS {_flag(connection.get('ws_connected'), 'connected', 'disconnected')} Health {_clean(_mapping(operation.get('service')).get('status', 'unknown'))}"
        )
        intelligence = _mapping(_mapping(experimental.get("strategy_engine")).get("intelligence"))
        line(
            f"Relations {_number(_count(certified.get('relationships')))} Evidence/cycle {_number(intelligence.get('evaluations'))}",
            priority=2,
        )
        line(
            f"Process gaps {_number(connection.get('gaps'))} Reconnect {_number(connection.get('reconnects'))}",
            priority=3,
        )
        line(f"Seen {_seen(certified.get('generated_at'))}", "dim", 3)
    else:
        line("No verified live feed available", "yellow")
    line("EXPERIMENTAL PAPER TRADING", "bold yellow", 0)
    if experimental.get("account_id") == "experimental-paper":
        stale_tokens = experimental.get("stale_mark_tokens")
        stale_marks = bool(stale_tokens) or experimental.get("pnl_valuation") == "stale_last_observed_marks"
        if stale_marks:
            line(f"UNVALIDATED · STALE MARKS {_number(_count(stale_tokens))}", "yellow")
        else:
            line(
                f"UNVALIDATED · Health {_clean(_mapping(experimental.get('service')).get('status', 'unknown'))}",
                "yellow",
            )
        pnl_label = "P/L(last)" if stale_marks else "P/L"
        line(
            f"Cash {_number(experimental.get('cash'), True)}  {pnl_label} {_number(experimental.get('simulated_pnl'), True)}"
        )
        line(
            f"Exposure {_number(experimental.get('exposure'), True)} Reserved {_number(experimental.get('reserved'), True)}",
            priority=2,
        )
        line(
            f"Pos {_number(_count(experimental.get('positions')))} Ord {_number(_count(experimental.get('orders')))} Fill {_number(experimental.get('fills'))} Opp {_number(experimental.get('qualified_opportunities'))}"
        )
        line(
            f"Emergency stop: {_flag(experimental.get('suspended'))}",
            "red" if experimental.get("suspended") is True else "white",
        )
    else:
        line("UNVALIDATED · account unavailable", "yellow")
        line("Values unknown; API unavailable")
    line("CERTIFIED PAPER TRADING", "bold green", 0)
    if live:
        line(
            f"Cash {_number(certified.get('cash'), True)}  P/L {_number(certified.get('simulated_pnl'), True)}"
        )
        line(
            f"Exposure {_number(certified.get('exposure'), True)} Stop {_flag(certified.get('suspended'))}",
            "red" if certified.get("suspended") is True else "white",
        )
        line(f"Gate: {_clean(_mapping(operation.get('service')).get('trading_status', 'unknown'))}")
        coverage = _mapping(_mapping(certified.get("research")).get("coverage"))
        owner = _flag(_mapping(operation.get("validation")).get("active"), "active", "withheld")
        qualification = _mapping(experimental.get("historical_qualification"))
        if isinstance(qualification.get("chain_corroborated_exact_settlement_groups"), int):
            line(
                f"Chain settlements {qualification['chain_corroborated_exact_settlement_groups']}/{_number(qualification.get('events'))}",
                priority=2,
            )
        line(
            f"Train/test {_number(coverage.get('train_events'))}/{_number(coverage.get('heldout_events'))} Owner {owner}",
            priority=2,
        )
    else:
        line("Values unknown; API unavailable")
        line("Gate and emergency stop unknown", "yellow")

    trace = _mapping(experimental.get("decision_trace"))
    if trace:
        # Give decision explanations priority over secondary telemetry.
        core = [row for row in core if row[2] < 2]
    # At tiny heights keep account labels, bankroll, gate and stop information;
    # omit lower priority telemetry first. Normal 24-row phones keep all core rows.
    footer = [(_safety_footer(certified, experimental), "dim", 0), ("Ctrl-C exits monitor only", "dim", 2)]
    while len(core) + len(footer) + 1 > height and any(row[2] > 1 for row in core):
        priority = max(row[2] for row in core)
        index = next(i for i in range(len(core) - 1, -1, -1) if core[i][2] == priority)
        core.pop(index)
    while len(core) + len(footer) > height:
        if len(footer) > 1:
            footer.pop()
        else:
            index = next((i for i in range(len(core) - 1, -1, -1) if core[i][2] > 0), None)
            if index is None:
                break
            core.pop(index)
    budget = height - len(core) - len(footer)
    details = []
    rows = _strategy_rows(experimental)
    reasons = _mapping(experimental.get("rejection_reasons"))
    activity = experimental.get("latest_activity", [])
    if budget:
        details.append(("LEGACY STRATEGIES / REJECTIONS", "bold", 0))
        budget -= 1
    error_rows = [(_clean(value), "yellow", 1) for value in tuple(errors)[:2]]
    # Reserve one line each for rankings, rejection and latest activity when available.
    if budget:
        if rows:
            row = rows[0]
            state = _strategy_state(row)
            value = row.get("simulated_realized_pnl", row.get("realized_pnl"))
            details.append(
                (
                    f"{_short_name(row.get('strategy_id', row.get('id', 'unknown')))} {state} P/L {_number(value, True)}",
                    "cyan",
                    1,
                )
            )
        else:
            details.append(("No strategy observations yet.", "dim", 1))
        budget -= 1
    if budget and reasons:
        reason = max(reasons, key=lambda key: _finite_count(reasons[key]))
        details.append((f"Rej {_number(reasons[reason])} {_reason_label(reason)}", "dim", 1))
        budget -= 1
    cycle = _mapping(experimental.get("last_cycle"))
    if budget and not activity and cycle:
        seen = _seen(cycle.get("timestamp"))
        time_label = seen[6:] if seen != "unknown" else seen
        details.append(
            (
                f"Last {time_label} {_number(cycle.get('signal_count'))} eval {_number(cycle.get('eligible_count'))} opp",
                "white",
                1,
            )
        )
        budget -= 1
    if budget and isinstance(activity, list) and activity:
        details.append(("Last: " + _clean(activity[-1]), "white", 1))
        budget -= 1
    for row in error_rows[:budget]:
        details.append(row)
        budget -= 1
    for row in rows[1 : 1 + budget]:
        state = _strategy_state(row)
        value = row.get("simulated_realized_pnl", row.get("realized_pnl"))
        details.append(
            (
                f"{_short_name(row.get('strategy_id', row.get('id', 'unknown')))} {state} P/L {_number(value, True)}",
                "cyan",
                1,
            )
        )
    if trace:
        details = _trace_summary(experimental, scope, height - len(core) - len(footer))
    rendered = Text()
    for index, (value, style, _) in enumerate(core + details + footer):
        text = Text(_clean(value), style=style, no_wrap=True, overflow="ellipsis")
        text.truncate(width, overflow="ellipsis")
        if index:
            rendered.append("\n")
        rendered.append_text(text)
    return rendered


def _safety_footer(certified, experimental):
    services = (
        _mapping(_mapping(certified.get("operation")).get("service")),
        _mapping(experimental.get("service")),
    )
    if any(
        service.get("live_trading_enabled") is True or service.get("paper_trading") is False
        for service in services
    ):
        return "WARNING LIVE CONFIGURATION UNSAFE"
    return "LIVE FINANCIAL TRADING DISABLED"


def _reason_label(reason):
    labels = {
        "conservative_roundtrip_edge_insufficient": "net edge below floor",
        "persistent_contextual_relationship_evidence_required": "persistent evidence missing",
        "independent_context_verified_labels_and_calibration_required": "context/calibration missing",
        "independently_reviewed_exhaustive_payoff_scope_required": "payoff scope unverified",
        "multi_leg_execution_and_hedging_not_supported": "multi-leg unsupported",
        "independent_predecision_context_and_response_model_required": "causal context/model missing",
        "two_sided_inventory_execution_not_supported": "two-sided execution unsupported",
        "validated_queue_and_adverse_selection_model_required": "queue/adverse model missing",
        "insufficient_causal_bid_history": "causal bid history insufficient",
        "unknown_fee_schedule": "fee schedule unknown",
    }
    return labels.get(str(reason), _clean(reason).replace("_", " "))


def _compact_count(value):
    number = _finite_count(value)
    if number < 0 or isinstance(value, bool):
        return "—"
    for scale, suffix in ((1e9, "G"), (1e6, "M"), (1e3, "k")):
        if number >= scale:
            return f"{int(number / scale)}{suffix}"
    return str(int(number))


def _source_tokens(operation, experimental):
    subscribed = _mapping(operation.get("connectivity")).get("subscribed_tokens")
    return (
        subscribed
        if subscribed is not None
        else experimental.get("source_tokens", operation.get("current_books"))
    )


def _fresh(fresh, total):
    """No percentage without a verified compatible denominator."""
    a, b = _finite_count(fresh), _finite_count(total)
    percentage = f" {100 * a / b:.0f}%" if 0 <= a <= b and b > 0 else ""
    return f"{_number(fresh)}/{_number(total)}{percentage}"


def _trace_rows(experimental, scope):
    trace = _mapping(experimental.get("decision_trace"))
    selected = _mapping(
        trace.get("latest_cycle" if scope == "cycle" else "phase10_epoch", trace.get("totals"))
    )
    return _mapping(selected.get("strategies", selected))


def _aggregate(rows, key):
    values = [row.get(key) for row in rows.values() if isinstance(row, dict)]
    if not values or any(_finite_count(value) < 0 or isinstance(value, bool) for value in values):
        return None
    return sum(float(value) for value in values)


def _trace_reasons(rows):
    reasons = {}
    for row in rows.values():
        values = _mapping(_mapping(row).get("reasons", _mapping(row).get("rejections")))
        for reason, evidence in values.items():
            count = evidence.get("count") if isinstance(evidence, dict) else evidence
            if _finite_count(count) >= 0 and not isinstance(count, bool):
                reasons[reason] = reasons.get(reason, 0) + float(count)
    return sorted(reasons.items(), key=lambda pair: (-pair[1], str(pair[0])))


def _scope_line(experimental, scope):
    trace = _mapping(experimental.get("decision_trace"))
    if not trace:
        return "Legacy counters; trace unavailable"
    if scope == "epoch":
        return f"Epoch since {_seen(trace.get('epoch_started_at', trace.get('epoch')))}"
    return f"Cycle (latest) {_seen(trace.get('last_evaluation_at', _mapping(experimental.get('last_cycle')).get('timestamp')))}"


def _trace_summary(experimental, scope, budget):
    rows = _trace_rows(experimental, scope)
    count = lambda key: _number(_aggregate(rows, key))
    details = [(_scope_line(experimental, scope), "dim", 1)]
    details.append(
        (f"Considered {count('markets_considered')} Valid {count('valid_observations')}", "white", 1)
    )
    details.append(
        (f"Signals {count('candidate_signals')} Qualified {count('qualified_opportunities')}", "white", 1)
    )
    reasons = _trace_reasons(rows)
    if reasons:
        reason, value = reasons[0]
        details.append((f"Rej {_number(value)} {_reason_label(reason)}", "yellow", 1))
    elif rows:
        details.append(("No rejection evidence in this scope", "dim", 1))
    else:
        details.append(("No completed traced evaluations", "yellow", 1))
    return details[: max(0, budget)]


def _render_detail(certified, experimental, width, height, errors, view, scope):
    """Read-only phone pages; each page preserves identities and account safety."""
    operation = _mapping(certified.get("operation"))
    live = certified.get("mode") == "live_market_paper"
    exp = experimental.get("account_id") == "experimental-paper"
    trace = _mapping(experimental.get("decision_trace"))
    rows = _trace_rows(experimental, scope)
    lines = [("REAL MARKET DATA", "bold cyan")]
    if live:
        lines.append(
            (
                f"Markets {_number(_mapping(operation.get('scan')).get('discovered_markets'))} Fresh {_fresh(operation.get('fresh_books'), _source_tokens(operation, experimental))}",
                "white",
            )
        )
    else:
        lines.append(("No verified live feed available", "yellow"))
    lines.append(("EXPERIMENTAL PAPER TRADING", "bold yellow"))
    lines.append(
        (
            f"UNVALIDATED Stop {_flag(experimental.get('suspended'))}"
            if exp
            else "UNVALIDATED · account unavailable",
            "yellow",
        )
    )
    stale = (
        bool(experimental.get("stale_mark_tokens"))
        or experimental.get("pnl_valuation") == "stale_last_observed_marks"
    )
    label = "P/L(last)" if stale else "P/L"
    lines.append(
        (
            f"Cash {_number(experimental.get('cash') if exp else None, True)} {label} {_number(experimental.get('simulated_pnl') if exp else None, True)}",
            "white",
        )
    )
    lines.append(
        (
            f"Exposure {_number(experimental.get('exposure') if exp else None, True)} Pos {_number(_count(experimental.get('positions')) if exp else None)}",
            "white",
        )
    )
    lines.append(
        (
            f"Exp fresh {_fresh(experimental.get('experimental_fresh_books'), experimental.get('selected_tokens'))}",
            "dim",
        )
    )
    lines.append(("CERTIFIED PAPER TRADING", "bold green"))
    lines.append(
        (
            f"Cash {_number(certified.get('cash') if live else None, True)} P/L {_number(certified.get('simulated_pnl') if live else None, True)}",
            "white",
        )
    )
    lines.append(
        (
            f"Gate {_clean(_mapping(operation.get('service')).get('trading_status', 'unknown'))} Stop {_flag(certified.get('suspended') if live else None)}",
            "white",
        )
    )
    lines.append((_scope_line(experimental, scope), "dim"))
    if view == "strategies":
        lines.append(("Strategy   C   S   Q   R   O   F", "bold"))
        fields = (
            "markets_considered",
            "candidate_signals",
            "qualified_opportunities",
            "rejected_signals",
            "submitted_orders",
            "fills",
        )
        for strategy_id, row in rows.items():
            values = " ".join(f"{_compact_count(_mapping(row).get(key)):>3}" for key in fields)
            lines.append((f"{_short_name(strategy_id)[:8]:8} {values}", "white"))
        count = lambda key: _number(_aggregate(rows, key))
        lines.append(
            (
                f"Valid {count('valid_observations')} Risk {count('risk_rejections')} Attempts {count('order_attempts')}",
                "white",
            )
        )
        lines.append((f"Expired {count('expired_orders')} Cancel {count('cancelled_orders')}", "white"))
        lines.append(("C considered S candidate Q qualified", "dim"))
        lines.append(("R rejected O orders F fill events", "dim"))
    else:
        lines.append(("REJECTIONS · nonexclusive counts", "bold"))
        categories = {}
        for row in rows.values():
            for reason in _mapping(_mapping(row).get("reasons")).values():
                evidence = _mapping(reason)
                count = evidence.get("count")
                if _finite_count(count) >= 0 and not isinstance(count, bool):
                    category = evidence.get("category", "UNKNOWN")
                    categories[category] = categories.get(category, 0) + float(count)
            for category, count in _mapping(_mapping(row).get("categories")).items():
                if (
                    not _mapping(row).get("reasons")
                    and _finite_count(count) >= 0
                    and not isinstance(count, bool)
                ):
                    categories[category] = categories.get(category, 0) + float(count)
        for category, count in sorted(categories.items(), key=lambda pair: -pair[1])[:3]:
            lines.append((f"{_number(count)} {_clean(category)}", "dim"))
        for reason, count in _trace_reasons(rows):
            lines.append((f"{_number(count)} {_reason_label(reason)}", "yellow"))
        if trace and not _trace_reasons(rows):
            lines.append(("No rejection evidence in this scope", "dim"))
    if not trace:
        lines.append(("No Phase10 trace; legacy API", "yellow"))
    if stale:
        lines.insert(5, ("STALE MARKS · last valuation", "yellow"))
    for error in errors:
        lines.insert(1, (_clean(error), "yellow"))
    footer = [(_safety_footer(certified, experimental), "dim"), ("Ctrl-C exits monitor only", "dim")]
    rendered = Text()
    for index, (value, style) in enumerate(lines[: max(0, height - len(footer))] + footer):
        if index:
            rendered.append("\n")
        row = Text(_clean(value), style=style, no_wrap=True, overflow="ellipsis")
        row.truncate(width, overflow="ellipsis")
        rendered.append_text(row)
    return rendered


def _event_metric(value):
    if value is None or isinstance(value, bool):
        return "unavailable"
    try:
        value = float(value)
        return f"{value:.5f}" if math.isfinite(value) and value >= 0 else "unavailable"
    except (ValueError, TypeError):
        return "unavailable"


def _render_events(certified, experimental, width, height, errors):
    """Outcome forecasting is explicit research, separate from both paper accounts."""
    operation = _mapping(certified.get("operation"))
    live = certified.get("mode") == "live_market_paper"
    exp = experimental.get("account_id") == "experimental-paper"
    event = _mapping(experimental.get("event_intelligence"))
    ledger = _mapping(event.get("ledger", event))
    available = bool(ledger) and ledger.get("status") not in {"unavailable", "stale", "invalid"}
    scores = _mapping(ledger.get("scores")) if available else {}
    baseline = _mapping(ledger.get("baseline_scores")) if available else {}
    history = _mapping(event.get("historical_qualification", experimental.get("historical_qualification")))
    relationships = _mapping(event.get("relationships", event.get("sii"))) if available else {}
    versions = ledger.get("model_versions", []) if available else []
    version_text = _clean(versions[0]) if isinstance(versions, list) and versions else "unavailable"
    reason = event.get("last_rejection", event.get("reason"))
    rejections = _mapping(event.get("rejections"))
    if not reason and rejections:
        reason = max(rejections, key=lambda k: _finite_count(rejections[k]))
    reason = (
        (reason or "Insufficient independent evidence")
        if available
        else "Report unavailable/stale; insufficient evidence"
    )
    stale_marks = (
        bool(experimental.get("stale_mark_tokens"))
        or experimental.get("pnl_valuation") == "stale_last_observed_marks"
    )
    pnl = "P/L(last)" if stale_marks else "P/L"

    def count(key):
        return _number(ledger.get(key) if available else None)

    lines = [
        ("REAL MARKET DATA", "bold cyan"),
        (
            f"Markets {_number(_mapping(operation.get('scan')).get('discovered_markets') if live else None)} WS {_flag(_mapping(operation.get('connectivity')).get('ws_connected'), 'up', 'down')}",
            "white",
        ),
        ("RESEARCH FORECAST", "bold yellow"),
        (
            f"Events {count('events_tracked')} Pending {count('forecasts_pending')} Done {count('forecasts_resolved')}",
            "white",
        ),
        (
            f"Groups {count('resolved_forecast_groups')} Independent {count('independent_event_groups')}",
            "white",
        ),
        (f"Model {version_text}", "dim"),
        (f"Cal {_research_text(ledger.get('calibration_status') if available else None)}", "dim"),
        (f"Brier {_event_metric(scores.get('brier'))} n={_number(scores.get('count'))}", "white"),
        (f"Log loss {_event_metric(scores.get('log_loss'))}", "white"),
        (f"Market Brier {_event_metric(baseline.get('brier'))}", "dim"),
        (
            f"History {_number(history.get('chain_corroborated_exact_settlement_groups'))}/{_number(history.get('events'))}",
            "dim",
        ),
        (
            f"Train/test {_number(history.get('qualified_training_events'))}/{_number(history.get('qualified_heldout_events'))} need 100/100",
            "dim",
        ),
        (
            f"SII findings {_number(relationships.get('qualified_findings', relationships.get('persistent_findings')))}",
            "dim",
        ),
        (
            f"Exp opp {_number(event.get('experimental_opportunities'))} Rej {_number(sum(v for v in rejections.values() if isinstance(v, int))) if rejections else '—'}",
            "white",
        ),
        (f"Block {_reason_label(reason)}", "yellow"),
        ("EXPERIMENTAL PAPER", "bold yellow"),
        (
            f"{_number(experimental.get('cash') if exp else None, True)} {pnl} {_number(experimental.get('simulated_pnl') if exp else None, True)}",
            "white",
        ),
        (
            f"Ord {_number(_count(experimental.get('orders')) if exp else None)} Fill {_number(experimental.get('fills') if exp else None)} Pos {_number(_count(experimental.get('positions')) if exp else None)}",
            "white",
        ),
        (
            f"Stop {_flag(experimental.get('suspended') if exp else None)} Health {_research_text(_mapping(experimental.get('service')).get('status'))}",
            "white",
        ),
        ("CERTIFIED PAPER", "bold green"),
        (
            f"{_number(certified.get('cash') if live else None, True)} P/L {_number(certified.get('simulated_pnl') if live else None, True)}",
            "white",
        ),
        (f"Gate {_research_text(_mapping(operation.get('service')).get('trading_status'))}", "white"),
    ]
    if errors:
        lines[14] = ("API " + _clean(errors[0]), "yellow")
    footer = [(_safety_footer(certified, experimental), "dim"), ("Ctrl-C exits monitor only", "dim")]
    # Tiny viewports retain all three identities and cash/gate; remove secondary
    # research detail first. Normal phone height preserves all 22 content rows.
    priority = [9, 8, 7, 12, 13, 10, 11, 5, 6, 1, 17, 18, 14, 4, 3]
    keep = list(range(len(lines)))
    for index in priority:
        if len(keep) <= height - 2:
            break
        keep.remove(index)
    rendered = Text()
    for index, (value, style) in enumerate([lines[i] for i in keep] + footer):
        if index:
            rendered.append("\n")
        row = Text(_clean(value), style=style, no_wrap=True, overflow="ellipsis")
        row.truncate(width, overflow="ellipsis")
        rendered.append_text(row)
    return rendered


def _research_text(value, default="unavailable"):
    if value is None:
        return default
    if isinstance(value, dict):
        return _clean(value.get("summary", value.get("status", default)))
    return _clean(value)


def _qualification_rate(value):
    if value is None or isinstance(value, bool):
        return "—"
    try:
        value = float(value)
        return f"{value * 100:.1f}%" if math.isfinite(value) and 0 <= value <= 1 else "unknown"
    except (ValueError, TypeError):
        return "unknown"


def _render_research(certified, experimental, width, height, errors, scope):
    """Research is a separate, explicitly unvalidated observation, never P/L."""
    operation = _mapping(certified.get("operation"))
    live = certified.get("mode") == "live_market_paper"
    exp = experimental.get("account_id") == "experimental-paper"
    report = _mapping(experimental.get("research"))
    status = _research_text(report.get("status"), "unavailable")
    unavailable = not report or status in {"unavailable", "unknown", "invalid", "stale"}
    lines = [("REAL MARKET DATA", "bold cyan")]
    lines.append(
        (
            f"Markets {_number(_mapping(operation.get('scan')).get('discovered_markets') if live else None)} Fresh {_fresh(operation.get('fresh_books') if live else None, _source_tokens(operation, experimental) if live else None)}",
            "white",
        )
    )
    stale_marks = (
        bool(experimental.get("stale_mark_tokens"))
        or experimental.get("pnl_valuation") == "stale_last_observed_marks"
    )
    pnl_label = "P/L(last)" if stale_marks else "P/L"
    lines.append(("EXPERIMENTAL PAPER TRADING", "bold yellow"))
    lines.append(
        (
            f"{_number(experimental.get('cash') if exp else None, True)} {pnl_label} {_number(experimental.get('simulated_pnl') if exp else None, True)} Stop {_flag(experimental.get('suspended') if exp else None)}",
            "yellow",
        )
    )
    lines.append(("CERTIFIED PAPER TRADING", "bold green"))
    lines.append(
        (
            f"{_number(certified.get('cash') if live else None, True)} Gate {_clean(_mapping(operation.get('service')).get('trading_status', 'unknown'))}",
            "white",
        )
    )
    lines.append(("RESEARCH · UNVALIDATED", "bold"))
    lines.append((f"{scope} {status} {_seen(report.get('generated_at'))}", "dim"))
    rows = report.get("strategies", [])
    rows = [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []
    rows = rows[:6]
    trace = _trace_rows(experimental, scope)
    if not rows and trace:
        rows = [{"strategy_id": sid} for sid in list(trace)[:6]]
    lines.append(("Strategy     Eval   Cand    Q%", "bold"))
    for row in rows:
        sid = row.get("strategy_id", "unknown")
        counts = _mapping(trace.get(sid))
        evaluations = counts.get("markets_considered", None if unavailable else row.get("evaluations"))
        candidates = counts.get("candidate_signals", None if unavailable else row.get("candidate_signals"))
        # Operational qualification uses the selected live counter scope. A
        # report's exploratory qualification is never silently substituted.
        rate = None if unavailable else row.get("qualification_rate")
        if counts:
            valid_count = _finite_count(evaluations)
            qualified = _finite_count(counts.get("qualified_opportunities"))
            rate = qualified / valid_count if valid_count > 0 and qualified >= 0 else None
        lines.append(
            (
                f"{_short_name(sid)[:11]:11} {_compact_count(evaluations):>5} {_compact_count(candidates):>5} {_qualification_rate(rate):>6}",
                "white",
            )
        )
    if not rows:
        lines.append(("No research artifact; metrics unknown", "yellow"))
    first = rows[0] if rows else {}
    baseline = None if unavailable else report.get("baseline_comparison", first.get("baseline_comparison"))
    lines.append((f"Base {_research_text(baseline)}", "dim"))
    calibration = None if unavailable else report.get("calibration_status", first.get("calibration_status"))
    lines.append((f"Cal {_research_text(calibration)}", "dim"))
    lines.append(
        (
            f"Evidence {_number(report.get('independent_training_events'))}/{_number(report.get('independent_heldout_events'))} need 100/100",
            "dim",
        )
    )
    edge = next((r.get("estimated_net_edge") for r in rows if r.get("estimated_net_edge") is not None), None)
    if unavailable:
        edge = None
    try:
        edge_text = (
            f"{float(edge):+.4f}/share" if edge is not None and math.isfinite(float(edge)) else "unavailable"
        )
    except (ValueError, TypeError):
        edge_text = "unavailable"
    lines.append((f"Edge {edge_text}", "white"))
    confidence = None if unavailable else report.get("confidence", first.get("confidence"))
    lines.append((f"Confidence {_research_text(confidence)}", "dim"))
    reasons = _trace_reasons(trace)
    if reasons:
        reason, count = reasons[0]
        lines.append((f"Rej {_number(count)} {_reason_label(reason)}", "yellow"))
    else:
        lines.append((f"Block {_research_text(first.get('bottleneck'))}", "yellow"))
    if unavailable:
        lines.append(("Report unavailable/stale; no inference", "yellow"))
    else:
        lines.append(("No automatic strategy promotion", "dim"))
    for error in errors:
        lines.insert(7, (_clean(error), "yellow"))
    footer = [(_safety_footer(certified, experimental), "dim"), ("Ctrl-C exits monitor only", "dim")]
    rendered = Text()
    for index, (value, style) in enumerate(lines[: max(0, height - 2)] + footer):
        if index:
            rendered.append("\n")
        row = Text(_clean(value), style=style, no_wrap=True, overflow="ellipsis")
        row.truncate(width, overflow="ellipsis")
        rendered.append_text(row)
    return rendered


def _strategy_state(row):
    if row.get("suspended") is True:
        return "SUSPENDED"
    return _flag(row.get("enabled"), "on", "off") if "enabled" in row else "research"


def _finite_count(value):
    try:
        return float(value) if math.isfinite(float(value)) else -1
    except (ValueError, TypeError, OverflowError):
        return -1


async def fetch_views(certified_url, experimental_url):
    async with httpx.AsyncClient(timeout=5, follow_redirects=False) as client:

        async def read(url, label):
            try:
                content = bytearray()
                async with client.stream("GET", loopback_url(url)) as response:
                    response.raise_for_status()
                    async for chunk in response.aiter_bytes():
                        if len(content) + len(chunk) > 8 * 1024 * 1024:
                            raise ValueError("state budget exceeded")
                        content.extend(chunk)
                import json

                value = json.loads(content)
                if not isinstance(value, dict):
                    raise TypeError("state object required")
                return value, None
            except (httpx.HTTPError, ValueError, TypeError) as error:
                return None, f"{label}: {type(error).__name__}"

        pairs = await asyncio.gather(
            read(certified_url, "Certified API"), read(experimental_url, "Experimental API")
        )
    return pairs[0][0], pairs[1][0], tuple(p[1] for p in pairs if p[1])


def monitor(
    *,
    once=False,
    width=None,
    refresh=3,
    certified_url="http://127.0.0.1:18742/api/state",
    experimental_url="http://127.0.0.1:18743/api/state",
    no_color=False,
    view="summary",
    scope="cycle",
):
    loopback_url(certified_url)
    loopback_url(experimental_url)
    if not 1 <= refresh <= 60:
        raise ValueError("monitor refresh must be1–60 seconds")
    console = Console(width=width, no_color=no_color)

    async def run():
        if once:
            c, e, errors = await fetch_views(certified_url, experimental_url)
            console.print(
                render_monitor(
                    c,
                    e,
                    width=console.width,
                    height=max(12, console.height - 1),
                    errors=errors,
                    view=view,
                    scope=scope,
                )
            )
            return
        with Live(console=console, auto_refresh=False, screen=False, vertical_overflow="crop") as live:
            while True:
                c, e, errors = await fetch_views(certified_url, experimental_url)
                live.update(
                    render_monitor(
                        c,
                        e,
                        width=console.width,
                        height=max(12, console.height - 1),
                        errors=errors,
                        view=view,
                        scope=scope,
                    ),
                    refresh=True,
                )
                await asyncio.sleep(refresh)

    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        console.print("Monitor stopped; paper services continue.", style="dim")
