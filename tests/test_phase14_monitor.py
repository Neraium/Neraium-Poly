"""Controlled narrow rendering, never measured operational values."""

from io import StringIO

from neraium_poly.ops.monitor import render_monitor
from rich.console import Console
from test_monitor import event_sample


def test_domain_view_fits_phone_and_preserves_account_semantics():
    c, e = event_sample()
    e["event_intelligence"]["domains"] = {
        "status": "storage_blocked",
        "last_error": "domain_durable_storage_below_8GiB_floor",
        "markets_monitored": 200,
        "market_source_status": "degraded_cached_universe",
        "domains": {
            "weather": {"monitored_markets": 1, "independent_forecasts": 0, "pending": 0, "resolved": 0},
            "sports": {"monitored_markets": 6, "independent_forecasts": 2, "pending": 2, "resolved": 0},
        },
    }
    for width, height in [(34, 24), (40, 24), (45, 24), (34, 12)]:
        out = StringIO()
        console = Console(file=out, width=width, color_system=None)
        console.print(render_monitor(c, e, width=width, height=height, view="domains"))
        value = out.getvalue()
        assert len(value.splitlines()) <= height and all(len(row) <= width for row in value.splitlines())
        assert "REAL MARKET DATA" in value and "MULTI-DOMAIN RESEARCH" in value
        assert "CERTIFIED PAPER" in value and "EXPERIMENTAL PAPER" in value
        assert "LIVE FINANCIAL TRADING DISABLED" in value
        if height == 24:
            assert "Sports" in value and "Weather" in value


def test_missing_domain_report_does_not_invent_zero_forecasts():
    out = StringIO()
    console = Console(file=out, width=40, color_system=None)
    console.print(render_monitor(width=40, height=24, view="domains"))
    assert "Markets —" in out.getvalue()
    assert "Accuracy unavailable" in out.getvalue()
