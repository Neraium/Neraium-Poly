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
    assert "Relations 1 Evidence/cycle 7" in at_size(38, 24, certified, experimental)


def test_latest_observed_cycle_is_visible_even_without_trades():
    output = rendered(
        e={
            "account_id": "experimental-paper",
            "last_cycle": {"timestamp": "2026-11-06T02:42:00Z", "signal_count": 312, "eligible_count": 0},
            "latest_activity": [],
        }
    )
    assert "Last 02:42:00Z 312 eval 0 opp" in output


def trace_sample():
    """Controlled presentation counters, never evidence of genuine trades."""
    from neraium_poly.experimental.trace_contracts import STAGES

    certified, experimental = sample()
    names = [row["strategy_id"] for row in experimental["strategies"]]

    def rows(considered):
        return {
            name: {
                **dict.fromkeys(STAGES, 0),
                "markets_considered": considered,
                "valid_observations": considered - 1,
                "rejected_signals": considered,
                "reasons": {
                    "conservative_roundtrip_edge_insufficient": {
                        "count": considered,
                        "category": "MARKET CONDITION",
                        "samples": [],
                    }
                },
            }
            for name in names
        }

    experimental["decision_trace"] = {
        "epoch_started_at": "2026-11-06T00:00:00Z",
        "last_evaluation_at": "2026-11-06T03:45:00Z",
        "phase10_epoch": {"strategies": rows(128)},
        "latest_cycle": {"strategies": rows(12)},
    }
    experimental.update(experimental_fresh_books=14, selected_tokens=64)
    return certified, experimental


def page(c, e, *, view="summary", scope="cycle", width=34, height=24):
    return render_monitor(c, e, view=view, scope=scope, width=width, height=height).plain


def test_phase10_scopes_show_latest_vs_persisted_without_combining():
    c, e = trace_sample()
    cycle, epoch = page(c, e), page(c, e, scope="epoch")
    assert "Considered 72 Valid 66" in cycle
    assert "Considered 768 Valid 762" in epoch
    assert "03:45:00Z" in cycle and "00:00:00Z" in epoch
    assert "net edge below floor" in cycle
    assert "Signals 0 Qualified 0" in cycle


def test_strategy_page_keeps_all_six_rows_and_safety_in_phone_view():
    from rich.cells import cell_len

    c, e = trace_sample()
    for width in (34, 38, 45, 80):
        for view in ("summary", "strategies", "rejections"):
            output = page(c, e, view=view, width=width)
            assert len(output.splitlines()) <= 24
            assert max(map(cell_len, output.splitlines())) <= width
            for label in (
                "REAL MARKET DATA",
                "EXPERIMENTAL PAPER TRADING",
                "CERTIFIED PAPER TRADING",
                "LIVE FINANCIAL TRADING DISABLED",
            ):
                assert label in output
        strategies = page(c, e, view="strategies", width=width)
        for name in ("Short-ho", "Event-dr", "Spread", "Relation", "Forecast", "Cross-ma"):
            assert name in strategies
        assert "Risk 0 Attempts 0" in strategies
        assert "Expired 0 Cancel 0" in strategies


def test_rejection_page_is_explicitly_nonexclusive_and_evidence_scoped():
    c, e = trace_sample()
    assert "nonexclusive counts" in page(c, e, view="rejections")
    assert "72 net edge below floor" in page(c, e, view="rejections")
    assert "768 net edge below floor" in page(c, e, view="rejections", scope="epoch")


def test_legacy_trace_absence_and_missing_fields_are_never_invented():
    c, e = sample()
    legacy = page(c, e, view="strategies")
    assert "Legacy counters; trace unavailable" in legacy
    assert "Valid — Risk — Attempts —" in legacy
    e["decision_trace"] = {"latest_cycle": {"strategies": {"short_horizon": {}}}}
    output = page(c, e)
    assert "Considered — Valid —" in output and "Qualified —" in output
    assert "No rejection evidence" in output


def test_fresh_percentage_uses_known_matching_source_and_experimental_denominators():
    c, e = trace_sample()
    output = page(c, e, view="strategies")
    assert "284/400 71%" in output
    assert "14/64 22%" in output
    c["operation"]["current_books"] = None
    assert "284/—" in page(c, e, view="strategies")
    assert "284/— 0%" not in page(c, e, view="strategies")


def test_trace_scope_and_view_are_explicitly_validated():
    import pytest

    for kwargs in ({"scope": "all_time"}, {"view": "trade"}):
        with pytest.raises(ValueError):
            render_monitor(**kwargs)


def test_initial_flat_trace_contract_remains_readable():
    c, e = trace_sample()
    trace = e["decision_trace"]
    e["decision_trace"] = {
        "epoch": trace["epoch_started_at"],
        "totals": {"short_horizon": {"markets_considered": 52, "rejections": {"stale_book": 3}}},
        "latest_cycle": {"short_horizon": {"markets_considered": 4, "rejections": {"stale_book": 2}}},
    }
    assert "Considered 4" in page(c, e)
    assert "Rej 2 stale book" in page(c, e)
    assert "Considered 52" in page(c, e, scope="epoch")


def test_phone_counter_cells_bound_large_epoch_counts_and_sanitize_reasons():
    c, e = trace_sample()
    for row in e["decision_trace"]["phase10_epoch"]["strategies"].values():
        row["markets_considered"] = 12345678
        row["fills"] = 12345678
    output = page(c, e, view="strategies", scope="epoch")
    assert "12M" in output
    assert "12,345,678" not in output


def test_observed_unsafe_configuration_never_claims_live_disabled():
    c, e = trace_sample()
    e["service"]["live_trading_enabled"] = True
    for view in ("summary", "strategies", "rejections"):
        output = page(c, e, view=view)
        assert "WARNING LIVE CONFIGURATION UNSAFE" in output
        assert "LIVE FINANCIAL TRADING DISABLED" not in output


def test_rejection_categories_are_supported_by_counts_not_invented():
    c, e = trace_sample()
    output = page(c, e, view="rejections")
    assert "72 MARKET CONDITION" in output
    assert "MISSING EVIDENCE" not in output


def test_source_freshness_denominator_includes_temporarily_missing_subscribed_books():
    c, e = trace_sample()
    c["operation"]["current_books"] = 370
    c["operation"]["connectivity"]["subscribed_tokens"] = 400
    assert "284/400 71%" in page(c, e, view="strategies")
    assert "284/370" not in page(c, e)


def test_research_view_renders_all_six_strategies_without_fabricated_performance():
    c, e = sample()
    ids = [
        "short_horizon",
        "persistent_relationship",
        "cross_market_consistency",
        "liquidity_spread",
        "event_driven",
        "calibrated_forecast",
    ]
    e["research"] = {
        "status": "exploratory",
        "generated_at": "2026-11-06T04:00:00Z",
        "independent_training_events": 0,
        "independent_heldout_events": 0,
        "baseline_comparison": "unchanged bid better",
        "calibration_status": "terminal unavailable",
        "confidence": "limited; correlated labels",
        "strategies": [
            {
                "strategy_id": sid,
                "evaluations": 42,
                "candidate_signals": 3,
                "qualification_rate": 0,
                "estimated_net_edge": None,
                "bottleneck": "missing independent evidence",
            }
            for sid in ids
        ],
    }
    for width in [34, 38, 45, 80]:
        output = render_monitor(c, e, width=width, height=24, view="research").plain
        assert len(output.splitlines()) <= 24
        assert max(map(len, output.splitlines())) <= width
        assert all(
            name in output
            for name in ["Short-horiz", "Relationshi", "Cross-marke", "Spread", "Event-drive", "Forecast"]
        )
        assert "Evidence 0/0 need 100/100" in output
        assert "Edge unavailable" in output and "Cal terminal unavailable" in output
        assert "LIVE FINANCIAL TRADING DISABLED" in output
        assert "RESEARCH · UNVALIDATED" in output
        assert "Base unchanged bid better" in output


def test_research_missing_report_does_not_show_invented_metrics_or_confidence():
    output = render_monitor(view="research", width=38).plain
    assert "No research artifact" in output
    assert "Edge unavailable" in output and "Confidence unavailable" in output
    assert "Evidence —/—" in output
    assert "$500.00" not in output and "100.0%" not in output


def test_research_view_qualification_uses_live_trace_scope_not_unsupported_report():
    c, e = sample()
    e["research"] = {
        "status": "exploratory",
        "strategies": [
            {
                "strategy_id": "short_horizon",
                "evaluations": 999,
                "candidate_signals": 999,
                "qualification_rate": 1,
            }
        ],
    }
    e["decision_trace"] = {
        "latest_cycle": {
            "strategies": {
                "short_horizon": {
                    "markets_considered": 64,
                    "candidate_signals": 4,
                    "qualified_opportunities": 0,
                }
            }
        }
    }
    output = render_monitor(c, e, view="research").plain
    assert "0.0%" in output and "100.0%" not in output and "999" not in output


def test_stale_research_does_not_republish_old_edge_as_current():
    c, e = sample()
    e["research"] = {
        "status": "stale",
        "baseline_comparison": "old positive result",
        "strategies": [
            {
                "strategy_id": "short_horizon",
                "evaluations": 999,
                "candidate_signals": 999,
                "qualification_rate": 1,
                "estimated_net_edge": 0.99,
            }
        ],
    }
    output = render_monitor(c, e, view="research").plain
    assert "Edge unavailable" in output and "old positive result" not in output
    assert "999" not in output and "100.0%" not in output
    assert "Report unavailable/stale" in output


def test_compact_research_counts_do_not_cap_real_higher_counts_at_99k():
    from neraium_poly.ops.monitor import _compact_count

    assert _compact_count(123456) == "123k"
    assert _compact_count(123456789) == "123M"
    assert _compact_count(None) == "—"
