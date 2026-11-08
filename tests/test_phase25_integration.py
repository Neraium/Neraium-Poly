"""Controlled engineering fixtures, never authentic forecasting evidence."""
from types import SimpleNamespace

import pytest
from neraium_poly.data import EventStore
from neraium_poly.research.phase25.continuous import ExpansionResearch
from test_phase24_integration import NOW, adapter, inputs


async def test_namespace_preserves_existing_enrollment_and_restart_checkpoint(tmp_path):
 from neraium_poly.research.phase24.continuous import DomainResearch
 store=EventStore(tmp_path/'fixture.sqlite');_m,_b,e,f,frame=inputs()
 try:
  old=DomainResearch(store,clock=lambda:NOW,adapters={'weather':adapter(e,f)});await old.step(frame)
  before=store.latest('DomainResearchStudy',100)
  new=ExpansionResearch(store,clock=lambda:NOW,adapters={'weather':adapter(e,f)});await new.step(frame)
  assert store.latest('DomainResearchStudy',100)==before
  assert len(store.latest('ExpansionResearchStudy',100))==3 and new.state['forecasts']==1
  assert ExpansionResearch(store,clock=lambda:NOW,adapters={'weather':adapter(e,f)}).state==new.state
  assert DomainResearch(store,clock=lambda:NOW,adapters={'weather':adapter(e,f)}).state==old.state
 finally:store.close()


@pytest.mark.parametrize("fault",["question","end_time","tick_size","min_order_size"])
async def test_supplemental_discovery_is_causal_bounded_and_conflicts_fail_closed(tmp_path,monkeypatch,fault):
 from neraium_poly.research.phase25 import discovery
 store=EventStore(tmp_path/'fixture.sqlite');m,_b,_e,_f,frame=inputs()
 async def discover(**kw):return [m.model_copy(update={'token_id':'extra-token','market_id':'extra-market'})]
 monkeypatch.setattr(discovery,'modules',lambda:{'controlled':SimpleNamespace(discover=discover)})
 try:
  u=discovery.Universe(store,clock=lambda:NOW,can_write=lambda:True)
  merged=await u.frame(frame);assert len(merged.markets)==2 and merged.books==frame.books
  assert store.count(kind='ExpansionDiscoveryStudy')==1
  assert len((await u.frame(frame)).markets)==2 and store.count(kind='ExpansionDiscoveryStudy')==1
  from datetime import timedelta
  changed={'question':'different settlement target','end_time':m.end_time+timedelta(hours=1),'tick_size':.001,'min_order_size':2.}[fault]
  u.cached=[m.model_copy(update={fault:changed}).model_dump(mode='json')]
  with pytest.raises(ValueError,match='identity conflict'):await u.frame(frame)
 finally:store.close()


def test_expansion_monitor_keeps_scope_accounts_and_no_authority_visible():
 from datetime import UTC, datetime

 from neraium_poly.ops.monitor import _render_domain_challengers
 now=datetime.now(UTC).isoformat();service={'paper_trading':True,'live_trading_enabled':False}
 c={'cash':500,'operation':{'service':service}};e={'bankroll':496.115,'generated_at':now,'service':service}
 d={'status':'research_only','last_evaluation_at':now,'forecasts':12,'native_parents':6,'models':{}}
 x={'status':'research_only','last_evaluation_at':now,'forecasts':4,'native_parents':2,'models':{'controlled-new-model':{'forecasts':4,'resolved':0}}}
 text=_render_domain_challengers(c,e,{},d,38,24,(),expansion=x).plain
 for label in ['P25 4 forecasts / 2 parents','25 F4 V0','NO TRADING AUTHORITY','$496.12','$500.00','LIVE TRADING DISABLED']:assert label in text


async def test_expansion_outcomes_use_own_namespace_adapter_and_verified_replay(tmp_path,monkeypatch):
 from datetime import timedelta

 from neraium_poly.research.phase25 import continuous
 store=EventStore(tmp_path/'controlled.sqlite');_m,_b,e,f,frame=inputs();clock=[NOW]
 async def acquire(forecast,**kw):return {'verified':True,'forecast_id':forecast['id']}
 def proof(result,study,forecast,**kw):
  return {**{k:forecast[k] for k in ['event_id','market_id','token_id','rules_sha256']},'verified':True,'forecast_id':forecast['id'],
          'resolved_at':(NOW+timedelta(days=1,hours=1)).isoformat(),'available_at':clock[0].isoformat()}
 module=SimpleNamespace(verify_outcome=acquire,replay=lambda *a,**kw:{'verified':True},replay_outcome=proof)
 monkeypatch.setattr(continuous,'modules',lambda:{'weather':module})
 try:
  r=ExpansionResearch(store,clock=lambda:clock[0],adapters={'weather':adapter(e,f)});await r.step(frame)
  clock[0]+=timedelta(days=2);o=continuous.ExpansionOutcomes(store,tmp_path/'proofs',clock=lambda:clock[0]);await o.step()
  assert len(o.state['verified'])==1 and store.count(kind='DomainOutcomeStudy')==0
  assert store.latest('ExpansionOutcomeStudy',1)[0]['result']['status']=='verified'
  assert continuous.ExpansionOutcomes(store,tmp_path/'proofs',clock=lambda:clock[0]).state==o.state
 finally:store.close()


async def test_empty_external_diagnostic_is_explicit_without_fabricating_a_cause(tmp_path):
 store=EventStore(tmp_path/'fixture.sqlite');_m,_b,e,f,frame=inputs();module=adapter(e,f)
 async def unavailable(*a,**kw):return {'forecasts':[],'evidence':[],'rejections':['']}
 module.forecast=unavailable
 try:
  engine=ExpansionResearch(store,clock=lambda:NOW,adapters={'weather':module})
  assert not await engine.step(frame)
  assert engine.state['rejections'].get('source_unavailable_without_provider_detail')==1
  assert '' not in engine.state['rejections']
 finally:store.close()
