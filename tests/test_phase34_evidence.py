"""Controlled model/depth/provenance cases, not authentic forecasting results."""
from copy import deepcopy
from datetime import timedelta

import pytest
from neraium_poly.contracts import OrderBookSnapshot
from neraium_poly.research.phase14.relationships import digest
from neraium_poly.research.phase24 import weather
from neraium_poly.research.phase34.weather import weather_economic_diagnostic
from test_phase24_weather_economics import NOW, book, market, weather_evidence
from test_phase29_economics import Store


async def original(monkeypatch):
    async def collect(*args,**kwargs):return weather_evidence()
    monkeypatch.setattr(weather,'collect',collect)
    m=market(side='No');b=book(m).model_dump(mode='json');b.update(bids=[{'price':.01,'size':100}],asks=[{'price':.02,'size':100},{'price':.03,'size':100}])
    r=await weather.forecast(m,OrderBookSnapshot.model_validate(b),clock=lambda:NOW)
    f=r['forecasts'][0];f['id']='CONTROLLED'
    return f,r['evidence']


def fees(f,offset=0):
    token=f['token_id'];stamp=(NOW+timedelta(seconds=offset)).isoformat();origin='https://clob.polymarket.com'
    parent={'condition_id':'C','primary_token_id':token,'secondary_token_id':'other'}
    details={'c':'C','t':[{'t':token}],'fd':{'r':.05,'e':1,'to':True}}
    rs={}
    for i,(payload,path) in enumerate([(parent,'/markets-by-token/'+token),(details,'/clob-markets/C')]):
        rs[str(i)]={'id':str(i),'source':origin,'timestamp':stamp,'available_at':stamp,'url':origin+path,'payload':payload,'content_sha256':digest(payload)}
    rs['O']={'id':'O','source':origin,'timestamp':stamp,'available_at':stamp,'token_id':token,'fee_rate':.05,'raw_response_ids':['0','1']}
    return Store(rs),{'evidence_id':'O'}


async def test_multilevel_point_margin_does_not_become_uncertainty_or_native_profit(monkeypatch):
    f,e=await original(monkeypatch);store,obs=fees(f)
    r=weather_economic_diagnostic(f,e,as_of=NOW,store=store,fee_observation=obs)
    assert r['status']=='original_quote_research_sensitivity'
    assert r['point_gross_optimal_quantity']==pytest.approx(20)
    assert r['point_gross_optimal_principal']==pytest.approx(.5)
    assert len(r['original_quantity_book_levels'])==2
    expected_fee=10*.05*.02*.98+10*.05*.03*.97
    assert r['unrounded_native_formula_fee']==pytest.approx(expected_fee)
    assert r['conditional_point_profit_after_formula_fee']==pytest.approx(r['point_expected_gross_profit']-expected_fee)
    assert r['break_even_probability_before_unknown_costs']==pytest.approx((.5+expected_fee)/20)
    assert r['lower_expected_gross_profit_at_same_quantity']==pytest.approx(-.5)
    assert r['conservative_expected_net_profit'] is None and not r['qualified_opportunity']
    assert not r['market_probability_comparable'] and r['market_baseline_superiority'] is None
    assert not r['trading_authority'] and not r['actual_fill']


@pytest.mark.parametrize('fault',['future_fee','wrong_fee_token','corrupt_fee_payload','missing_fee'])
async def test_unknown_or_later_fee_evidence_never_becomes_historical_zero_fee(monkeypatch,fault):
    f,e=await original(monkeypatch);store,obs=fees(f,1 if fault=='future_fee' else 0)
    if fault=='wrong_fee_token':store.records['O']['token_id']='WRONG'
    if fault=='corrupt_fee_payload':store.records['1']['payload']['fd']['r']=0
    if fault=='missing_fee':obs=None
    r=weather_economic_diagnostic(f,e,as_of=NOW+timedelta(seconds=2),store=store,fee_observation=obs)
    assert r['status']=='original_quote_research_sensitivity'
    assert r['unrounded_native_formula_fee'] is None
    assert r['maximum_unknown_cost_budget_at_point'] is None and r['conservative_expected_net_profit'] is None
    assert 'causal_original_native_fee_evidence_missing' in r['rejections']


@pytest.mark.parametrize('fault',['probability','token','book','evidence','future_forecast'])
async def test_original_model_and_book_binding_required(monkeypatch,fault):
    f,e=await original(monkeypatch);f=deepcopy(f);e=deepcopy(e)
    if fault=='probability':f['probability']=.999
    elif fault=='token':f['token_id']='WRONG'
    elif fault=='book':f['book']['asks'][0]['size']=999
    elif fault=='evidence':e[0]['payload']['raw_response_utf8']='[]'
    else:f['timestamp']=(NOW+timedelta(seconds=2)).isoformat()
    r=weather_economic_diagnostic(f,e,as_of=NOW)
    assert r['status']=='withheld' and r['rejections'] and r['conservative_expected_net_profit'] is None


async def test_later_replay_of_original_depth_is_historical_not_current_liquidity(monkeypatch):
    f,e=await original(monkeypatch)
    r=weather_economic_diagnostic(f,e,as_of=NOW+timedelta(days=2))
    assert r['status']=='original_quote_research_sensitivity'
    assert 'original_book_not_current_executable_liquidity' in r['rejections']
    assert 'original_weather_event_ended' in r['rejections']
    assert not r['qualified_opportunity']


def selection_case():
    from neraium_poly.experimental.contracts import SharedMarketFrame
    m=market();fresh=book(m);bad=m.model_copy(update={'id':'CONTROLLED-M2','market_id':'M2','token_id':'T2'})
    # Same real-shaped parent and station-day, a separate exact threshold token.
    # The fixture's question/rules still independently pass the existing mapper.
    stale=fresh.model_copy(update={'id':'CONTROLLED-B2','market_id':'M2','token_id':'T2','timestamp':NOW-timedelta(seconds=20),'available_at':NOW-timedelta(seconds=20)})
    return SharedMarketFrame(timestamp=NOW,available_at=NOW,source='CONTROLLED-public-shaped',producer_health={'status':'ok'},markets=(m,bad),books=(fresh,stale))


def test_fresh_station_day_sibling_cannot_lose_source_slot_to_stale_retry():
    from neraium_poly.research.phase34.selection import prepare_weather_frame
    frame=selection_case();selected,r=prepare_weather_frame(frame,as_of=NOW)
    assert r['preferred_tokens']==[frame.markets[0].token_id] and r['deferred_tokens']==['T2']
    assert len(selected.markets)==len(selected.books)==1
    assert selected.books[0]==frame.books[0] and selected.markets[0]==frame.markets[0]
    assert len(frame.markets)==2 and frame.books[1].timestamp==NOW-timedelta(seconds=20)
    assert not r['trading_authority'] and r['policy_sha256']


def test_missing_all_fresh_quotes_preserves_bounded_provider_fallback():
    from neraium_poly.research.phase34.selection import prepare_weather_frame
    frame=selection_case();frame=frame.model_copy(update={'books':(frame.books[1],)})
    selected,r=prepare_weather_frame(frame,as_of=NOW)
    assert selected==frame and not r['deferred_tokens'] and not r['preferred_tokens']


@pytest.mark.parametrize('fault',['wrong_market','future_receipt','wide_spread','nonpublic_source'])
def test_unqualified_sibling_never_becomes_preferred(fault):
    from neraium_poly.research.phase34.selection import prepare_weather_frame
    frame=selection_case();b=frame.books[0].model_dump(mode='json')
    if fault=='wrong_market':b['market_id']='WRONG'
    elif fault=='future_receipt':b['available_at']=(NOW+timedelta(seconds=1)).isoformat()
    elif fault=='wide_spread':b['asks']=[{'price':.7,'size':100}]
    else:b['source']='https://untrusted.example'
    frame=frame.model_copy(update={'books':(OrderBookSnapshot.model_validate(b),frame.books[1])})
    selected,r=prepare_weather_frame(frame,as_of=NOW)
    assert selected==frame and not r['preferred_tokens'] and not r['deferred_tokens']


def test_conflicting_tokens_and_future_frames_fail_closed():
    from neraium_poly.research.phase34.selection import prepare_weather_frame
    frame=selection_case()
    with pytest.raises(ValueError):prepare_weather_frame(frame.model_copy(update={'markets':(frame.markets[0],frame.markets[0])}),as_of=NOW)
    with pytest.raises(ValueError):prepare_weather_frame(frame,as_of=NOW-timedelta(seconds=1))


def test_weather_subscription_slots_prefer_central_bins_without_changing_parent_or_budget():
    from neraium_poly.research.phase34.selection import select_weather_aware_supplemental_markets
    m=market();extreme=m.model_copy(update={'id':'CONTROLLED-extreme','market_id':'00001','token_id':'EXTREME','probability':.99})
    central=m.model_copy(update={'id':'CONTROLLED-central','market_id':'00002','token_id':'CENTRAL','probability':.5})
    rows,r=select_weather_aware_supplemental_markets([extreme,central],base_tokens=set(),adapters={'weather':weather},as_of=NOW,maximum=1)
    assert [m.token_id for m in rows]==['CENTRAL'] and r['selected_parent_events']==1
    assert r['selected_tokens']==1 and r['weather_replacements']
    rows,_=select_weather_aware_supplemental_markets([extreme,central],base_tokens=set(),adapters={'weather':weather},as_of=NOW,maximum=1,forecast_tokens=['EXTREME'])
    assert [m.token_id for m in rows]==['EXTREME']


def test_weather_subscription_never_duplicates_base_tokens_or_reserved_forecast():
    from neraium_poly.research.phase34.selection import select_weather_aware_supplemental_markets
    m=market();a=m.model_copy(update={'id':'A','market_id':'01','token_id':'A','probability':.99});b=m.model_copy(update={'id':'B','market_id':'02','token_id':'B','probability':.5})
    rows,_=select_weather_aware_supplemental_markets([a,b],base_tokens={'B'},adapters={'weather':weather},as_of=NOW,maximum=2)
    assert [m.token_id for m in rows]==['A']
    rows,_=select_weather_aware_supplemental_markets([a,b],base_tokens=set(),adapters={'weather':weather},as_of=NOW,maximum=2,forecast_tokens=['B'])
    assert len(rows)==len({m.token_id for m in rows})==2
