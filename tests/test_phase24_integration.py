"""Controlled contracts only: these fixtures are never authentic research results."""
import asyncio
import hashlib
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from neraium_poly.contracts import MarketSnapshot, OrderBookSnapshot, PriceLevel
from neraium_poly.data import EventStore
from neraium_poly.experimental.contracts import SharedMarketFrame
from neraium_poly.research.phase14.contracts import DomainEvidence
from neraium_poly.research.phase14.relationships import digest
from neraium_poly.research.phase24.continuous import DomainResearch
from neraium_poly.research.phase24.operations import combined_report
from neraium_poly.research.phase24.outcomes import DomainOutcomes

NOW=datetime(2026,11,7,23,tzinfo=UTC)


def inputs():
 m=MarketSnapshot(id='controlled-market',timestamp=NOW,available_at=NOW,source='https://gamma-api.polymarket.com',
    market_id='controlled-market',event_id='controlled-parent',token_id='controlled-token',question='Controlled precise target?',
    probability=.5,status='active',resolution_rules='Controlled exact final-source rule',resolution_source='https://official.example/result',end_time=NOW+timedelta(days=1))
 b=OrderBookSnapshot(id='controlled-book',timestamp=NOW,available_at=NOW,source='https://clob.polymarket.com',
    market_id=m.market_id,token_id=m.token_id,bids=(PriceLevel(price=.45,size=100),),asks=(PriceLevel(price=.46,size=100),))
 e=DomainEvidence(id='controlled-evidence',timestamp=NOW,available_at=NOW,retrieved_at=NOW,source='https://official.example/data',
    domain='weather',provider='CONTROLLED',source_id='CONTROLLED',content_sha256=digest({'controlled':True}),payload={'controlled':True},
    qualification='qualified_research',independent_of_polymarket=True)
 f={'model_id':'controlled-model','model_version':'controlled-model','model_sha256':'1'*64,'feature_version':'controlled-v1',
    'domain':'weather','event_id':m.event_id,'market_id':m.market_id,'token_id':m.token_id,'probability':.6,'probability_semantics':'binary_event_probability',
    'timestamp':NOW.isoformat(),'evidence_cutoff':NOW.isoformat(),'event_end_time':m.end_time.isoformat(),'rules_sha256':hashlib.sha256(m.resolution_rules.encode()).hexdigest(),
    'lower_probability':0.,'upper_probability':1.,'dataset_sha256':'2'*64,'evidence_ids':[e.id],'source_lineages':['CONTROLLED'],
    'target_conditioning':'controlled_valid_source','unconditional_contract_probability':False,
    'research_only':True,'trading_authority':False,'certification_authority':False}
 frame=SharedMarketFrame(id='controlled-frame',timestamp=NOW,available_at=NOW,source='controlled-fixture',producer_health={'status':'ok'},markets=(m,),books=(b,))
 return m,b,e,f,frame


def adapter(e,f):
 async def predict(*a,**kw):return {'forecasts':[deepcopy(f)],'evidence':[e.model_dump(mode='json')],'rejections':[]}
 return SimpleNamespace(definitions=lambda:[{'model_id':f['model_id'],'model_version':f['model_id'],'model_sha256':f['model_sha256']}],
    supports=lambda m,cutoff:{'supported':True,'reasons':[]},forecast=predict)


async def test_real_frame_separate_enrollment_recovery_and_conditional_leaderboard(tmp_path):
 store=EventStore(tmp_path/'controlled.sqlite');_m,_b,e,f,frame=inputs()
 try:
  runtime=DomainResearch(store,clock=lambda:NOW,adapters={'weather':adapter(e,f)})
  assert await runtime.step(frame)
  assert store.count(kind='ChallengerStudy')==0 and store.count(kind='DomainResearchStudy')==3
  row=store.latest('DomainResearchStudy',1)[0];assert len(row['forecasts'])==1
  forecast=row['forecasts'][0];assert forecast['market_probability'] is None and forecast['market_expected_payout']==.455
  recovered=DomainResearch(store,clock=lambda:NOW,adapters={'weather':adapter(e,f)})
  assert recovered.state==runtime.state and not await recovered.step(frame)
  report=combined_report(store,as_of=NOW,evidence_root=tmp_path/'proofs')
  assert report['counts']['forecasts']==1 and report['counts']['pending_forecasts']==1
  assert report['leaderboard'][0]['metrics'] is None and not report['trading_authority']
  outcomes=DomainOutcomes(store,tmp_path/'proofs',clock=lambda:NOW)
  assert not await outcomes.step() and outcomes.status()['pending_forecasts']==1
  again=DomainOutcomes(store,tmp_path/'proofs',clock=lambda:NOW)
  assert again.state==outcomes.state
 finally:store.close()


@pytest.mark.parametrize('fault',['top_identity','question','reference','other_adapter','source_future','stale_at_commit','duplicate_evidence'])
def test_domain_boundary_rejects_mismatched_or_unavailable_inputs(tmp_path,fault):
 store=EventStore(tmp_path/'controlled.sqlite');m,b,e,f,_=inputs();runtime=DomainResearch(store,clock=lambda:NOW,adapters={'weather':adapter(e,f)})
 try:
  evidence=[e];end=NOW;name='weather'
  if fault=='top_identity':f['event_id']='wrong'
  elif fault=='question':f['market']={**m.model_dump(mode='json'),'question':'wrong target'}
  elif fault=='reference':f['market']={**m.model_dump(mode='json'),'resolution_source':'https://wrong.example'}
  elif fault=='other_adapter':name='sports'
  elif fault=='source_future':evidence=[e.model_copy(update={'available_at':NOW+timedelta(seconds=1)})]
  elif fault=='stale_at_commit':end=NOW+timedelta(seconds=16)
  else:evidence=[e,e.model_copy(update={'payload':{'different':True}})]
  with pytest.raises(ValueError):runtime._validate(f,evidence,m,b,ended=end,adapter=name)
 finally:store.close()


async def test_missing_source_book_is_fetched_without_restamping_or_weakening(tmp_path):
 store=EventStore(tmp_path/'controlled.sqlite');m,b,e,f,frame=inputs();calls=[]
 async def get_book(market):calls.append(market.token_id);return b
 try:
  runtime=DomainResearch(store,clock=lambda:NOW,adapters={'weather':adapter(e,f)},book_provider=get_book)
  assert await runtime.step(frame.model_copy(update={'books':()}))
  assert calls==[m.token_id] and store.latest('DomainResearchStudy',1)[0]['forecasts'][0]['book']['timestamp']==b.timestamp.isoformat().replace('+00:00','Z')
 finally:store.close()


async def test_budget_denial_and_interrupted_append_preserve_model_state(tmp_path,monkeypatch):
 store=EventStore(tmp_path/'controlled.sqlite');_m,_b,e,f,frame=inputs()
 try:
  r=DomainResearch(store,clock=lambda:NOW,adapters={'weather':adapter(e,f)},can_write=lambda:False)
  assert not await r.step(frame) and not r.state['enrolled']
  r.can_write=lambda:True;before=digest(r.state)
  def fail(_r):raise OSError('CONTROLLED disk full')
  monkeypatch.setattr(store,'append',fail)
  with pytest.raises(OSError):await r.step(frame)
  assert digest(r.state)==before
 finally:store.close()


async def test_domain_loop_shutdown_cancels_source_work_before_store_close():
 from neraium_poly.experimental.runtime import ExperimentalRuntime
 entered=asyncio.Event();cancelled=asyncio.Event();stop=False
 async def blocked(frame):
  entered.set()
  try:await asyncio.sleep(60)
  finally:cancelled.set()
 runtime=ExperimentalRuntime.__new__(ExperimentalRuntime);runtime.stopping=False;runtime.last_frame={};runtime._research_source_lock=asyncio.Lock()
 runtime.phase24=SimpleNamespace(step=blocked);runtime.phase24_outcomes=None
 task=asyncio.create_task(runtime._domain_research_loop(lambda:stop))
 try:
  await asyncio.wait_for(entered.wait(),2);stop=True
  await asyncio.wait_for(task,3);assert cancelled.is_set()
 finally:task.cancel();await asyncio.gather(task,return_exceptions=True)


async def test_same_parent_threshold_does_not_inflate_forecasts_and_clock_ties_recover(tmp_path):
 store=EventStore(tmp_path/'controlled.sqlite');m,b,e,f,frame=inputs();clock=[NOW];predictions=[]
 module=adapter(e,f)
 async def predict(market,book,**kw):
  value=deepcopy(f);value.update(market_id=market.market_id,token_id=market.token_id,timestamp=clock[0].isoformat())
  predictions.append(market.market_id)
  return {'forecasts':[value],'evidence':[e.model_dump(mode='json')],'rejections':[]}
 module.forecast=predict
 try:
  r=DomainResearch(store,clock=lambda:clock[0],adapters={'weather':module});assert await r.step(frame)
  assert DomainResearch(store,clock=lambda:clock[0],adapters={'weather':module}).state==r.state
  clock[0]+=timedelta(seconds=301)
  other=m.model_copy(update={'id':'other','market_id':'other','token_id':'other-token'})
  book=b.model_copy(update={'id':'other-book','market_id':'other','token_id':'other-token','timestamp':clock[0],'available_at':clock[0]})
  next_frame=frame.model_copy(update={'id':'next','timestamp':clock[0],'available_at':clock[0],'markets':(other,),'books':(book,)})
  assert not await r.step(next_frame) and r.state['forecasts']==1 and len(predictions)==1
 finally:store.close()


def test_archive_read_budget_reduces_view_without_mutating_originals(tmp_path,monkeypatch):
 from neraium_poly.research.phase24 import archive
 (tmp_path/'events-archive.sqlite').touch();calls=[]
 class Reader:
  def __init__(self,*a,**kw):assert kw['max_query_bytes']==32*1024**2
  def __enter__(self):return self
  def __exit__(self,*a):pass
  def latest(self,kind,*,limit):
   calls.append(limit)
   if limit>64:raise ValueError('archive query byte budget exceeded')
   return [{'id':'controlled-original'}]
 monkeypatch.setattr(archive,'ReadonlyArchive',Reader)
 assert archive.latest(SimpleNamespace(directory=tmp_path),'DomainResearchStudy')==[{'id':'controlled-original'}]
 assert calls==[256,128,64]


def test_phone_registry_view_preserves_accounts_safety_and_stale_warning():
 from neraium_poly.ops.monitor import _render_domain_challengers
 now=datetime.now(UTC).isoformat();service={'paper_trading':True,'live_trading_enabled':False}
 cert={'cash':500,'operation':{'service':service}}
 exp={'bankroll':496.115,'generated_at':now,'service':service}
 domain={'status':'research_only','last_evaluation_at':now,'forecasts':14,'native_parents':7,
         'models':{f'controlled-model-{i}':{'forecasts':2,'resolved':0} for i in range(8)}}
 for width in (32,38,80):
  text=_render_domain_challengers(cert,exp,{'forecasts':18,'models':{}},domain,width,24,()).plain
  assert 'P24 14' in text and 'F2 V0' in text and '$496.12' in text and '$500.00' in text
  assert 'LIVE TRADING DISABLED' in text and max(map(len,text.splitlines()))<=width
 stale={**domain,'last_evaluation_at':'2020-01-01T00:00:00Z'}
 assert 'unavailable / stale' in _render_domain_challengers(cert,exp,{},stale,38,24,()).plain


@pytest.mark.parametrize('replay_valid',[True,False])
async def test_outcome_adapter_verified_boolean_requires_replay_before_normalizing_status(tmp_path,monkeypatch,replay_valid):
 from neraium_poly.research.phase24 import outcomes
 store=EventStore(tmp_path/'controlled.sqlite');_m,_b,e,f,frame=inputs();clock=[NOW];calls=[]
 try:
  r=DomainResearch(store,clock=lambda:clock[0],adapters={'weather':adapter(e,f)});await r.step(frame)
  clock[0]+=timedelta(days=2)
  async def acquire(forecast,**kw):return {'verified':True,'forecast_id':forecast['id']}
  def replay_result(result,study,forecast,**kw):
   calls.append(forecast['id'])
   return {**{k:forecast[k] for k in ['event_id','market_id','token_id','rules_sha256']},'forecast_id':forecast['id'],
           'verified':replay_valid,'resolved_at':(NOW+timedelta(days=1,hours=1)).isoformat(),'available_at':clock[0].isoformat()}
  module=SimpleNamespace(verify_outcome=acquire,replay=lambda *a,**kw:{'verified':True},replay_outcome=replay_result)
  monkeypatch.setattr(outcomes.importlib,'import_module',lambda name:module)
  scheduler=DomainOutcomes(store,tmp_path/'proofs',clock=lambda:clock[0]);await scheduler.step()
  result=store.latest('DomainOutcomeStudy',1)[0]['result']
  assert bool(scheduler.state['verified'])==replay_valid
  assert result['status']==('verified' if replay_valid else 'withheld') and len(calls)==1
  recovered=DomainOutcomes(store,tmp_path/'proofs',clock=lambda:clock[0]);assert recovered.state==scheduler.state
  report=combined_report(store,as_of=clock[0],evidence_root=tmp_path/'proofs')
  assert report['counts']['individually_verified_forecasts']==int(replay_valid)
 finally:store.close()
