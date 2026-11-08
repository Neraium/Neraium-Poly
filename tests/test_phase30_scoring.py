"""Controlled scoring/journal fixtures, never authentic outcome claims."""
from copy import deepcopy
from datetime import timedelta

import pytest
from neraium_poly.research.phase14.relationships import digest
from neraium_poly.research.phase30.outcomes import replay_official_event
from neraium_poly.research.phase30.scoring import OfficialEventScoring, evaluation
from test_phase26_outcomes import ASOF, NOW
from test_phase30_outcomes import verified


@pytest.fixture(autouse=True)
def controlled_storage_capacity(monkeypatch):
    from types import SimpleNamespace

    from neraium_poly.research.phase30 import outcomes
    monkeypatch.setattr(outcomes.shutil,'disk_usage',lambda _p:SimpleNamespace(free=200*1024**3))


class Store:
    def __init__(self,study):self.rows={study['id']:study};self.kinds={study['id']:'Original'}
    def get(self,i):return self.rows.get(i)
    def latest(self,kind,limit=1):return list(reversed([v for k,v in self.rows.items() if self.kinds[k]==kind]))[:limit]
    def append(self,r):
        value=r.model_dump(mode='json')
        if r.id in self.rows:
            assert digest(value)==digest(self.rows[r.id]);return False
        self.rows[r.id]=value;self.kinds[r.id]=type(r).__name__;return True


class Index:
    def __init__(self,f,s):self.f,self.s=f,s
    def report(self,**kw):return {'projection':{'status':'caught_up'}}
    def snapshot(self):
        f,s=self.f,self.s
        return [{'type':'forecast','replay_verified':True,'forecast_id':f['id'],'forecast_sha256':digest(f),
            'source_id':s['id'],'source_study_sha256':digest(s),'available_at':s['available_at'],'forecast':{k:v for k,v in f.items() if k in ('id','timestamp','event_end_time','event_id','market_id','token_id','model_id','probability','domain')},
            'review':{'descriptor':{'league':'NHL'}}}],{'id':'CONTROLLED-anchor','available_at':ASOF.isoformat()}


async def test_append_only_event_scores_recover_and_do_not_reacquire_or_settle(monkeypatch,tmp_path):
    f,s,result,_calls=await verified(monkeypatch,tmp_path);store=Store(s);index=Index(f,s);acquisitions=[]
    async def acquire(f,**kw):acquisitions.append(f['id']);return deepcopy(result)
    engine=OfficialEventScoring(store,index,tmp_path,clock=lambda:ASOF,can_write=lambda:True,verify=acquire,replay=replay_official_event)
    assert await engine.step()
    assert engine.status()['verified_forecast_labels']==1 and engine.status()['distinct_official_games']==1
    assert engine.status()['models'][0]['market_baseline_comparison'] is None
    assert engine.status()['certified_training_events']==0 and not engine.status()['native_payout_verified']
    assert store.latest('OfficialEventLabelStudy')[0]['result']==result
    recovered=OfficialEventScoring(store,index,tmp_path,clock=lambda:ASOF+timedelta(seconds=301),can_write=lambda:True,verify=acquire,replay=replay_official_event)
    assert await recovered.step() and len(acquisitions)==1
    assert len(store.latest('OfficialEventLabelStudy',10))==1
    assert recovered.status()['models'][0]['descriptive_brier']==pytest.approx((f['probability']-1)**2)
    assert not engine.status()['trading_authority'] and not engine.status()['certification_authority']


async def test_corrupt_official_proof_is_not_scored_after_restart(monkeypatch,tmp_path):
    f,s,result,_calls=await verified(monkeypatch,tmp_path);store=Store(s);index=Index(f,s)
    async def acquire(*a,**k):return result
    engine=OfficialEventScoring(store,index,tmp_path,clock=lambda:ASOF,can_write=lambda:True,verify=acquire,replay=replay_official_event);await engine.step()
    ref=result['official_evidence'][0]
    (tmp_path/result['evidence_directory']/ref['raw_file']).write_bytes(b'CONTROLLED CORRUPTION')
    recovered=OfficialEventScoring(store,index,tmp_path,clock=lambda:ASOF+timedelta(seconds=301),can_write=lambda:True,verify=acquire,replay=replay_official_event)
    await recovered.step()
    assert recovered.status()['scored_forecast_event_model_pairs']==0 and recovered.status()['collection_rejections']


async def test_event_group_and_chronological_dedup_never_inflate_n(monkeypatch,tmp_path):
    f,s,result,_calls=await verified(monkeypatch,tmp_path);p=replay_official_event(result,s,f,evidence_root=tmp_path,as_of=ASOF)
    item={'label_id':'CONTROLLED','forecast':f,'forecast_available_at':s['available_at'],'proof':p}
    later=deepcopy(item);later['forecast']['timestamp']=(NOW+timedelta(seconds=2)).isoformat();later['forecast_available_at']=(NOW+timedelta(seconds=3)).isoformat();later['forecast']['id']='CONTROLLED-later';later['proof']['forecast_id']='CONTROLLED-later'
    r=evaluation([later,item,item]);assert r['distinct_official_games']==1 and r['scored_forecast_event_model_pairs']==1
    assert r['models'][0]['event_scores'][0]['forecast_id']==f['id']
    assert r['effective_independent_sample_size'] is None and not r['statistical_independence_verified']
    assert not r['models'][0]['superiority_established'] and r['models'][0]['calibration'] is None


async def test_late_or_authority_mismatched_label_is_rejected(monkeypatch,tmp_path):
    f,s,result,_calls=await verified(monkeypatch,tmp_path);p=replay_official_event(result,s,f,evidence_root=tmp_path,as_of=ASOF)
    item={'label_id':'CONTROLLED','forecast':f,'forecast_available_at':ASOF.isoformat(),'proof':p}
    assert evaluation([item])['scored_forecast_event_model_pairs']==0
    item['forecast_available_at']=s['available_at'];item['proof']['native_payout_verified']=True
    assert evaluation([item])['scored_forecast_event_model_pairs']==0


async def test_cancelled_reader_drains_before_owner_shutdown():
    import asyncio
    import threading

    from neraium_poly.research.phase30.scoring import _thread
    entered=threading.Event();release=threading.Event();finished=threading.Event()
    def reader():
        entered.set();release.wait(timeout=2);finished.set();return 1
    task=asyncio.create_task(_thread(reader))
    for _ in range(100):
        if entered.is_set():break
        await asyncio.sleep(.001)
    assert entered.is_set()
    task.cancel();await asyncio.sleep(.01)
    assert not task.done() and not finished.is_set()
    release.set()
    with pytest.raises(asyncio.CancelledError):await asyncio.wait_for(task,1)
    assert finished.is_set()
