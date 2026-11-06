"""Compact loopback-only SSH monitor. Missing services stay unknown, never zero."""

import asyncio

import httpx
from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.text import Text

from neraium_poly.experimental.feed import loopback_url


def _clean(value):
    return "".join(c for c in str(value) if ord(c) >= 32)[:180]


def _number(value, money=False):
    if value is None:
        return "—"
    try:
        return f"${float(value):.2f}" if money else f"{int(value):,}"
    except (ValueError, TypeError, OverflowError):
        return "unknown"


def render_monitor(certified=None, experimental=None, *, width=40, errors=()):
    """Render observed values only; safe at 34 columns with restrained colors."""
    width = max(30, min(width, 160))
    certified = certified or {}
    experimental = experimental or {}
    operation = certified.get("operation", {})
    connection = operation.get("connectivity", {})
    live = certified.get("mode") == "live_market_paper"
    data = Text()
    if live:
        data.append("REAL MARKET DATA\n", style="bold cyan")
        data.append(f"Markets {_number(operation.get('scan', {}).get('discovered_markets'))}  ")
        data.append(f"Fresh {_number(operation.get('fresh_books'))}\n")
        data.append(f"WS {'connected' if connection.get('ws_connected') else 'disconnected / REST'}\n")
        data.append(f"Native messages {_number(connection.get('messages'))}\n")
        data.append(
            f"Gaps {_number(connection.get('gaps'))} / reconnects {_number(connection.get('reconnects'))}\n"
        )
        data.append(
            f"Relationships {_number(len(certified['relationships']) if 'relationships' in certified else None)}\n"
        )
        data.append(f"Observed {_clean(certified.get('generated_at', 'unknown'))}")
    else:
        data.append("REAL MARKET DATA\n", style="bold cyan")
        data.append("No verified live feed available", style="yellow")
    panels = [Panel(data, border_style="dim", width=width)]
    e = Text("EXPERIMENTAL PAPER TRADING\n", style="bold yellow")
    if experimental.get("account_id") == "experimental-paper":
        e.append("UNVALIDATED · simulated only\n", style="yellow")
        e.append(
            f"Cash {_number(experimental.get('cash'), True)}  P/L {_number(experimental.get('simulated_pnl'), True)}\n",
            style="white",
        )
        e.append(
            f"Exposure {_number(experimental.get('exposure'), True)} / $100 initial cap\n", style="white"
        )
        e.append(f"Reserved {_number(experimental.get('reserved'), True)}\n", style="white")
        positions = experimental.get("positions")
        orders = experimental.get("orders")
        e.append(
            f"Positions {_number(len(positions) if isinstance(positions, list) else positions)}  ",
            style="white",
        )
        e.append(f"Orders {_number(len(orders) if isinstance(orders, list) else orders)}\n", style="white")
        e.append(f"Fills {_number(experimental.get('fills'))}  ", style="white")
        e.append(f"Opportunities {_number(experimental.get('qualified_opportunities'))}\n", style="white")
        e.append(
            f"Emergency stop: {'ACTIVE' if experimental.get('suspended') else 'clear'}\n",
            style="red" if experimental.get("suspended") else "white",
        )
        e.append(f"Health {_clean(experimental.get('service', {}).get('status', 'unknown'))}", style="white")
    else:
        e.append("Account unavailable; values unknown", style="white")
    panels.append(Panel(e, border_style="dim", width=width))
    c = Text("CERTIFIED PAPER TRADING\n", style="bold green")
    if live:
        c.append(
            f"Cash {_number(certified.get('cash'), True)}  P/L {_number(certified.get('simulated_pnl'), True)}\n",
            style="white",
        )
        c.append(f"Exposure {_number(certified.get('exposure'), True)}\n", style="white")
        c.append(
            f"Gate: {_clean(operation.get('service', {}).get('trading_status', 'unknown'))}\n", style="white"
        )
        c.append(
            f"Owner approval: {'active' if operation.get('validation', {}).get('active') else 'withheld'}\n",
            style="white",
        )
        coverage = certified.get("research", {}).get("coverage", {})
        c.append(
            f"Independent train/test: {_number(coverage.get('train_events'))}/{_number(coverage.get('heldout_events'))}\n",
            style="white",
        )
        c.append(f"Emergency stop: {'ACTIVE' if certified.get('suspended') else 'clear'}", style="white")
    else:
        c.append("Account unavailable; values unknown", style="white")
    panels.append(Panel(c, border_style="dim", width=width))
    detail = Text("STRATEGIES / REJECTIONS\n", style="bold")
    rows = experimental.get("strategies", [])
    if isinstance(rows, dict):
        rows = [{"strategy_id": k, **(v if isinstance(v, dict) else {})} for k, v in rows.items()]
    if not rows:
        detail.append("No strategy observations yet.\n", style="white")
    for row in rows[:6]:
        if not isinstance(row, dict):
            continue
        name = row.get("strategy_id", row.get("id", "unknown"))
        detail.append(f"{_clean(name)}\n", style="cyan")
        detail.append(
            f"  {'suspended' if row.get('suspended') else 'research'} · P/L {_number(row.get('simulated_realized_pnl', row.get('realized_pnl')), True)}\n",
            style="white",
        )
    reasons = experimental.get("rejection_reasons", {})
    for name, count in sorted(reasons.items(), key=lambda x: x[1], reverse=True)[:3]:
        detail.append(f"{_clean(name)}: {_number(count)}\n", style="dim")
    activity = experimental.get("latest_activity", [])
    if activity:
        detail.append("LATEST ACTIVITY\n", style="bold")
        for row in activity[-3:]:
            detail.append(_clean(row) + "\n", style="white")
    panels.append(Panel(detail, border_style="dim", width=width))
    footer = Text("LIVE FINANCIAL TRADING DISABLED\nCtrl-C exits monitor only", style="dim")
    for error in errors:
        footer.append("\n" + _clean(error), style="yellow")
    return Group(*panels, footer)


async def fetch_views(certified_url, experimental_url):
    async with httpx.AsyncClient(timeout=5, follow_redirects=False) as client:

        async def read(url):
            try:
                response = await client.get(loopback_url(url))
                response.raise_for_status()
                if len(response.content) > 8 * 1024 * 1024:
                    raise ValueError("state budget exceeded")
                return response.json(), None
            except (httpx.HTTPError, ValueError) as error:
                return None, f"{url}: {type(error).__name__}"

        pairs = await asyncio.gather(read(certified_url), read(experimental_url))
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
            console.print(render_monitor(c, e, width=console.width, errors=errors))
            return
        with Live(console=console, auto_refresh=False, screen=False) as live:
            while True:
                c, e, errors = await fetch_views(certified_url, experimental_url)
                live.update(render_monitor(c, e, width=console.width, errors=errors), refresh=True)
                await asyncio.sleep(refresh)

    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        console.print("Monitor stopped; paper services continue.", style="dim")
