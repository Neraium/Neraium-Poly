"""Controlled routing fixtures only; never genuine opportunity or performance data."""
import hashlib
from datetime import timedelta
from types import SimpleNamespace

import pytest
from neraium_poly.research.phase26 import coordination
from neraium_poly.research.phase26.books import SupplementalBooks
from neraium_poly.research.phase28.inputs import current_frame
from neraium_poly.research.phase29.alignment import classify_alignment, select_supplemental_markets
from test_phase24_integration import inputs
from test_phase26_books import NOW, FakeFeed, book, market


def forecast(m,**updates):
    return {'id':'forecast-'+m.token_id,'event_id':m.event_id,'market_id':m.market_id,'token_id':m.token_id,
        'timestamp':NOW.isoformat(),'event_end_time':m.end_time.isoformat(),
        'rules_sha256':hashlib.sha256(m.resolution_rules.encode()).hexdigest(),**updates}


def frame_for(markets,books):
    *_,frame=inputs()
    return frame.model_copy(update={'timestamp':NOW,'available_at':NOW,'markets':tuple(markets),'books':tuple(books)})


def adapter_for(prefix):
    return SimpleNamespace(supports=lambda m,**kw:{'supported':(m['token_id'] if isinstance(m,dict) else m.token_id).startswith(prefix)})


def test_subscription_selects_supported_weather_and_sports_not_only_finance_and_economics():
    adapters={n:adapter_for(n) for n in ['finance','economics','weather','sports']}
    values=[market(n).model_copy(update={'event_id':n}) for n in adapters]
    selected,counts=select_supplemental_markets(values,base_tokens={'finance'},adapters=adapters,as_of=NOW)
    assert {m.token_id for m in selected}=={'economics','weather','sports'}
    assert counts['selected_domains']=={'economics':1,'sports':1,'weather':1} and not counts['trading_authority']


def test_selection_is_bounded_deterministic_event_diverse_and_forecast_prioritized():
    values=[market('sports'+str(i)).model_copy(update={'event_id':'parent'+str(i//2)}) for i in range(40)]
    adapters={'sports':adapter_for('sports')}
    chosen,counts=select_supplemental_markets(values,base_tokens=set(),adapters=adapters,as_of=NOW,maximum=5,forecast_tokens={'sports38'})
    again,_=select_supplemental_markets(list(reversed(values)),base_tokens=set(),adapters=adapters,as_of=NOW,maximum=5,forecast_tokens={'sports38'})
    assert chosen==again and chosen[0].token_id=='sports38'
    assert len(chosen)==5 and len({m.event_id for m in chosen})==5 and counts['deferred_tokens']==35
    with pytest.raises(ValueError,match='32_token'):select_supplemental_markets(values,base_tokens=set(),adapters=adapters,as_of=NOW,maximum=33)
    with pytest.raises(ValueError,match='ambiguous'):select_supplemental_markets(values+[values[0].model_copy(update={'outcome':'wrong'})],base_tokens=set(),adapters=adapters,as_of=NOW)


async def test_raw_native_diagnostics_are_not_executable_freshness_or_archive_samples():
    m=market();feed=FakeFeed();w=SupplementalBooks(clock=lambda:NOW,feed=feed)
    try:
        await w.update([m]);old=book(m,timestamp=NOW-timedelta(seconds=20));feed.latest[m.token_id]=old
        assert w.snapshot()==() and w.observations()==(old,)
        status=w.status();assert status['token_diagnostics'][m.token_id]['reasons']==['stale_book']
        merged=current_frame(frame_for([m],[]),extra_markets=[m],extra_books=w.observations(),as_of=NOW)
        assert merged.books[0].timestamp==old.timestamp and merged.books[0].available_at==old.available_at
        result=classify_alignment([forecast(m)],merged,as_of=NOW,subscribed_tokens={m.token_id},supplemental_status=status)
        assert result['findings'][0]['category']=='MARKET_DATA_QUALITY'
        assert 'stale_book' in result['findings'][0]['reasons'] and result['counts']['authentically_matched_executable_books']==0
        feed.latest.clear();feed._gap_watermarks={m.token_id:NOW}
        assert not w.observations() and w.status()['token_diagnostics'][m.token_id]['reasons']==['transport_gap_withheld']
    finally:await w.close()


@pytest.mark.parametrize('kind,category',[
    ('closed','EVENT_LIFECYCLE'),('not_discovered','DISCOVERY_COVERAGE'),
    ('not_subscribed','SUBSCRIPTION_COVERAGE'),('missing','MARKET_DATA_UNAVAILABLE'),
    ('gap','TRANSPORT_INTEGRITY'),('wrong_token_market','IDENTITY_DEFECT'),('matched','MATCHED_EXECUTABLE_BOOK')])
def test_alignment_attributes_exact_join_failure_without_inventing_liquidity(kind,category):
    m=market();f=forecast(m);markets=[m];books=[];tokens={m.token_id};status={}
    if kind=='closed':markets=[];f['event_end_time']=(NOW-timedelta(hours=1)).isoformat()
    if kind=='not_discovered':markets=[]
    if kind=='not_subscribed':tokens=set()
    if kind=='gap':status={'token_diagnostics':{m.token_id:{'reasons':['transport_gap_withheld']}}}
    if kind=='wrong_token_market':books=[book(m,market_id='unrelated')]
    if kind=='matched':books=[book(m)]
    result=classify_alignment([f],frame_for(markets,books),as_of=NOW,subscribed_tokens=tokens,supplemental_status=status)
    row=result['findings'][0]
    assert row['category']==category and row['current_executable_book_matched'] is (kind=='matched')
    assert result['trading_authority'] is False and result['certification_authority'] is False


def test_old_forecast_can_have_matched_book_without_current_execution_authority():
    m=market();b=book(m);f=forecast(m,timestamp=(NOW-timedelta(hours=1)).isoformat())
    result=classify_alignment([f],frame_for([m],[b]),as_of=NOW)
    row=result['findings'][0];assert row['current_executable_book_matched'] and not row['forecast_current']
    assert result['counts']['current_forecasts_with_executable_books']==0
    assert row['book_source_timestamp']==b.timestamp.isoformat() and not row['trading_authority']


def test_current_frame_rejects_outcome_and_resolution_reference_alias_changes():
    m=market();base=frame_for([m],[book(m)])
    for changed in [m.model_copy(update={'outcome':'wrong'}),m.model_copy(update={'resolution_source':'https://unrelated.example'})]:
        with pytest.raises(ValueError,match='conflicting_supplemental_market_identity'):current_frame(base,extra_markets=[changed],as_of=NOW)


async def test_prepare_subscribes_supported_nonfinancial_contract_without_relaxing_quality(tmp_path,monkeypatch):
    from neraium_poly.data import EventStore
    from test_phase26_integration import Watcher
    monkeypatch.setattr(coordination,'modules',lambda:{'sports':adapter_for('sports'),'finance':adapter_for('finance'),'economics':adapter_for('economics')})
    m=market('sports');w=Watcher();store=EventStore(tmp_path/'controlled.sqlite')
    try:
        c=coordination.Inputs(store,clock=lambda:NOW,can_write=lambda:True,watcher=w)
        await c.prepare(frame_for([m],[]),base_tokens=set(),forecast_tokens={m.token_id})
        assert [v.token_id for v in w.updated]==[m.token_id]
        assert c.status()['selection']['selected_domains']=={'sports':1}
    finally:store.close()
