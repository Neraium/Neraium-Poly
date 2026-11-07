"""Narrow controlled terminal fixtures, never live market observations."""
from datetime import UTC, datetime, timedelta
from io import StringIO

from neraium_poly.ops.monitor import render_monitor
from rich.console import Console
from test_phase15_monitor import sample


def text(c=None,e=None,width=40,height=24):
    out=StringIO();Console(file=out,width=width,height=height,color_system=None).print(
        render_monitor(c,e,view='edge',width=width,height=height))
    s=out.getvalue();assert len(s.splitlines())<=height;assert max(map(len,s.splitlines()))<=width
    return s


def test_edge_view_preserves_accounts_risk_and_absent_inference():
    for width,height in [(30,12),(40,24),(80,40)]:
        c,e=sample();now=datetime.now(UTC).isoformat()
        e['operations_research']['phase17']={'status':'research_only','last_evaluation_at':now,
            'forecast_points':10,'matured_points':4,'pending_points':6,'unreviewed_parent_groups':1,
            'models':{'unchanged':{'mae':.02}}}
        s=text(c,e,width,height)
        assert 'EXPERIMENTAL PAPER' in s and 'CERTIFIED PAPER' in s
        assert 'Stop ACTIVE' in s and s.count('$500.00')==2
        assert 'LIVE TRADING DISABLED' in s and 'insufficient' in s
        if height>=24:assert 'unchanged MAE 0.02000' in s


def test_stale_research_never_displays_supported_current_accuracy():
    c,e=sample();e['operations_research']['phase17']={'status':'research_only',
        'last_evaluation_at':(datetime.now(UTC)-timedelta(minutes=5)).isoformat(),'models':{'bad':{'mae':.0001}}}
    s=text(c,e);assert '0.00010' not in s and 'bad MAE unavailable' in s
    s=text();assert '$500.00' not in s and 'LIVE CONFIG UNVERIFIED' in s
