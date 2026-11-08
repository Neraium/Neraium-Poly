"""Controlled orchestration fixtures; no authentic trading results."""
from datetime import timedelta

import pytest
from neraium_poly.contracts import Record
from neraium_poly.data import EventStore
from neraium_poly.research.phase14.relationships import digest
from neraium_poly.research.phase28.continuous import VolumeResearch
from neraium_poly.research.phase28.inputs import current_frame
from test_phase24_integration import NOW, inputs


class Original(Record):
    forecasts:list


class Index:
    def __init__(self,studies):
        self.entries=[{'type':'forecast','replay_verified':True,'forecast_id':f['id'],'forecast_sha256':digest(f),'source_id':s['id'],'source_study_sha256':digest(s),'forecast':f} for s in studies for f in s['forecasts']]
    def report(self,**kw):return {'projection':{'status':'caught_up'}}
    def snapshot(self):return self.entries,{'id':'CONTROLLED-anchor','available_at':NOW.isoformat()}


def build(studies,frame,**kwargs):
    assert len(studies)==1
    return {'rows':[{'id':s['id'],'original_sha':digest(s)} for s in studies]}


def combine(reports,**kwargs):
    return {'findings':[r for report in reports for r in report['rows']],'counts':{'qualified_research_findings':0},'research_only':True,'trading_authority':False}


def setup(tmp_path):
    store=EventStore(tmp_path/'controlled.sqlite');studies=[]
    for i in range(2):
        s=Original(id=f'CONTROLLED-{i}',timestamp=NOW,available_at=NOW,source='CONTROLLED-fixture',forecasts=[{'id':f'CONTROLLED-F{i}','timestamp':NOW.isoformat()}]);store.append(s);studies.append(s.model_dump(mode='json'))
    return store,Index(studies)


def test_streamed_sources_recover_and_keep_full_frame(tmp_path):
    store,index=setup(tmp_path)
    try:
        r=VolumeResearch(store,index,clock=lambda:NOW,can_write=lambda:True,builder=build,combiner=combine)
        assert r.step({'books':[]})
        assert r.status()['raw_study_cache_bytes']==0 and r.totals['finding_rows']==2
        recovered=VolumeResearch(store,index,clock=lambda:NOW,can_write=lambda:True,builder=build,combiner=combine)
        assert not recovered.step({'books':[]}) and store.count(kind='VolumeStudy')==1
        row=store.latest('VolumeStudy',1)[0];row['decision_frame_sha256']='CONTROLLED-corrupt'
        with pytest.raises(ValueError,match='frame integrity'):recovered._adopt(row)
    finally:store.close()


def test_publication_ahead_of_ack_and_authority_guard(tmp_path,monkeypatch):
    store,index=setup(tmp_path)
    try:
        r=VolumeResearch(store,index,clock=lambda:NOW,can_write=lambda:True,builder=build,combiner=combine);append=store.append
        def fail(record):append(record);raise OSError('CONTROLLED interrupted acknowledgement')
        monkeypatch.setattr(store,'append',fail)
        with pytest.raises(OSError):r.step({})
        monkeypatch.setattr(store,'append',append)
        assert not r.step({}) and r.status()['totals']['evaluations']==1
    finally:store.close()


def test_current_composition_preserves_native_clocks_and_rejects_old_primary():
    _m,b,_e,_f,frame=inputs()
    composed=current_frame(frame,as_of=NOW+timedelta(seconds=1))
    assert composed.books[0].timestamp==b.timestamp and composed.available_at==NOW+timedelta(seconds=1)
    with pytest.raises(ValueError,match='fresh_primary'):current_frame(frame,as_of=NOW+timedelta(seconds=16))
    wrong=b.model_copy(update={'market_id':'CONTROLLED-wrong'})
    with pytest.raises(ValueError,match='identity'):current_frame(frame,extra_books=[wrong],as_of=NOW)


async def test_volume_loop_does_not_wait_for_unresolved_source_lock(tmp_path):
    import asyncio
    from types import SimpleNamespace

    from neraium_poly.experimental.runtime import ExperimentalRuntime
    _m,_b,_e,_f,frame=inputs();done=[False];calls=[]
    runtime=ExperimentalRuntime.__new__(ExperimentalRuntime)
    runtime.stopping=False;runtime.last_frame=frame;runtime.clock=lambda:NOW
    runtime.phase26_inputs=None;runtime._research_report_lock=asyncio.Lock()
    runtime._research_source_lock=asyncio.Lock();await runtime._research_source_lock.acquire()
    runtime.events=EventStore(tmp_path/'controlled-loop.sqlite');runtime.config=SimpleNamespace(data_dir=tmp_path)
    runtime.phase26_index=SimpleNamespace(step=lambda *a,**k:None,report=lambda **k:{'projection':{'status':'caught_up'}})
    runtime._budget_ok=lambda:True
    def step(current):
        calls.append(current);done[0]=True;return True
    runtime.phase28=SimpleNamespace(step=step,error=None)
    try:
        await asyncio.wait_for(runtime._volume_research_loop(lambda:done[0]),timeout=2)
        assert calls and calls[0].books[0].timestamp==frame.books[0].timestamp
        assert runtime._research_source_lock.locked() and runtime.phase28.error is None
    finally:runtime._research_source_lock.release();runtime.events.close()


def test_research_configuration_does_not_change_certified_or_account_risk_limits():
    import json
    from pathlib import Path
    root=Path(__file__).resolve().parents[1]
    for name in ['paper-live.example.json','experimental-paper.example.json']:
        cfg=json.loads((root/'config'/name).read_text())
        assert cfg['risk_limits']['min_net_edge']==.03
        assert cfg['risk_limits']['aggregate_fraction']==.2
        assert cfg['archive_budget_mb']==153600 and cfg['archive_reserve_disk_mb']==102400


def test_forecast_namespace_preserves_physical_provenance_and_logical_recovery(tmp_path):
    import json

    from neraium_poly.research.phase27.payout import PayoutForecastStudy
    from neraium_poly.research.phase28.continuous import ForecastStore
    store=EventStore(tmp_path/'controlled-forecast.sqlite')
    try:
        logical=PayoutForecastStudy(id='CONTROLLED-payout',timestamp=NOW,available_at=NOW,source='CONTROLLED',enrollment_id='CONTROLLED-window',original_study_id='CONTROLLED-original',original_study_sha256='a'*64,horizon='1h',forecasts=[{'id':'CONTROLLED-estimate'}])
        namespace=ForecastStore(store,'CONTROLLED-parent');namespace.append(logical)
        physical=json.loads(store.get(logical.id)[1]);restored=namespace.get(logical.id)
        assert physical['parent_enrollment_id']=='CONTROLLED-parent'
        assert 'parent_enrollment_id' not in restored
        assert PayoutForecastStudy.model_validate(restored).forecasts==logical.forecasts
        assert digest(physical)!=digest(restored) # reports must use the physical source body
    finally:store.close()
