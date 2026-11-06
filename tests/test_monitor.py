"""Terminal rendering uses explicitly controlled presentation inputs."""

from neraium_poly.ops.monitor import render_monitor
from rich.console import Console


def rendered(c=None, e=None, width=38):
    console = Console(width=width, record=True, no_color=True)
    console.print(render_monitor(c, e, width=width))
    return console.export_text()


def test_unavailable_values_are_not_synthetic_live_zeros():
    output = rendered()
    assert "No verified live feed available" in output
    assert "unknown" in output and "$0.00" not in output


def test_phone_layout_labels_accounts_and_unvalidated_results():
    c = {
        "mode": "live_market_paper",
        "generated_at": "controlled test",
        "cash": 500,
        "simulated_pnl": 0,
        "exposure": 0,
        "suspended": False,
        "relationships": [],
        "operation": {
            "scan": {"discovered_markets": 200},
            "fresh_books": 284,
            "connectivity": {"ws_connected": True, "messages": 42, "gaps": 2, "reconnects": 0},
            "validation": {"active": False},
            "service": {"trading_status": "validation_blocked"},
        },
        "research": {"coverage": {"train_events": 0, "heldout_events": 0}},
    }
    e = {
        "account_id": "experimental-paper",
        "cash": 499,
        "simulated_pnl": -1,
        "exposure": 4,
        "reserved": 0,
        "positions": [],
        "orders": [],
        "fills": 0,
        "qualified_opportunities": 0,
        "suspended": True,
        "service": {"status": "ok"},
        "strategies": [],
        "rejection_reasons": {"insufficient_history": 3},
    }
    output = rendered(c, e)
    assert "REAL MARKET DATA" in output and "EXPERIMENTAL PAPER TRADING" in output
    assert "CERTIFIED PAPER TRADING" in output and "UNVALIDATED" in output
    assert "$499.00" in output and "$500.00" in output and "$-1.00" in output
    assert "Emergency stop: ACTIVE" in output and "validation_blocked" in output
    assert max(map(len, output.splitlines())) <= 38


def test_synthetic_service_is_not_presented_as_real():
    output = rendered({"mode": "paper", "cash": 123, "simulated_pnl": 999})
    assert "No verified live feed" in output and "$123.00" not in output


def test_terminal_control_sequences_are_not_rendered():
    output = rendered(
        e={"account_id": "experimental-paper", "latest_activity": ["bad\x1b[2Jvalue"], "strategies": []}
    )
    assert "\x1b" not in output
