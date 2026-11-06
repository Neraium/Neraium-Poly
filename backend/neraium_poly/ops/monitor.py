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


def render_monitor(certified=None, experimental=None, *, width=40, height=24, errors=()):
    """Fit every critical account label within a phone's actual terminal height.

    The viewport is bounded before Rich Live renders it, preserving safety/status
    rows that would otherwise scroll offscreen. Larger terminals show more
    strategy/rejection/activity details. Numbers are never synthesized for gaps.
    """
    width, height = max(30, min(int(width), 160)), max(12, min(int(height or 24), 100))
    certified, experimental = _mapping(certified), _mapping(experimental)
    operation = _mapping(certified.get("operation"))
    connection = _mapping(operation.get("connectivity"))
    live = certified.get("mode") == "live_market_paper"
    core = []

    def line(text, style="white", priority=1):
        core.append((str(text), style, priority))

    line("REAL MARKET DATA", "bold cyan", 0)
    if live:
        line(
            f"Markets {_number(_mapping(operation.get('scan')).get('discovered_markets'))} Fresh {_number(operation.get('fresh_books'))} Books {_number(operation.get('current_books'))}"
        )
        line(
            f"WS {_flag(connection.get('ws_connected'), 'connected', 'disconnected')} Health {_clean(_mapping(operation.get('service')).get('status', 'unknown'))}"
        )
        intelligence = _mapping(_mapping(experimental.get("strategy_engine")).get("intelligence"))
        line(
            f"Relationships {_number(_count(certified.get('relationships')))} ExpEval {_number(intelligence.get('evaluations'))}",
            priority=2,
        )
        line(
            f"Msg {_number(connection.get('messages'))}  G/R {_number(connection.get('gaps'))}/{_number(connection.get('reconnects'))}",
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

    # At tiny heights keep account labels, bankroll, gate and stop information;
    # omit lower priority telemetry first. Normal 24-row phones keep all core rows.
    footer = [("LIVE FINANCIAL TRADING DISABLED", "dim", 0), ("Ctrl-C exits monitor only", "dim", 2)]
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
        details.append(("STRATEGIES / REJECTIONS", "bold", 0))
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
        details.append((f"Rej {_number(reasons[reason])} {_clean(reason).replace('_', ' ')}", "dim", 1))
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
    rendered = Text()
    for index, (value, style, _) in enumerate(core + details + footer):
        text = Text(_clean(value), style=style, no_wrap=True, overflow="ellipsis")
        text.truncate(width, overflow="ellipsis")
        if index:
            rendered.append("\n")
        rendered.append_text(text)
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
                render_monitor(c, e, width=console.width, height=max(12, console.height - 1), errors=errors)
            )
            return
        with Live(console=console, auto_refresh=False, screen=False, vertical_overflow="crop") as live:
            while True:
                c, e, errors = await fetch_views(certified_url, experimental_url)
                live.update(
                    render_monitor(
                        c, e, width=console.width, height=max(12, console.height - 1), errors=errors
                    ),
                    refresh=True,
                )
                await asyncio.sleep(refresh)

    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        console.print("Monitor stopped; paper services continue.", style="dim")
