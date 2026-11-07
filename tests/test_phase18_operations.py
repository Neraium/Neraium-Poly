"""Controlled phone rendering and configuration, never genuine market evidence."""
from datetime import UTC, datetime
from io import StringIO

import pytest
from neraium_poly.ops.live_config import LivePaperConfig
from neraium_poly.ops.monitor import render_monitor
from neraium_poly.research.phase15.budgets import capacity_status
from neraium_poly.research.phase18.operations import tier_allocations
from rich.console import Console
from test_phase15_monitor import sample


def test_approved_storage_budget_and_tiers_preserve_strict_bounds():
    assert LivePaperConfig(archive_budget_mb=204800).archive_budget_mb==204800
    with pytest.raises(ValueError):LivePaperConfig(archive_budget_mb=262145)
    for service,budget in [('collector',200*1024**3),('experimental',100*1024**3)]:
        tiers=tier_allocations(service);assert sum(tiers.values())==budget
        a={'usage_bytes':1024,'budget_bytes':budget,'free_bytes':400*1024**3,'global_floor_bytes':100*1024**3,
           'health':'ok','growth_bytes_per_second':1000,'tier_usage_bytes':{}}
        r=capacity_status(a,service=service,now=datetime.now(UTC),allocations=tiers)
        assert 'tier_allocation_requires_budget_review' not in r['alerts']
        assert not r['budget_increase_authorized'] and not r['retirement_authorized']


def test_event_edge_mobile_empty_and_stale_states_keep_both_accounts_and_gate():
    for width,height in [(30,12),(40,24),(80,40)]:
        c,e=sample();now=datetime.now(UTC).isoformat()
        e['operations_research']['phase18']={'status':'research_only','last_evaluation_at':now,
            'forecasts_by_domain':{'crypto':1},'pending_forecasts':1,'qualified_training_events':0,'qualified_heldout_events':0,
            'approaches':{},'durable_outcome_records':0}
        out=StringIO();Console(file=out,width=width,height=height,color_system=None).print(render_monitor(c,e,view='edge',width=width,height=height))
        s=out.getvalue();assert len(s.splitlines())<=height and all(len(l)<=width for l in s.splitlines())
        assert 'EXPERIMENTAL PAPER' in s and 'CERTIFIED PAPER' in s and 'Stop ACTIVE' in s
        assert s.count('$500.00')==2 and 'LIVE TRADING DISABLED' in s
        assert 'Research models NO order' in s
