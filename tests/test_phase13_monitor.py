"""Controlled rendering values, never genuine forecasting results."""
from io import StringIO

from neraium_poly.ops.monitor import render_monitor
from rich.console import Console
from test_monitor import event_sample


def render(width=38, height=24, *, status="ready"):
    c, e = event_sample()
    ledger = e["event_intelligence"].pop("ledger")
    e["event_intelligence"].update(ledger)
    e["event_intelligence"].update({
        "market_baseline_forecasts": 24, "independent_model_forecasts": 0,
        "sports": {"status": status, "upcoming_eligible_events": 2, "mapping_failures": 4,
                   "model_version": "external-elo-v1", "source_status": "qualified",
                   "last_rejection": "insufficient_team_history"},
    })
    stream = StringIO()
    console = Console(file=stream, width=width, height=height, color_system=None)
    console.print(render_monitor(c, e, width=width, height=height, view="events"))
    return stream.getvalue()


def test_sports_view_phone_keeps_distinctions_and_null_scores():
    for width in (34, 38, 45):
        out = render(width)
        assert len(out.splitlines()) <= 24
        assert all(len(row) <= width for row in out.splitlines())
        for label in ("REAL MARKET DATA", "RESEARCH FORECAST", "EXPERIMENTAL PAPER", "CERTIFIED PAPER"):
            assert label in out
        assert "Independent 0 Baseline 24" in out
        assert "Brier unavailable" in out
        assert "research-only" in out
        assert "Upcoming 2 Map fail 4" in out


def test_sports_unavailable_never_invents_observations():
    out = render(status="unavailable")
    assert "Independent — Baseline —" in out
    assert "Brier unavailable" in out


def test_tiny_sports_view_preserves_accounts_and_safety():
    out = render(34, 12)
    assert len(out.splitlines()) <= 12
    assert "CERTIFIED PAPER" in out and "EXPERIMENTAL PAPER" in out
    assert "research-only" in out
    assert "LIVE FINANCIAL TRADING DISABLED" in out
