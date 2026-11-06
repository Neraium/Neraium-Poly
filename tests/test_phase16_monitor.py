"""Controlled terminal inputs; no fixture is presented as an operational result."""
from datetime import UTC, datetime, timedelta
from io import StringIO

from neraium_poly.ops import monitor as module
from rich.console import Console
from test_phase15_monitor import sample as operations_sample


def sample():
    c, e = operations_sample()
    now = datetime.now(UTC).isoformat()
    e.update(kill_switch=False, orders_submitted=0, fills=0, open_positions=0)
    e["operations_research"]["phase16"] = {
        "status": "research_only", "last_study_at": now,
        "history": {"tokens_tracked": 1, "current_observations": 80, "valid_observations": 80,
                    "matured_labels": 50, "current_matured_labels": 50, "unique_parent_events": 1,
                    "per_token": [{"token_id": "controlled-token", "latest_source_at": now,
                                   "latest_available_at": now}]},
        "qualification": {"mark_research_readiness": {"status": "insufficient_evidence",
                "remaining_requirements": ["depth_history_required"]}, "eligible_mark_tokens": [],
                "estimated_executable_edge": -.005,
                "execution_context": {"bound": True, "token_id": "controlled-token", "source_at": now, "available_at": now},
                "calibration": {"training_events": 0, "heldout_events": 0, "metrics": None}},
        "relationships": {"engine": {"evaluations": 14}}}
    return c, e


def render(c=None, e=None, width=40, height=24, errors=()):
    out = StringIO(); console = Console(file=out, width=width, height=height, color_system=None)
    console.print(module.render_monitor(c, e, width=width, height=height, view="readiness", errors=errors))
    value = out.getvalue()
    assert len(value.splitlines()) <= height
    assert all(len(row) <= width for row in value.splitlines())
    return value


def test_readiness_phone_layout_preserves_both_accounts_stop_and_safety():
    for width, height in [(30, 12), (40, 24), (80, 40)]:
        c, e = sample(); text = render(c, e, width, height)
        assert "REAL MARKET DATA" in text
        assert "EXPERIMENTAL PAPER" in text and "CERTIFIED PAPER" in text
        assert text.count("$500.00") == 2 and "Stop clear" in text
        assert "LIVE TRADING DISABLED" in text and "Terminal train/held 0/0" in text
        if height >= 24:
            assert "Tokens 1 Marks 50" in text and "insufficient evidence" in text
            assert "-0.0050/share" in text and "Orders 0 Fills 0 Pos 0" in text
            assert "Terminal Brier insufficient evidence" in text


def test_missing_inputs_never_become_synthetic_zero_accounts_or_calibration():
    text = render()
    assert "$500.00" not in text and "$0.00" not in text
    assert "SOURCE STALE / UNAVAILABLE" in text
    assert "LIVE CONFIG UNVERIFIED" in text and "DISABLED" not in text
    assert "Last terminal train/held —/—" in text


def test_fresh_render_timestamp_cannot_make_old_source_quotes_fresh():
    c, e = sample()
    study = e["operations_research"]["phase16"]
    old = (datetime.now(UTC)-timedelta(seconds=16)).isoformat()
    study["history"]["per_token"][0]["latest_source_at"] = old
    text = render(c, e)
    assert "REAL MARKET DATA" in text  # collector itself remains current
    assert "Mark research: stale / unavailable" in text
    assert "Est edge (research) unavailable" in text and "-0.0050/share" not in text
    assert "Remaining: fresh source quotes" in text


def test_old_study_and_future_receipt_cannot_report_current_readiness():
    c, e = sample()
    study = e["operations_research"]["phase16"]
    study["last_study_at"] = (datetime.now(UTC)-timedelta(seconds=61)).isoformat()
    text = render(c, e)
    assert "Last Tokens" in text and "Last terminal" in text
    assert "Remaining: fresh study evidence" in text
    c, e = sample()
    e["operations_research"]["phase16"]["history"]["per_token"][0]["latest_available_at"] = (datetime.now(UTC)+timedelta(seconds=1)).isoformat()
    assert "Est edge (research) unavailable" in render(c, e)


def test_unsupported_brier_and_terminal_sample_counts_are_not_invented():
    c, e = sample()
    calibration = e["operations_research"]["phase16"]["qualification"]["calibration"]
    calibration["metrics"] = {"brier": .001}
    assert "Terminal Brier insufficient evidence" in render(c, e)
    calibration.update(training_events=100, heldout_events=100)
    assert "Terminal Brier 0.00100" in render(c, e)


def test_incomplete_or_unsafe_process_flags_do_not_claim_live_execution_disabled():
    c, e = sample(); del e["service"]["paper_trading"]
    assert "LIVE CONFIG UNVERIFIED" in render(c, e)
    c, e = sample(); e["service"]["live_trading_enabled"] = True
    assert "WARNING LIVE CONFIG UNSAFE" in render(c, e)


def test_readiness_uses_compact_operations_endpoints_and_sanitizes_errors(monkeypatch):
    urls = []
    async def fetch(c, e):
        urls.extend([c, e]); return *sample(), ()
    monkeypatch.setattr(module, "fetch_views", fetch)
    module.monitor(once=True, width=40, view="readiness", no_color=True,
                   certified_url="http://127.0.0.1:18742/api/state",
                   experimental_url="http://127.0.0.1:18743/custom")
    assert urls == ["http://127.0.0.1:18742/api/operations-state", "http://127.0.0.1:18743/api/operations-state"]
    c, e = sample()
    text = render(c, e, height=40, errors=("controlled\x1b[2Jfailure",))
    assert "controlledfailure" in text and "\x1b" not in text


def test_fresh_other_token_does_not_make_bound_execution_quote_current():
    c, e = sample()
    q = e['operations_research']['phase16']['qualification']
    q['mark_research_readiness']['status'] = 'research_prerequisites_observed'
    q['execution_context']['source_at'] = (datetime.now(UTC)-timedelta(seconds=16)).isoformat()
    text = render(c, e)
    assert 'Mark research: stale / unavailable' in text
    assert 'Est edge (research) unavailable' in text
