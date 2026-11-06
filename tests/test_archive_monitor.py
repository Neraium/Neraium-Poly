"""Controlled archive presentation inputs, never production storage measurements."""

import re
from io import StringIO

import pytest
from neraium_poly.ops.monitor import render_monitor
from rich.console import Console


def archive_sample():
    archive = {
        "managed": True,
        "usage_bytes": 1024**3,
        "budget_bytes": 64 * 1024**3,
        "active_bytes": 4 * 1024**2,
        "segment_bytes": 16 * 1024**2,
        "segments": 7,
        "sealed_segments": 6,
        "compressed_segments": 5,
        "legacy_records": 100,
        "records": 250,
        "free_bytes": 400 * 1024**3,
        "growth_bytes_per_second": 65536.0,
        "remaining_bytes": 63 * 1024**3,
        "seconds_to_exhaustion": 1032192.0,
        "global_floor_bytes": 8 * 1024**3,
        "retention_policy": "retain_originals",
        "health": "ok",
        "last_error": None,
    }
    certified = {
        "mode": "live_market_paper",
        "cash": 500.0,
        "simulated_pnl": 0.0,
        "archive": archive,
        "operation": {
            "fresh_books": 300,
            "connectivity": {"ws_connected": True, "fresh_books": 300},
            "service": {"status": "ok"},
        },
    }
    experimental = {
        "account_id": "experimental-paper",
        "cash": 500.0,
        "simulated_pnl": 0.0,
        "suspended": True,
        "kill_switch": True,
        "archive": {**archive, "budget_bytes": 16 * 1024**3},
    }
    return certified, experimental


def render(c=None, e=None, *, width=40, height=24):
    out = StringIO()
    console = Console(file=out, width=width, color_system=None)
    console.print(render_monitor(c, e, width=width, height=height, view="archives"))
    return out.getvalue()


@pytest.mark.parametrize("width,height", [(30, 12), (34, 24), (40, 24), (80, 40)])
def test_archive_view_preserves_phone_limits_accounts_and_stop(width, height):
    c, e = archive_sample()
    value = render(c, e, width=width, height=height)
    assert len(value.splitlines()) <= height
    assert all(len(line) <= width for line in value.splitlines())
    assert "EXPERIMENTAL PAPER" in value and "CERTIFIED PAPER" in value
    assert "LIVE FINANCIAL TRADING DISABLED" in value or "LIVE TRADING DISABLED" in value
    assert "ACTIVE" in value
    if height >= 24:
        assert "COLLECTOR ARCHIVE" in value and "EXPERIMENTAL ARCHIVE" in value
        assert value.count("$500.00") == 2


def test_unknown_archive_does_not_fabricate_usage_or_exhaustion():
    value = render()
    assert "COLLECTOR ARCHIVE" in value and "EXPERIMENTAL ARCHIVE" in value
    assert "$0.00" not in value and "0B/s" not in value
    assert "unavailable" in value.lower() or "unknown" in value.lower() or "—" in value
    assert "LIVE FINANCIAL TRADING DISABLED" in value


def test_unknown_growth_does_not_claim_infinite_retention():
    c, e = archive_sample()
    for state in (c, e):
        state["archive"] = {
            **state["archive"],
            "growth_bytes_per_second": None,
            "seconds_to_exhaustion": None,
        }
    value = render(c, e, width=80, height=40).lower()
    assert "infinite" not in value and re.search(r"\bnan\b", value) is None
    assert "unknown" in value or "unavailable" in value or "—" in value


def test_archive_fault_and_terminal_controls_are_not_hidden():
    c, e = archive_sample()
    c["archive"] = {
        **c["archive"],
        "health": "blocked",
        "last_error": "archive_budget_exhausted\x1b[2J",
    }
    value = render(c, e, width=80, height=40)
    assert "archive_budget_exhausted" in value
    assert "\x1b" not in value
    assert "ACTIVE" in value
