"""Controlled operations fixtures, never research performance."""
from datetime import UTC, datetime
from io import StringIO

from neraium_poly.ops.monitor import render_monitor
from rich.console import Console
from test_phase15_monitor import sample


def test_narrow_edge_monitor_preserves_safety_and_no_sii_performance_claim():
    for width, height in [(30, 12), (40, 30), (80, 40)]:
        c, e = sample()
        e['operations_research']['phase18'] = {'status': 'research_only',
            'last_evaluation_at': datetime.now(UTC).isoformat(), 'pending_forecasts': 24,
            'forecasts_by_domain': {'crypto': 24}}
        e['operations_research']['phase20'] = {'status': 'research_only', 'paired': 0, 'withheld': 0}
        out = StringIO()
        Console(file=out, width=width, color_system=None).print(render_monitor(c, e, width=width, height=height, view='edge'))
        text = out.getvalue()
        assert len(text.splitlines()) <= height and all(len(s) <= width for s in text.splitlines())
        assert 'EXPERIMENTAL PAPER' in text and 'CERTIFIED PAPER' in text
        assert 'LIVE TRADING DISABLED' in text
        if height >= 30:
            assert 'SII A/B pairs 0 withheld 0' in text and 'SII challenger unavailable' in text
            assert 'SII improvement unmeasured' in text
