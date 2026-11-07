"""Height-aware loopback SSH monitor; unavailable observations never become zero."""

import asyncio
import math
import re
import unicodedata
from datetime import UTC, datetime
from urllib.parse import urlsplit, urlunsplit

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
    if view not in {"summary", "strategies", "rejections", "research", "events", "domains", "archives", "operations", "readiness", "edge", "challengers"} or scope not in {
        "cycle",
        "epoch",
    }:
        raise ValueError("monitor view or scope invalid")
    if view == "challengers":
        return _render_challengers(certified, experimental, width, height, errors)
    if view == "edge":
        event = _mapping(_mapping(experimental.get("operations_research")).get("phase18"))
        if event and event.get("status") != "disabled":
            return _render_event_edge(certified, experimental, width, height, errors)
        return _render_edge(certified, experimental, width, height, errors)
    if view == "readiness":
        return _render_readiness(certified, experimental, width, height, errors)
    if view == "operations":
        return _render_operations(certified, experimental, width, height, errors)
    if view == "archives":
        return _render_archives(certified, experimental, width, height, errors)
    if view == "domains":
        return _render_domains(certified, experimental, width, height, errors)
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



def _ops_fresh(value, now):
    try:
        at = datetime.fromisoformat(value)
        return at.tzinfo is not None and 0 <= (now-at).total_seconds() <= 60
    except (TypeError, ValueError, AttributeError):
        return False


def _ops_bytes(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        return "—"
    if value >= 1024**3:
        return f"{value/1024**3:.1f}GiB"
    if value >= 1024**2:
        return f"{value/1024**2:.1f}MiB"
    return f"{value/1024:.1f}KiB"


def _ops_horizon(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        return "unknown"
    return f"{value/86400:.1f}d" if value >= 86400 else f"{value/3600:.1f}h"


def _p16_recent(value, now, seconds=15):
    try:
        at = datetime.fromisoformat(value)
        return at.tzinfo is not None and 0 <= (now - at).total_seconds() <= seconds
    except (TypeError, ValueError, AttributeError):
        return False


def _render_readiness(certified, experimental, width, height, errors):
    """Phone-sized evidence progress; original quote times control current claims."""
    now = datetime.now(UTC)
    operation = _mapping(certified.get("operation"))
    connection = _mapping(operation.get("connectivity"))
    cs, es = _mapping(operation.get("service")), _mapping(experimental.get("service"))
    cf, ef = (_ops_fresh(v.get("generated_at"), now) for v in (certified, experimental))
    live = (cf and certified.get("mode") == "live_market_paper" and cs.get("status") == "ok"
            and _ops_fresh(cs.get("timestamp"), now) and connection.get("ws_connected") is True
            and _p16_recent(connection.get("last_message_at"), now))
    study = _mapping(_mapping(experimental.get("operations_research")).get("phase16"))
    history, qualification = _mapping(study.get("history")), _mapping(study.get("qualification"))
    mark = _mapping(qualification.get("mark_research_readiness"))
    calibration = _mapping(qualification.get("calibration"))
    tokens = history.get("per_token", [])
    if isinstance(tokens, dict):
        tokens = list(tokens.values())
    quote_current = isinstance(tokens, list) and any(
        isinstance(row, dict) and _p16_recent(row.get("latest_source_at"), now)
        and _p16_recent(row.get("latest_available_at"), now) for row in tokens)
    study_fresh = ef and _ops_fresh(study.get("last_study_at"), now)
    current = live and study_fresh and quote_current
    lines = []

    def line(value, priority=2, style="white"):
        lines.append((_clean(value), style, priority))

    def reason(value):
        return _clean(value).replace("_", " ")

    line("QUALIFICATION READINESS", 0, "bold cyan")
    line("REAL MARKET DATA" if live else "SOURCE STALE / UNAVAILABLE", 0, "cyan" if live else "yellow")
    line("EXPERIMENTAL PAPER", 0, "bold yellow")
    line(f"{'Last ' if experimental and not ef else ''}{_number(experimental.get('cash'), True)} Sim P/L {_number(experimental.get('simulated_pnl'), True)}", 0)
    line(f"Stop {_flag(experimental.get('kill_switch', experimental.get('suspended')))}", 0, "yellow")
    line("CERTIFIED PAPER", 0, "bold green")
    line(f"{'Last ' if certified and not cf else ''}{_number(certified.get('cash'), True)} Sim P/L {_number(certified.get('simulated_pnl'), True)}", 0)
    execution_context = _mapping(qualification.get("execution_context"))
    bound_current = (execution_context.get("bound") is True
                     and _p16_recent(execution_context.get("source_at"), now)
                     and _p16_recent(execution_context.get("available_at"), now))
    mark_current = current and (mark.get("status") != "research_prerequisites_observed" or bound_current)
    mark_status = reason(mark.get("status", "unavailable")) if mark_current else "stale / unavailable"
    line(f"Mark research: {mark_status}", 1, "yellow")
    train, held = calibration.get("training_events"), calibration.get("heldout_events")
    line(f"{'Terminal' if study_fresh else 'Last terminal'} train/held {_number(train)}/{_number(held)}", 1)
    prefix = "" if study_fresh else "Last "
    line(f"{prefix}Tokens {_number(history.get('tokens_tracked'))} Marks {_number(history.get('current_matured_labels'))}", 1)
    remaining = mark.get("remaining_requirements", qualification.get("insufficient_evidence", []))
    if not study_fresh:
        line("Remaining: fresh study evidence", 1, "yellow")
    elif not quote_current:
        line("Remaining: fresh source quotes", 1, "yellow")
    elif isinstance(remaining, list) and remaining:
        line(f"Remaining: {reason(remaining[0])}", 1, "yellow")
    elif calibration.get("metrics") is None:
        line("Remaining: independent outcomes", 1, "yellow")
    line(f"Markets {_number(_mapping(operation.get('scan')).get('discovered_markets'))} Fresh {_number(connection.get('fresh_books')) if live else '—'}", 2)
    line(f"{prefix}History {_number(history.get('current_observations'))} Matured {_number(history.get('matured_labels'))}", 2)
    line(f"{prefix}Parent groups {_number(history.get('unique_parent_events'))} (unreviewed)", 2)
    eligible = qualification.get("eligible_mark_tokens")
    line(f"Eligible mark tokens {_number(len(eligible) if isinstance(eligible, list) else None)}" + (" (last)" if not current else ""), 2)
    edge = qualification.get("estimated_executable_edge")
    all_quotes_current = isinstance(tokens, list) and bool(tokens) and all(
        isinstance(row, dict) and _p16_recent(row.get("latest_source_at"), now)
        and _p16_recent(row.get("latest_available_at"), now) for row in tokens)
    edge_text = f"{edge:+.4f}/share" if current and all_quotes_current and bound_current and type(edge) in (float, int) and math.isfinite(edge) else "unavailable"
    line(f"Est edge (research) {edge_text}", 2)
    metrics = _mapping(calibration.get("metrics"))
    sufficient = type(train) is int and train >= 100 and type(held) is int and held >= 100
    brier = metrics.get("brier")
    brier_text = f"{brier:.5f}" if study_fresh and sufficient and type(brier) in (float, int) and math.isfinite(brier) and brier >= 0 else "insufficient evidence"
    line(f"Terminal Brier {brier_text}", 2)
    line(f"Orders {_number(experimental.get('orders_submitted'))} Fills {_number(experimental.get('fills'))} Pos {_number(experimental.get('open_positions'))}", 2)
    execution_stage = _mapping(_mapping(experimental.get("operations_research")).get("phase16_execution"))
    line(f"Depth checks veto {_number(execution_stage.get('committed_vetoes'))} pass {_number(execution_stage.get('committed_check_passes'))}", 3)
    relationship = _mapping(study.get("relationships"))
    line(f"Relationship {_number(relationship.get('evaluations', _mapping(relationship.get('engine')).get('evaluations')))} evaluations", 3)
    line(f"Certified gate {reason(cs.get('trading_status', 'unavailable'))}", 2, "yellow")
    line(f"Study {_seen(study.get('last_study_at'))}", 2, "dim")
    if study.get("last_error"):
        line(f"Study error {reason(study['last_error'])}", 1, "yellow")
    for error in tuple(errors)[:2]:
        line(f"API {reason(error)}", 1, "red")
    unsafe = any(v.get("live_trading_enabled") is True or v.get("paper_trading") is False for v in (cs, es))
    safe = all(fresh and _ops_fresh(v.get("timestamp"), now) and v.get("paper_trading") is True
               and v.get("live_trading_enabled") is False for v, fresh in ((cs, cf), (es, ef)))
    footer = "WARNING LIVE CONFIG UNSAFE" if unsafe else "LIVE TRADING DISABLED" if safe else "LIVE CONFIG UNVERIFIED"
    keep = list(range(len(lines)))
    for i in sorted(keep, key=lambda i: (lines[i][2], i), reverse=True):
        if len(keep) <= height - 1:
            break
        keep.remove(i)
    output = Text()
    for i, (text, style) in enumerate([(lines[j][0], lines[j][1]) for j in keep] + [(footer, "red" if unsafe else "dim")]):
        if i:
            output.append("\n")
        row = Text(text, style=style, no_wrap=True, overflow="ellipsis")
        row.truncate(width, overflow="ellipsis")
        output.append_text(row)
    return output


def _archive_sample(archive):
    """Only operational cache samples have their own independent freshness clock."""
    if archive.get("snapshot_only") is not True:
        return ""
    try:
        measured = datetime.fromisoformat(archive["measurement_at"])
        age = (datetime.now(UTC)-measured).total_seconds()
        if measured.tzinfo is None or age < 0 or not math.isfinite(age):
            raise ValueError("invalid archive measurement time")
    except (KeyError, TypeError, ValueError):
        return "sample unavailable"
    if archive.get("measurement_status") == "unavailable":
        return "sample unavailable"
    prefix = "STALE sample" if archive.get("measurement_status") != "cached" or age > 60 else "sample"
    return f"{prefix} {age:.0f}s"


def _render_operations(certified, experimental, width, height, errors):
    """Small read-only snapshots; stale sources never masquerade as live counts."""
    now = datetime.now(UTC)
    c_fresh, e_fresh = (_ops_fresh(account.get("generated_at"), now) for account in (certified, experimental))
    operation = _mapping(certified.get("operation"))
    connection = _mapping(operation.get("connectivity"))
    c_service, e_service = _mapping(operation.get("service")), _mapping(experimental.get("service"))
    services = ((c_service, c_fresh), (e_service, e_fresh))
    source_fresh = (c_fresh and certified.get("mode") == "live_market_paper"
        and _ops_fresh(c_service.get("timestamp"), now) and c_service.get("status") == "ok"
        and _ops_fresh(connection.get("last_message_at"), now) and connection.get("ws_connected") is True)
    lines = []

    def line(value, priority=2, style="white"):
        lines.append((_clean(value), style, priority))

    line("OPERATIONS · PAPER ONLY", 0, "bold cyan")
    line("REAL MARKET DATA" if source_fresh else "DATA STALE / UNAVAILABLE", 0, "cyan" if source_fresh else "yellow")
    markets = _mapping(operation.get("scan")).get("discovered_markets")
    line(f"{'Mkts' if source_fresh else 'Last mkts'} {_number(markets)} Fresh {_number(connection.get('fresh_books')) if source_fresh else '—'} WS {_flag(connection.get('ws_connected'), 'on', 'off') if source_fresh else 'stale'}", 1)
    for label, account, fresh in (("EXPERIMENTAL PAPER", experimental, e_fresh), ("CERTIFIED PAPER", certified, c_fresh)):
        line(label + (" · stale" if account and not fresh else ""), 0, "bold yellow" if label.startswith("EXP") else "bold green")
        activity = (f" O{_number(account.get('orders_submitted'))} F{_number(account.get('fills'))} P{_number(account.get('open_positions'))}"
                    if label.startswith("EXP") and "orders_submitted" in account else "")
        line(f"{'Last ' if account and not fresh else ''}{_number(account.get('cash'), True)} P/L {_number(account.get('simulated_pnl'), True)}{activity}", 0)
        if label.startswith("EXP"):
            health = _clean(e_service.get("status", "unavailable")) if fresh else "stale/unavailable"
            line(f"Stop {_flag(account.get('kill_switch', account.get('suspended')))} · svc {health}", 0, "yellow")
        else:
            line(f"Gate {_clean(c_service.get('trading_status', 'unavailable'))}" + (" · stale" if not fresh else ""), 1, "yellow")
    research = _mapping(experimental.get("operations_research")) or _mapping(certified.get("operations_research"))
    events = _mapping(research.get("phase18"))
    if events:
        line(f"Event forecasts {_number(events.get('independent_research_forecasts'))} (research)", 2)
        line(f"Event train/held {_number(events.get('qualified_training_events'))}/{_number(events.get('qualified_heldout_events'))}", 2)
    readiness = _mapping(research.get("readiness_snapshot"))
    readiness_fresh = _ops_fresh(readiness.get("generated_at"), now)
    assessment = readiness.get("assessment")
    if not readiness_fresh:
        line("Readiness unavailable/stale", 2, "yellow")
    else:
        text = assessment if isinstance(assessment, str) else _mapping(assessment).get("current_blocker", _mapping(assessment).get("status", "review required"))
        line(f"Readiness {_clean(text)}", 2, "yellow")
    for label, account, fresh in (("Col", certified, c_fresh), ("Exp", experimental, e_fresh)):
        archive, capacity = _mapping(account.get("archive")), _mapping(account.get("capacity"))
        sample = _archive_sample(archive)
        if sample:
            line(f"{label} {sample} {_ops_bytes(archive.get('usage_bytes'))}/{_ops_bytes(archive.get('budget_bytes'))}", 1,
                 "yellow" if "STALE" in sample or "unavailable" in sample else "white")
        else:
            line(f"{label} {_ops_bytes(archive.get('usage_bytes'))}/{_ops_bytes(archive.get('budget_bytes'))} {'last' if not fresh else _clean(capacity.get('status', archive.get('health', 'unknown')))}", 1)
        horizon = capacity.get("seconds_to_capacity", archive.get("seconds_to_exhaustion"))
        line(f"{label} +{_ops_bytes(archive.get('growth_bytes_per_second'))}/s full {_ops_horizon(horizon)}", 2, "dim")
        tiers = _mapping(archive.get("tier_usage_bytes"))
        line(f"{label} A/W/C {_ops_bytes(tiers.get('active'))}/{_ops_bytes(tiers.get('warm'))}/{_ops_bytes(tiers.get('cold'))}", 3, "dim")
        archive_tiers = _mapping(archive.get("archive_tiers"))
        verified = archive.get("cold_verified_segments")
        if verified is not None:
            line(f"{label} Cold verified {_number(verified)}", 3, "dim")
        else:
            line(f"{label} Gzip {_number(archive.get('compressed_segments'))} Proofs {_number(archive_tiers.get('cold_proofs_present'))}", 3, "dim")
        alerts = capacity.get("alerts")
        if isinstance(alerts, (list, tuple)):
            for alert in alerts[:1]:
                text = _mapping(alert).get("reason", _mapping(alert).get("code", alert)) if isinstance(alert, dict) else alert
                line(f"{label} alert {_clean(text)}", 1, "yellow")
        if archive.get("last_error"):
            line(f"{label} block {_clean(archive['last_error'])}", 1, "yellow")
    domains = _mapping(research.get("domains"))
    rows = _mapping(domains.get("domains"))
    domain_fresh = e_fresh and _ops_fresh(domains.get("last_frame_at", domains.get("generated_at")), now)
    forecasts = [r.get("independent_forecasts") for r in rows.values() if isinstance(r, dict)]
    forecast_total = sum(forecasts) if forecasts and all(type(x) is int and x >= 0 for x in forecasts) else None
    line(f"Forecasts {_number(forecast_total)}" + (" · research snapshot stale" if not domain_fresh else " · independent"), 2)
    relationships = _mapping(research.get("relationships"))
    engine = _mapping(relationships.get("engine")) or relationships
    rel_fresh = _ops_fresh(relationships.get("last_evaluation_at"), now)
    line(f"SII eval {_number(engine.get('evaluations'))} finds {_number(engine.get('persistent_findings'))}" + (" · stale" if not rel_fresh else ""), 2)
    history = _mapping(research.get("historical_qualification"))
    line(f"Train/test {_number(history.get('qualified_training_events', history.get('qualifying_training_events', history.get('training_events'))))} / {_number(history.get('qualified_heldout_events', history.get('qualifying_heldout_events', history.get('heldout_events'))))}", 2)
    line(f"Outcomes {_number(history.get('chain_corroborated_exact_settlement_groups', history.get('outcomes_verified')))}", 3)
    strategies = readiness.get("strategies")
    if isinstance(strategies, list) and readiness_fresh:
        line(f"Strategies {_number(len(strategies))} · no auto promotion", 3, "dim")
    for name, row in rows.items():
        if isinstance(row, dict) and row.get("monitored_markets"):
            line(f"{name}: M{_number(row.get('monitored_markets'))} F{_number(row.get('independent_forecasts'))}", 3, "dim")
    for error in tuple(errors)[:2]:
        line(f"API {_clean(error)}", 1, "red")
    unsafe = any(service.get("live_trading_enabled") is True or service.get("paper_trading") is False for service, _ in services)
    verified = all(fresh and _ops_fresh(service.get("timestamp"), now) and service.get("live_trading_enabled") is False and service.get("paper_trading") is True for service, fresh in services)
    footer = "WARNING LIVE CONFIG UNSAFE" if unsafe else "LIVE TRADING DISABLED" if verified else "LIVE CONFIG UNVERIFIED"
    keep = list(range(len(lines)))
    for index in sorted(keep, key=lambda i: (lines[i][2], i), reverse=True):
        if len(keep) <= height-1:
            break
        keep.remove(index)
    rendered = Text()
    for index, (value, style) in enumerate([(lines[i][0], lines[i][1]) for i in keep] + [(footer, "red" if unsafe else "dim")]):
        if index:
            rendered.append("\n")
        row = Text(value, style=style, no_wrap=True, overflow="ellipsis")
        row.truncate(width, overflow="ellipsis")
        rendered.append_text(row)
    return rendered


def _render_archives(certified, experimental, width, height, errors):
    import math

    def size(value):
        if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or value < 0:
            return "unknown"
        if value >= 1024**3:
            return f"{value / 1024**3:.2f}GiB"
        if value < 1024**2:
            return f"{value / 1024:.1f}KiB"
        return f"{value / 1024**2:.1f}MiB"

    def horizon(value):
        if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or value < 0:
            return "unknown"
        return f"{value / 3600:.1f}h"

    connection = _mapping(_mapping(certified.get("operation")).get("connectivity"))
    lines = [("REAL MARKET DATA", "bold cyan", 0),
             (f"WS {_flag(connection.get('ws_connected'), 'on', 'off')} Fresh {_number(connection.get('fresh_books'))}", "white", 1)]
    for label, account in [("COLLECTOR ARCHIVE", certified), ("EXPERIMENTAL ARCHIVE", experimental)]:
        archive = _mapping(account.get("archive"))
        rate = archive.get("growth_bytes_per_second")
        sample = _archive_sample(archive)
        lines.extend([
            (label, "bold yellow", 0),
            (f"{sample+' ' if sample else ''}{size(archive.get('usage_bytes'))} / {size(archive.get('budget_bytes'))}", "white", 0),
            (f"State {_clean(archive.get('health', 'unavailable'))}", "yellow", 1),
            (f"Segments {_number(archive.get('segments'))} Sealed {_number(archive.get('sealed_segments'))} Gzip {_number(archive.get('compressed_segments'))}", "white", 2),
            (f"Growth {size(rate)}/s Full in {horizon(archive.get('seconds_to_exhaustion'))}", "dim", 2),
            (f"Free {size(archive.get('free_bytes'))} Floor {size(archive.get('global_floor_bytes'))}", "dim", 2),
        ])
        if archive.get("last_error"):
            lines.append((f"Reason {_clean(archive['last_error'])}", "yellow", 0))
    lines += [
        (f"EXPERIMENTAL PAPER {_number(experimental.get('cash'),True)} P/L {_number(experimental.get('simulated_pnl'),True)}", "white", 0),
        (f"CERTIFIED PAPER {_number(certified.get('cash'),True)} P/L {_number(certified.get('simulated_pnl'),True)}", "white", 0),
        (f"Emergency stop: {_flag(experimental.get('kill_switch', experimental.get('suspended')), 'ACTIVE', 'clear')}", "yellow", 0),
        ("Retention: all originals; no purge", "dim", 2),
    ]
    if errors:
        lines.append((f"API {_clean(errors[0])}", "red", 0))
    keep = list(range(len(lines)))
    for i in sorted(keep, key=lambda i: (lines[i][2], -i), reverse=True):
        if len(keep) <= height - 2:
            break
        keep.remove(i)
    result = Text()
    footer = _safety_footer(certified, experimental)
    if width < 31 and "DISABLED" in footer:
        footer = "LIVE TRADING DISABLED"
    final = [(lines[i][0], lines[i][1]) for i in keep] + [(footer, "dim"), ("Ctrl-C exits monitor only", "dim")]
    for i, (text, style) in enumerate(final):
        if i:
            result.append("\n")
        row = Text(_clean(text), style=style, no_wrap=True, overflow="ellipsis")
        row.truncate(width, overflow="ellipsis")
        result.append_text(row)
    return result


def _render_domains(certified, experimental, width, height, errors):
    domain = _mapping(_mapping(experimental.get("event_intelligence")).get("domains"))
    rows = _mapping(domain.get("domains"))
    operation = _mapping(certified.get("operation"))
    connection = _mapping(operation.get("connectivity"))
    source = domain.get("market_source_status", "unavailable")
    lines = [
        ("REAL MARKET DATA", "bold cyan", 0),
        (f"Markets {_number(domain.get('markets_monitored'))} Fresh {_number(connection.get('fresh_books'))} {_clean(source)}", "white", 1),
        ("MULTI-DOMAIN RESEARCH", "bold yellow", 0),
        ("Domain       Mkt Fcst Pend Done", "dim", 1),
    ]
    names = [('weather','Weather'),('crypto','Crypto'),('finance','Finance'),('economics','Economics'),
             ('politics','Politics'),('sports','Sports'),('esports','Esports'),('technology','Tech/AI'),
             ('science','Science'),('geopolitics','Geopolitics'),('entertainment','Culture'),('other','Other/review')]
    for d,label in names:
        row = _mapping(rows.get(d))
        text=f"{label:<12} {_number(row.get('monitored_markets')):>3} {_number(row.get('independent_forecasts')):>4} {_number(row.get('pending')):>4} {_number(row.get('resolved')):>4}"
        if width>=80:
            text+=' '+_research_text(row.get('capability'))
        lines.append((text,"white",2 if row.get('monitored_markets') else 3))
    reason = domain.get('last_error') or domain.get('status') or 'unavailable'
    if errors:reason='API '+_clean(errors[0])
    lines += [(f"State {_reason_label(reason)}",'yellow',0),
              ('Accuracy unavailable; no qualified cohort','dim',2),
              ('EXPERIMENTAL PAPER','bold yellow',0),
              (f"{_number(experimental.get('cash'),True)} P/L {_number(experimental.get('simulated_pnl'),True)} O{_number(_count(experimental.get('orders')))} F{_number(experimental.get('fills'))}",'white',0),
              ('CERTIFIED PAPER','bold green',0),
              (f"{_number(certified.get('cash'),True)} P/L {_number(certified.get('simulated_pnl'),True)}",'white',0)]
    keep=list(range(len(lines)))
    for i in sorted(keep,key=lambda i:(lines[i][2],-i),reverse=True):
        if len(keep)<=height-2:break
        keep.remove(i)
    output=Text()
    final=[(lines[i][0],lines[i][1]) for i in keep]+[(_safety_footer(certified,experimental),'dim'),('Ctrl-C exits monitor only','dim')]
    for i,(text,style) in enumerate(final):
        if i:output.append('\n')
        row=Text(_clean(text),style=style,no_wrap=True,overflow='ellipsis');row.truncate(width,overflow='ellipsis')
        output.append_text(row)
    return output

def _render_events(certified, experimental, width, height, errors):
    """Outcome forecasting is explicit research, separate from both paper accounts."""
    operation = _mapping(certified.get("operation"))
    live = certified.get("mode") == "live_market_paper"
    exp = experimental.get("account_id") == "experimental-paper"
    event = _mapping(experimental.get("event_intelligence"))
    if isinstance(event.get("sports"), dict):
        return _render_sports_events(certified, experimental, event, width, height, errors)
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



def _render_sports_events(certified, experimental, event, width, height, errors):
    """External forecasts, market comparators and paper capital stay distinct."""
    sports = _mapping(event.get("sports"))
    available = sports.get("status") not in {None, "unavailable", "invalid", "stale"}
    operation = _mapping(certified.get("operation"))
    scores = _mapping(sports.get("scores")) if available else {}
    source = _mapping(sports.get("source_qualification", sports.get("source")))
    ternary = sports.get("ternary_research_forecasts", event.get("independent_model_forecasts")) if available else None
    mapping_failures = sports.get("mapping_failures") if available else None
    if isinstance(mapping_failures, dict):
        mapping_failures = sum(v for k, v in mapping_failures.items() if k.startswith("mapping_") and isinstance(v, int))
    versions = sorted({str(_mapping(row).get("model_version")) for row in sports.get("model_versions", [])
                       if isinstance(row, dict)})
    model_version = sports.get("model_version") or (versions[0] if versions else None)
    rejection = sports.get("last_rejection") or sports.get("last_error")
    reasons = _mapping(sports.get("rejections"))
    if not rejection and reasons:
        rejection = max(reasons, key=lambda k: _finite_count(reasons[k]))
    history = _mapping(event.get("historical_qualification"))
    resolution = _mapping(event.get("resolution_collection"))

    def count(key):
        return _number(event.get(key) if available else None)

    def number(key):
        return _number(sports.get(key) if available else None)

    # Priority 0 preserves identities and account balances on tiny terminals.
    rows = [
        ("REAL MARKET DATA", "bold cyan", 0),
        (f"Markets {_number(_mapping(operation.get('scan')).get('discovered_markets'))} WS {_flag(_mapping(operation.get('connectivity')).get('ws_connected'), 'up', 'down')}", "white", 2),
        ("RESEARCH FORECAST", "bold yellow", 0),
        (f"Upcoming {_number(sports.get('upcoming_mapped_events_last_frame', sports.get('upcoming_eligible_events')) if available else None)} Map rej {_number(mapping_failures)}", "white", 1),
        (f"Independent {_number(ternary)} Baseline {count('market_baseline_forecasts')}", "white", 0),
        (f"WTL pending {_number(sports.get('ternary_pending') if available else None)} done {_number(sports.get('ternary_resolved') if available else None)}", "white", 1),
        (f"Independent groups {count('independent_event_groups')}", "dim", 2),
        (f"Model {_research_text(model_version if available else None)}", "dim", 2),
        (f"Source {_research_text(sports.get('source_status') or source.get('license') or 'unavailable')}", "dim", 1),
        (f"Data as of {_seen(sports.get('last_source_success', sports.get('last_refresh_at')))}", "dim", 3),
        (f"Block {_reason_label(rejection or 'insufficient_independent_evidence')}", "yellow", 1),
        (f"Brier {_event_metric(scores.get('brier'))} n={_number(scores.get('count'))}", "white", 2),
        (f"Market Brier {_event_metric(scores.get('market_brier'))}", "dim", 2),
        (f"Log loss {_event_metric(scores.get('log_loss'))}", "white", 3),
        (f"Cal {_research_text(sports.get('calibration_status'))}", "dim", 2),
        (f"Settlement {_number(resolution.get('verified'))}/{_number(resolution.get('attempts'))}", "dim", 3),
        (f"History {_number(history.get('chain_corroborated_exact_settlement_groups'))} Train/test {_number(history.get('qualified_training_events'))}/{_number(history.get('qualified_heldout_events'))}", "dim", 3),
        (f"SII {_number(_mapping(sports.get('relationships')).get('descriptive_findings'))} descriptive only", "dim", 3),
        ("EXPERIMENTAL PAPER", "bold yellow", 0),
        (f"{_number(experimental.get('cash'), True)} P/L {_number(experimental.get('simulated_pnl'), True)}", "white", 0),
        (f"Orders {_number(_count(experimental.get('orders')))} Fills {_number(experimental.get('fills'))}", "white", 2),
        ("Models research-only; admission blocked", "yellow", 0),
        ("CERTIFIED PAPER", "bold green", 0),
        (f"{_number(certified.get('cash'), True)} P/L {_number(certified.get('simulated_pnl'), True)}", "white", 0),
        (f"Gate {_research_text(_mapping(operation.get('service')).get('trading_status'))}", "dim", 1),
    ]
    if errors:
        rows[10] = ("API " + _clean(errors[0]), "yellow", 1)
    keep = list(range(len(rows)))
    for index in sorted(range(len(rows)), key=lambda i: (rows[i][2], -i), reverse=True):
        if len(keep) <= height - 2:
            break
        keep.remove(index)
    final = [(rows[i][0], rows[i][1]) for i in keep] + [
        (_safety_footer(certified, experimental), "dim"), ("Ctrl-C exits monitor only", "dim")
    ]
    rendered = Text()
    for index, (value, style) in enumerate(final):
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
    if view in {"operations", "readiness", "edge", "challengers"}:
        def operations_url(value):
            parsed = urlsplit(value)
            return urlunsplit((parsed.scheme, parsed.netloc, "/api/operations-state", "", ""))
        certified_url, experimental_url = operations_url(certified_url), operations_url(experimental_url)
    elif view == "archives":
        certified_url = certified_url.removesuffix("/api/state") + "/api/archive-state" if certified_url.endswith("/api/state") else certified_url
        experimental_url = experimental_url.removesuffix("/api/state") + "/api/archive-state" if experimental_url.endswith("/api/state") else experimental_url
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


def _render_edge(certified, experimental, width, height, errors):
    """Small empirical research viewport; counter and uncertainty scopes stay explicit."""
    now = datetime.now(UTC)
    op = _mapping(certified.get("operation"))
    con = _mapping(op.get("connectivity"))
    report = _mapping(_mapping(experimental.get("operations_research")).get("phase17"))
    current = (_ops_fresh(experimental.get("generated_at"), now)
        and _p16_recent(report.get("last_evaluation_at"), now, seconds=90)
        and _mapping(experimental.get("service")).get("status") == "ok"
        and report.get("status") == "research_only" and not report.get("runtime_error")
        and not report.get("last_error"))
    live = (_ops_fresh(certified.get("generated_at"), now) and con.get("ws_connected") is True
        and _p16_recent(con.get("last_message_at"), now) and certified.get("mode") == "live_market_paper")
    rows = [("EMPIRICAL EDGE RESEARCH", "bold cyan", 1),
        ("REAL MARKET DATA" if live else "SOURCE STALE / UNAVAILABLE", "cyan" if live else "yellow", 0),
        ("EXPERIMENTAL PAPER", "bold yellow", 0),
        (f"{_number(experimental.get('cash'), True)} P/L {_number(experimental.get('simulated_pnl'), True)}", "white", 0),
        (f"Stop {_flag(experimental.get('kill_switch'))}", "yellow", 0),
        ("CERTIFIED PAPER", "bold green", 0),
        (f"{_number(certified.get('cash'), True)} Gate {_clean(_mapping(op.get('service')).get('trading_status', 'unknown'))}", "white", 0),
        ("Research prospective" if current else "Research stale / warming / unavailable", "cyan" if current else "yellow", 1),
        (f"Forecast points {_number(report.get('forecast_points'))} Pending {_number(report.get('pending_points'))}", "white", 1),
        (f"Matured marks {_number(report.get('matured_points'))}", "white", 1),
        (f"Parent groups {_number(report.get('unreviewed_parent_groups'))} (unreviewed)", "white", 1),
        ("CI / calibration insufficient evidence", "yellow", 0),
        ("Research models have NO order authority", "yellow", 0)]
    models = _mapping(report.get("models"))
    for name, model in list(models.items())[:4]:
        model = _mapping(model)
        score = model.get("mae") if current else None
        value = f"{score:.5f}" if type(score) in (float, int) and math.isfinite(score) else "unavailable"
        rows.append((f"{_clean(name)} MAE {value}", "white", 2))
    rows.extend([(f"Last {_seen(report.get('last_evaluation_at'))}", "dim", 2),
                 ("Marks are not event outcomes or P/L", "yellow", 1)])
    if errors:
        rows.append(("API " + _clean(errors[0]), "yellow", 1))
    keep = list(range(len(rows)))
    for i in sorted(range(len(rows)), key=lambda j: (rows[j][2], j), reverse=True):
        if len(keep) <= height-1:
            break
        if rows[i][2]:
            keep.remove(i)
    rendered = Text()
    services = (_mapping(op.get("service")), _mapping(experimental.get("service")))
    unsafe = any(s.get("live_trading_enabled") is True or s.get("paper_trading") is False for s in services)
    verified = all(s.get("live_trading_enabled") is False and s.get("paper_trading") is True for s in services)
    safety = "WARNING LIVE CONFIG UNSAFE" if unsafe else "LIVE TRADING DISABLED" if verified else "LIVE CONFIG UNVERIFIED"
    chosen = [(rows[i][0], rows[i][1]) for i in keep] + [(safety, "dim")]
    for i, (value, style) in enumerate(chosen):
        if i:
            rendered.append("\n")
        row = Text(_clean(value), style=style, no_wrap=True, overflow="ellipsis")
        row.truncate(width, overflow="ellipsis")
        rendered.append_text(row)
    return rendered


def _render_event_edge(certified, experimental, width, height, errors):
    """Event outcomes take priority over legacy mark-prediction comparisons."""
    now=datetime.now(UTC);op=_mapping(certified.get('operation'));cs=_mapping(op.get('service'))
    es=_mapping(experimental.get('service'));con=_mapping(op.get('connectivity'))
    r=_mapping(_mapping(experimental.get('operations_research')).get('phase18'))
    fresh=(_ops_fresh(experimental.get('generated_at'),now) and es.get('status')=='ok'
        and r.get('status')=='research_only' and _p16_recent(r.get('last_evaluation_at'),now,seconds=360)
        and not r.get('runtime_error') and not r.get('last_error'))
    live=(_ops_fresh(certified.get('generated_at'),now) and cs.get('status')=='ok'
        and con.get('ws_connected') is True and _p16_recent(con.get('last_message_at'),now))
    latest=_mapping(r.get('latest'));approaches=_mapping(r.get('approaches'));domains=_mapping(r.get('forecasts_by_domain'))
    rows=[('EVENT PROBABILITY RESEARCH','bold cyan',1),
        ('REAL MARKET DATA' if live else 'SOURCE STALE / UNAVAILABLE','cyan' if live else 'yellow',0),
        ('EXPERIMENTAL PAPER','bold yellow',0),
        (f"Equity {_number(experimental.get('bankroll',experimental.get('cash')),True)} P/L {_number(experimental.get('simulated_pnl'),True)}",'white',0),
        (f"Stop {_flag(experimental.get('kill_switch'))}",'yellow',0),
        ('CERTIFIED PAPER','bold green',0),
        (f"Equity {_number(certified.get('bankroll',certified.get('cash')),True)}",'white',0),
        ('Event source current' if fresh else 'Event source stale / unavailable','cyan' if fresh else 'yellow',1),
        (f"Crypto {_number(domains.get('crypto'))} Pending {_number(r.get('pending_forecasts'))}",'white',1),
        ('Weather/econ qualified inputs required','yellow',2),
        (f"Resolved {_number(r.get('durable_outcome_records'))} (proof required)",'white',2),
        (f"Train/held {_number(r.get('qualified_training_events'))}/{_number(r.get('qualified_heldout_events'))} needs100/100",'white',1),
        ('Uncalibrated; uncertainty [0,1]','yellow',1),
        ('Net edge unavailable / no admission','yellow',1),
        ('Research models NO order authority','yellow',0)]
    paired = _mapping(_mapping(experimental.get("operations_research")).get("phase20"))
    if paired and paired.get("status") != "disabled":
        pair_current = fresh and not paired.get("runtime_error") and not paired.get("last_error")
        rows.extend([
            (f"SII A/B pairs {_number(paired.get('paired'))} withheld {_number(paired.get('withheld'))}", "white", 1),
            ("SII challenger unavailable" if pair_current else "SII A/B state unavailable / stale", "yellow", 1),
            ("SII improvement unmeasured; no authority", "yellow", 1),
        ])
    for name,label in [('high_throughput','Throughput'),('high_conviction','Conviction')]:
        row=_mapping(approaches.get(name))
        rows.append((f"{label} E{_number(row.get('evaluated'))} Q{_number(row.get('qualified'))} R{_number(row.get('rejected'))}",'white',1))
    for label,value in [('Col',certified),('Exp',experimental)]:
        archive=_mapping(value.get('archive'))
        sample = _archive_sample(archive)
        rows.append((f"{label} {sample+' ' if sample else ''}{_ops_bytes(archive.get('usage_bytes'))}/{_ops_bytes(archive.get('budget_bytes'))}",'dim',2))
    rows.append((f"Last {_seen(r.get('last_evaluation_at'))}",'dim',2))
    if latest.get('model_version'):rows.append((_clean(latest['model_version']),'dim',3))
    if errors:rows.append(('API '+_clean(errors[0]),'yellow',1))
    keep=list(range(len(rows)))
    for i in sorted(keep,key=lambda j:(rows[j][2],j),reverse=True):
        if len(keep)<=height-1:break
        if rows[i][2]:keep.remove(i)
    unsafe=any(s.get('live_trading_enabled') is True or s.get('paper_trading') is False for s in (cs,es))
    verified=all(s.get('live_trading_enabled') is False and s.get('paper_trading') is True for s in (cs,es))
    safety='WARNING LIVE CONFIG UNSAFE' if unsafe else 'LIVE TRADING DISABLED' if verified else 'LIVE CONFIG UNVERIFIED'
    rendered=Text()
    for i,(value,style) in enumerate([(rows[j][0],rows[j][1]) for j in keep]+[(safety,'dim')]):
        if i:rendered.append('\n')
        line=Text(_clean(value),style=style,no_wrap=True,overflow='ellipsis');line.truncate(width,overflow='ellipsis');rendered.append_text(line)
    return rendered


def _render_challengers(certified, experimental, width, height, errors):
    from datetime import UTC, datetime

    now = datetime.now(UTC)
    research = _mapping(_mapping(experimental.get("operations_research")).get("phase23"))
    domain = _mapping(_mapping(experimental.get("operations_research")).get("phase24"))
    if domain.get("status") != "disabled" and domain:
        return _render_domain_challengers(certified, experimental, research, domain, width, height, errors)
    current = (research.get("status") == "research_only" and not research.get("runtime_error")
               and _ops_fresh(experimental.get("generated_at"), now)
               and _p16_recent(research.get("last_evaluation_at"), now, seconds=360))
    rows = [("RESEARCH MODEL COMPETITION", "bold cyan"),
            ("NO TRADING AUTHORITY", "yellow")]
    if current:
        rows.append((f"Forecasts {_number(research.get('forecasts'))} Pending {_number(research.get('pending_forecasts'))}", "white"))
        rows.append((f"Parents {_number(research.get('unreviewed_parent_events'))} unreviewed", "white"))
        for name, model in _mapping(research.get("models")).items():
            row = _mapping(model)
            rows.append((f"{_clean(name)} F{_number(row.get('forecasts'))} V{_number(row.get('resolved'))}", "white"))
        rows.append(("Scores: insufficient evidence", "yellow"))
    else:
        rows.append(("Research unavailable / stale", "yellow"))
    rows.append((f"Exp {_number(experimental.get('bankroll'), money=True)} Cert {_number(certified.get('cash'), money=True)}", "white"))
    rows.append(("LIVE TRADING DISABLED" if all(_mapping(s.get('service', s.get('operation', {}).get('service', {}))).get('live_trading_enabled') is False
                 for s in [experimental, certified]) else "LIVE CONFIG UNVERIFIED", "dim"))
    if errors:
        rows.insert(2, ("API "+_clean(errors[0]), "yellow"))
    text = Text()
    for index, (label, style) in enumerate(rows[:height]):
        if index:
            text.append("\n")
        line = Text(label, style=style, no_wrap=True, overflow="ellipsis")
        line.truncate(width, overflow="ellipsis")
        text.append_text(line)
    return text


def _render_domain_challengers(certified, experimental, legacy, domain, width, height, errors):
    from datetime import UTC, datetime

    now = datetime.now(UTC)
    fresh = (domain.get("status") == "research_only" and not domain.get("runtime_error")
             and _ops_fresh(experimental.get("generated_at"), now)
             and _p16_recent(domain.get("last_evaluation_at"), now, seconds=360))
    rows = [("RESEARCH MODEL REGISTRIES", "bold cyan"), ("NO TRADING AUTHORITY", "yellow")]
    if fresh:
        rows += [(f"P23 {_number(legacy.get('forecasts'))} P24 {_number(domain.get('forecasts'))} forecasts", "white"),
                 ("Registry totals; legacy separate", "dim"),
                 (f"P24 parents {_number(domain.get('native_parents'))} unreviewed", "white")]
        models = [("24", name, _mapping(row)) for name, row in _mapping(domain.get("models")).items()]
        models += [("23", name, _mapping(row)) for name, row in _mapping(legacy.get("models")).items()]
        models.sort(key=lambda x: (not bool(x[2].get('forecasts')), x[0] != '24', x[1]))
        maximum = max(0, height-len(rows)-5)
        for phase, name, row in models[:maximum]:
            rows.append((f"{phase} F{_number(row.get('forecasts'))} V{_number(row.get('resolved'))} {_clean(name)}", "white"))
        if len(models)>maximum:
            rows.append((f"+{len(models)-maximum} models: domain-leaderboard", "dim"))
    else:
        rows.append(("Domain research unavailable / stale", "yellow"))
    rows += [("Scores: unvalidated / incomparable", "yellow"),
             (f"Exp {_number(experimental.get('bankroll'), money=True)} Cert {_number(certified.get('cash'), money=True)}", "white")]
    services = [_mapping(experimental.get('service')), _mapping(_mapping(certified.get('operation')).get('service'))]
    safe = all(s.get('paper_trading') is True and s.get('live_trading_enabled') is False for s in services)
    rows.append(("LIVE TRADING DISABLED" if safe else "LIVE CONFIG UNVERIFIED", "dim"))
    if errors:
        rows.insert(2,("API "+_clean(errors[0]),"yellow"))
    text=Text()
    for index,(label,style) in enumerate(rows[:height]):
        if index:text.append("\n")
        line=Text(label,style=style,no_wrap=True,overflow="ellipsis");line.truncate(width,overflow="ellipsis");text.append_text(line)
    return text
