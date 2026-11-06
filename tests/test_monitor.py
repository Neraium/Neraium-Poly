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
    assert "Values unknown; API unavailable" in output and "$0.00" not in output


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


def sample():
    certified = {
        "mode": "live_market_paper",
        "generated_at": "2026-11-06T02:00:00Z",
        "cash": 500,
        "simulated_pnl": 0,
        "exposure": 0,
        "suspended": False,
        "relationships": ["controlled-relationship"],
        "operation": {
            "scan": {"discovered_markets": 200},
            "fresh_books": 284,
            "current_books": 400,
            "connectivity": {"ws_connected": True, "messages": 2000000, "gaps": 22, "reconnects": 0},
            "validation": {"active": False},
            "service": {"trading_status": "validation_blocked"},
        },
        "research": {"coverage": {"train_events": 0, "heldout_events": 0}},
    }
    experimental = {
        "account_id": "experimental-paper",
        "cash": 498,
        "simulated_pnl": -2,
        "exposure": 2,
        "reserved": 0,
        "positions": ["controlled-position"],
        "orders": [],
        "fills": 0,
        "qualified_opportunities": 0,
        "suspended": False,
        "service": {"status": "ok"},
        "strategies": [
            {"strategy_id": name, "enabled": True, "simulated_realized_pnl": -i}
            for i, name in enumerate(
                [
                    "short_horizon",
                    "event_driven",
                    "liquidity_spread",
                    "persistent_relationship",
                    "calibrated_forecast",
                    "cross_market_consistency",
                ]
            )
        ],
        "rejection_reasons": {"missing_independent_context_available_before_decision": 125},
        "latest_activity": ["controlled strategy rejected; insufficient causal history"],
    }
    return certified, experimental


def at_size(width, height, certified=None, experimental=None, errors=()):
    console = Console(width=width, height=height, record=True, no_color=True)
    console.print(render_monitor(certified, experimental, width=width, height=height, errors=errors))
    return console.export_text()


def test_phone_and_desktop_viewports_keep_safety_and_accounts_visible():
    for width in (34, 38, 45, 80):
        certified, experimental = sample()
        output = at_size(width, 24, certified, experimental, errors=("experimental state HTTP failure",))
        assert len(output.splitlines()) <= 24
        assert max(map(len, output.splitlines())) <= width
        for required in (
            "REAL MARKET DATA",
            "EXPERIMENTAL PAPER TRADING",
            "CERTIFIED PAPER TRADING",
            "UNVALIDATED",
            "$498.00",
            "$500.00",
            "validation_blocked",
            "LIVE FINANCIAL TRADING DISABLED",
            "Ctrl-C exits monitor only",
        ):
            assert required in output
        assert "Rej 125" in output


def test_short_viewports_preserve_all_three_account_labels_and_live_disable():
    for height in (12, 18, 24, 50):
        certified, experimental = sample()
        output = at_size(34, height, certified, experimental)
        assert len(output.splitlines()) <= height
        for required in (
            "REAL MARKET DATA",
            "EXPERIMENTAL PAPER TRADING",
            "CERTIFIED PAPER TRADING",
            "LIVE FINANCIAL TRADING DISABLED",
        ):
            assert required in output


def test_missing_status_flags_remain_unknown():
    certified, experimental = sample()
    experimental.pop("suspended")
    certified.pop("suspended")
    certified["operation"]["connectivity"].pop("ws_connected")
    certified["operation"]["validation"].pop("active")
    output = at_size(38, 40, certified, experimental)
    assert "WS unknown" in output and "Emergency stop: unknown" in output
    assert "Owner unknown" in output and "Stop unknown" in output


def test_nonfinite_and_boolean_numbers_are_unknown():
    certified, experimental = sample()
    experimental.update(cash=float("nan"), simulated_pnl=float("inf"), fills=True)
    output = at_size(38, 24, certified, experimental)
    assert "$nan" not in output and "$inf" not in output and "Fill unknown" in output


def test_control_sequences_bidi_and_markup_are_literal_sanitized_text():
    experimental = {
        "account_id": "experimental-paper",
        "latest_activity": ["\x1b[2Jbad\x1b]0;title\x07\u202e[red]literal[/red]"],
    }
    output = at_size(80, 30, experimental=experimental)
    assert "\x1b" not in output and "\x07" not in output and "\u202e" not in output
    assert "[red]literal[/red]" in output and "title" not in output


def test_stale_position_marks_are_never_presented_as_fresh_pnl():
    certified, experimental = sample()
    experimental.update(stale_mark_tokens=["controlled-position"], pnl_valuation="stale_last_observed_marks")
    output = at_size(34, 24, certified, experimental)
    assert "UNVALIDATED · STALE MARKS 1" in output and "P/L(last) $-2.00" in output
    assert len(output.splitlines()) <= 24


def test_source_timestamp_offsets_are_converted_to_utc():
    certified, experimental = sample()
    certified["generated_at"] = "2026-11-06T02:00:00+05:00"
    output = at_size(38, 24, certified, experimental)
    assert "11-05 21:00:00Z" in output


def test_enabled_engine_scope_is_shown_separately_from_performance():
    certified, experimental = sample()
    experimental["strategy_engine"] = {"enabled": ["short_horizon"]}
    output = at_size(80, 50, certified, experimental)
    assert "Short-horizon on P/L $0.00" in output
    assert "Event-driven off P/L $-1.00" in output


async def test_http_views_are_concurrent_and_failure_stays_unknown(monkeypatch):
    import asyncio

    import httpx
    from neraium_poly.ops import monitor as module

    original = httpx.AsyncClient
    both = asyncio.Event()
    requests = []

    async def response(request):
        requests.append(str(request.url))
        if len(requests) == 2:
            both.set()
        await asyncio.wait_for(both.wait(), timeout=1)
        return (
            httpx.Response(200, json={"mode": "live_market_paper"})
            if request.url.port == 18742
            else httpx.Response(503)
        )

    monkeypatch.setattr(
        module.httpx,
        "AsyncClient",
        lambda **kwargs: original(**kwargs, transport=httpx.MockTransport(response)),
    )
    certified, experimental, errors = await module.fetch_views(
        "http://127.0.0.1:18742/api/state", "http://127.0.0.1:18743/api/state"
    )
    assert len(requests) == 2 and certified["mode"] == "live_market_paper"
    assert experimental is None and len(errors) == 1
    assert "$0.00" not in at_size(38, 24, certified, experimental, errors)


async def test_nonobject_state_is_unavailable_not_a_renderer_exception(monkeypatch):
    import httpx
    from neraium_poly.ops import monitor as module

    original = httpx.AsyncClient
    monkeypatch.setattr(
        module.httpx,
        "AsyncClient",
        lambda **kwargs: original(
            **kwargs, transport=httpx.MockTransport(lambda request: httpx.Response(200, json=[]))
        ),
    )
    certified, experimental, errors = await module.fetch_views(
        "http://127.0.0.1:18742/api/state", "http://127.0.0.1:18743/api/state"
    )
    assert certified is experimental is None and len(errors) == 2


async def test_state_read_budget_is_applied_during_streaming(monkeypatch):
    import httpx
    from neraium_poly.ops import monitor as module

    class Oversize(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b"x" * (4 * 1024 * 1024)
            yield b"y" * (4 * 1024 * 1024)
            yield b"z"

    original = httpx.AsyncClient
    monkeypatch.setattr(
        module.httpx,
        "AsyncClient",
        lambda **kwargs: original(
            **kwargs, transport=httpx.MockTransport(lambda request: httpx.Response(200, stream=Oversize()))
        ),
    )
    certified, experimental, errors = await module.fetch_views(
        "http://127.0.0.1:18742/api/state", "http://127.0.0.1:18743/api/state"
    )
    assert certified is experimental is None and all("ValueError" in reason for reason in errors)


def test_relationship_evaluations_come_from_observed_engine_status():
    certified, experimental = sample()
    experimental["strategy_engine"] = {"intelligence": {"evaluations": 7}}
    assert "Relationships 1 ExpEval 7" in at_size(38, 24, certified, experimental)
