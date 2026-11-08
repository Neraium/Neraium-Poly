"""One-domain source accounting and fail-closed scorecard publication fixtures."""
from datetime import timedelta
from types import SimpleNamespace

import pytest
from neraium_poly.research.phase14.relationships import digest
from neraium_poly.research.phase31.scorecard import ScorecardPublisher, build_scorecard
from test_phase27_findings import NOW, inputs


def data():
    s,f,frame=inputs();entry={'type':'forecast','forecast_id':f['id'],'forecast_sha256':digest(f),'forecast':f,'available_at':s['available_at'],'replay_verified':True,'review':{'canonical_group_id':'same-underlying'}}
    return [entry,entry],frame


def test_domains_include_empty_unsupported_categories_and_no_sample_inflation():
    entries,frame=data();shadow={'positions':0,'hypothetical_fills':0,'pending_orders':0}
    r=build_scorecard(entries,frame,{'findings':[]},{},shadow,as_of=NOW)
    d=r['domains'][entries[0]['forecast']['domain']];assert d['prospective_forecasts']==1 and d['reviewed_event_groups']==1
    assert d['official_event_forecast_scores']==0 and d['realized_simulated_pnl'] is None
    assert r['domains']['politics']['forecasting_support']=='evidence_only_no_supported_probability_model'
    assert r['domains']['technology']['prospective_forecasts']==0
    assert r['certified_heldout_events']==0 and not r['trading_authority']


def test_old_or_future_frame_cannot_present_current_scorecard():
    entries,frame=data()
    with pytest.raises(ValueError):build_scorecard(entries,frame,{}, {},{},as_of=NOW+timedelta(seconds=16))


def test_publisher_expires_current_counts_and_never_creates_account_authority():
    now=[NOW];records=[]
    publisher=ScorecardPublisher(SimpleNamespace(append=records.append),clock=lambda:now[0],can_write=lambda:True,official=dict,macro=dict,shadow=dict)
    entries,frame=data();volume=SimpleNamespace(id='CONTROLLED',timestamp=NOW,report={},model_dump=lambda **kw:{'id':'CONTROLLED'})
    publisher.observe(volume,frame,entries);assert publisher.status()['status']=='research_only' and len(records)==1
    assert not records[0].trading_authority
    now[0]+=timedelta(seconds=121);assert publisher.status()['status']=='stale' and 'domains' not in publisher.status()


def test_cpi_source_reference_age_cannot_be_represented_as_current_qualification():
    entries,frame=data();records=[]
    p=ScorecardPublisher(SimpleNamespace(append=records.append),clock=lambda:NOW,can_write=lambda:True,official=dict,
        macro=lambda:{'status':'denominator_only_qualified','available_at':(NOW-timedelta(hours=7)).isoformat()},shadow=dict)
    p.observe(SimpleNamespace(id='CONTROLLED',timestamp=NOW,report={},model_dump=lambda **k:{}),frame,entries)
    assert p.status()['cpi_input_qualification']['status']=='stale'


def test_scorecard_monitor_narrow_empty_state():
    import io

    from neraium_poly.ops.monitor import render_monitor
    from rich.console import Console
    stream=io.StringIO()
    Console(file=stream,width=32,no_color=True).print(render_monitor(experimental={},view="scorecard",width=32,height=24))
    assert stream.getvalue()


def test_failed_source_review_is_counted_without_qualification():
    from neraium_poly.research.phase31.macro import macro_readiness
    entries,frame=data()
    entries[0]['review']=None;entries[0]['replay_verified']=False
    r=build_scorecard(entries,frame,{}, {},{},as_of=NOW)
    d=r['domains'][entries[0]['forecast']['domain']]
    assert d['source_replayed_forecasts']==0 and d['reviewed_event_groups']==0
    macro_readiness(entries,as_of=NOW)


def test_optional_scorecard_failure_cannot_invalidate_committed_economics(tmp_path):
    from test_phase28_continuous import VolumeResearch, build, combine, setup
    store,index=setup(tmp_path)
    def fail(*args):raise ValueError("CONTROLLED observer failure")
    try:
        r=VolumeResearch(store,index,clock=lambda:NOW,can_write=lambda:True,builder=build,combiner=combine,on_report=fail)
        assert r.step({'books':[]}) and store.count(kind='VolumeStudy')==1
        assert r.error is None and r.status()['report_callback_error'].startswith('ValueError')
    finally:store.close()
