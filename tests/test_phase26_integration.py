"""Controlled pipeline fixtures only; no genuine performance observations."""
from datetime import timedelta
from types import SimpleNamespace

from neraium_poly.data import EventStore
from neraium_poly.research.phase25.competition import executable_diagnostic
from neraium_poly.research.phase26 import coordination
from test_phase24_integration import NOW, inputs
from test_phase25_competition import fixture


class Watcher:
 def __init__(self,books=()):self.books=books;self.updated=[];self.closed=False
 async def update(self,markets):self.updated=markets
 def snapshot(self):return self.books
 async def wait_fresh(self,**kw):return self.books
 def status(self):return {'qualified_books':len(self.books),'trading_authority':False}
 async def close(self):self.closed=True


def supported():
 yes=SimpleNamespace(supports=lambda *a,**kw:{'supported':True})
 no=SimpleNamespace(supports=lambda *a,**kw:{'supported':False})
 return {'finance':yes,'economics':no}


async def test_preflight_merges_native_inputs_without_restamping_and_policy_recovers(tmp_path,monkeypatch):
 store=EventStore(tmp_path/'controlled.sqlite');m,b,_e,_f,frame=inputs();watcher=Watcher((b,))
 monkeypatch.setattr(coordination,'modules',supported)
 try:
  c=coordination.Inputs(store,clock=lambda:NOW,can_write=lambda:True,watcher=watcher)
  merged=await c.prepare(frame.model_copy(update={'books':()}),base_tokens=set(),wait=True)
  assert merged.books==(b,) and merged.markets==(m,) and merged.books[0].timestamp==b.timestamp
  assert store.count(kind='ResearchInputPolicy')==1
  again=coordination.Inputs(store,clock=lambda:NOW,can_write=lambda:True,watcher=Watcher())
  assert again.policy_id==c.policy_id and store.count(kind='ResearchInputPolicy')==1
  await c.close();assert watcher.closed
 finally:store.close()


async def test_preflight_withholds_stale_books_and_records_reason(tmp_path,monkeypatch):
 store=EventStore(tmp_path/'controlled.sqlite');_m,b,_e,_f,frame=inputs()
 monkeypatch.setattr(coordination,'modules',supported)
 try:
  old=b.model_copy(update={'timestamp':NOW-timedelta(seconds=16)})
  c=coordination.Inputs(store,clock=lambda:NOW,can_write=lambda:True,watcher=Watcher())
  merged=await c.prepare(frame.model_copy(update={'books':(old,)}),base_tokens=set())
  assert not merged.markets and not merged.books
  assert 'stale_book' in c.rejections
  row=store.latest('ResearchInputObservation',1)[0];assert row['counts']=={'considered':1,'qualified':0,'withheld':1}
 finally:store.close()


async def test_native_book_sampling_is_bounded_and_budget_fail_closed(tmp_path):
 store=EventStore(tmp_path/'controlled.sqlite');_m,b,*_=inputs();budget=[True];clock=[NOW]
 try:
  c=coordination.Inputs(store,clock=lambda:clock[0],can_write=lambda:budget[0],watcher=Watcher())
  await c.on_book(b);await c.on_book(b)
  assert store.count(kind='ResearchInputObservation')==1 and c.counts['sampling_skips']==1
  clock[0]+=timedelta(seconds=61);budget[0]=False;await c.on_book(b)
  assert store.count(kind='ResearchInputObservation')==1 and c.counts['archive_backpressure']==1
 finally:store.close()


def test_close_time_is_not_invented_settlement_capital_lockup():
 _s,f=fixture();r=executable_diagnostic(f,evaluated_at=NOW,forecast_verified=True)
 assert r['capacity']['expected_capital_lockup_seconds'] is None
 assert r['capacity']['time_to_forecast_cutoff_seconds']==7200
 assert r['capacity']['capital_lockup_status']=='settlement_and_redemption_timing_unverified'
 assert not r['execution_authorized']


def test_outcome_check_can_run_earlier_without_weakening_finality():
 from neraium_poly.research.phase24.outcomes import DomainOutcomes
 from neraium_poly.research.phase26.routing import OfficialDomainOutcomes
 p={'adapter':'sports','end':NOW.isoformat()}
 assert OfficialDomainOutcomes._due(None,p,NOW+timedelta(hours=1))
 assert not DomainOutcomes._due(None,p,NOW+timedelta(hours=1))
