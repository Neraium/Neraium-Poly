"""Controlled engineering fixtures; never authentic research observations."""
import hashlib
import json
import math
from datetime import UTC, datetime, timedelta

import pytest
from neraium_poly.contracts import MarketSnapshot, OrderBookSnapshot, PriceLevel
from neraium_poly.research.phase14.contracts import DomainEvidence
from neraium_poly.research.phase14.relationships import digest
from neraium_poly.research.phase25 import economics, finance

NOW=datetime(2026,11,7,23,tzinfo=UTC)


def market(domain='finance',**changes):
 if domain=='finance':
  question='S&P 500 (SPX) Up or Down on November 9?';rules=finance.RULE.format(day='Monday, November 9, 2026');source=finance.RESOLUTION;end=datetime(2026,11,9,21,tzinfo=UTC);outcome='Up'
 else:
  question='Will UK GDP growth in Q3 2026 be negative?';rules=economics.RULE.format(quarter=3,year=2026,release='November 12, 2026');source=economics.SOURCE;end=datetime(2026,11,13,tzinfo=UTC);outcome='Yes'
 return MarketSnapshot(id='CONTROLLED',timestamp=NOW,available_at=NOW,source='https://gamma-api.polymarket.com',market_id='CONTROLLED-market',event_id='CONTROLLED-parent',token_id='CONTROLLED-token',question=question,resolution_rules=rules,resolution_source=source,status='active',outcome=outcome,probability=.5,end_time=end).model_copy(update=changes)


def evidence(domain='finance'):
 if domain=='finance':
  start=datetime(2023,1,1,tzinfo=UTC);rows=[];n=0
  for i in range(1405):
   t=start+timedelta(days=i)
   if t.weekday()<5:rows.append(t.strftime('%Y-%m-%d')+','+str(4000*math.exp(n*.0002+.03*math.sin(n/5))));n+=1
  body='observation_date,SP500\n'+'\n'.join(rows);url=finance.URL;provider='Federal Reserve Bank of St. Louis FRED';sid='SP500'
 else:
  quarters=[]
  for k in range(2026*4+2-80,2026*4+2):
   y,q=divmod(k,4);quarters.append({'date':f'{y} Q{q+1}','value':str(round(.3+.4*math.sin(k),1)),'updateDate':(NOW-timedelta(days=1)).isoformat()})
  body=json.dumps({'description':{'cdid':'IHYQ','unit':'%','datasetId':'PN2','title':'Gross Domestic Product: Quarter on Quarter growth: CVM SA %','releaseDate':(NOW-timedelta(days=1)).isoformat(),'date':'2026 Q2'},'quarters':quarters});url=economics.URL;provider=economics.PROVIDER;sid='IHYQ'
 p={'request_url':url,'raw_response_utf8':body,'raw_response_sha256':hashlib.sha256(body.encode()).hexdigest()}
 return DomainEvidence(id='CONTROLLED-evidence',timestamp=NOW,available_at=NOW,retrieved_at=NOW,source=url,domain=domain,provider=provider,source_id=sid,payload=p,content_sha256=digest(p),independent_of_polymarket=True,qualification='qualified_research')


def book(m):return OrderBookSnapshot(id='CONTROLLED-book',timestamp=NOW,available_at=NOW,source='https://clob.polymarket.com',market_id=m.market_id,token_id=m.token_id,bids=(PriceLevel(price=.48,size=100),),asks=(PriceLevel(price=.49,size=100),))


@pytest.mark.parametrize('module',[finance,economics])
async def test_probability_replay_prospective_bound_to_actual_inputs(monkeypatch,module):
 m=market('finance' if module is finance else 'economics');e=evidence('finance' if module is finance else 'economics');b=book(m)
 async def source(**kw):return (e,)
 monkeypatch.setattr(module,'collect',source)
 r=await module.forecast(m,b,clock=lambda:NOW);assert len(r['forecasts'])==2
 for f in r['forecasts']:
  f['id']='CONTROLLED-forecast';assert module.replay(f,r['evidence'],as_of=NOW)['verified']
  assert f['market_probability'] is None and f['market_expected_payout']==.485 and f['lower_probability']==0 and f['upper_probability']==1
  assert not f['trading_authority'] and f['calibration_status']=='unvalidated_research'
  wrong={**f,'market':{**f['market'],'question':'wrong'}}
  with pytest.raises(ValueError):module.replay(wrong,r['evidence'],as_of=NOW)
  with pytest.raises(ValueError):module.replay({**f,'probability':.123456},r['evidence'],as_of=NOW)


@pytest.mark.parametrize('module',[finance,economics])
def test_future_or_tampered_source_rejected(module):
 domain='finance' if module is finance else 'economics';m=market(domain);e=evidence(domain);c=module.supports(m,cutoff=NOW)['contract']
 for bad in [e.model_copy(update={'available_at':NOW+timedelta(seconds=1)}),e.model_copy(update={'payload':{'forged':True}})]:
  with pytest.raises((ValueError,KeyError)):module.estimates(c,[bad],cutoff=NOW)


def test_finance_does_not_forecast_spy_opens_pyth_or_changed_resolution():
 for updates in [{'question':'S&P 500 (SPY) Up or Down on November 9?'},{'question':'S&P 500 (SPX) Opens Up or Down on November 9?'},{'resolution_source':'https://pythdata.app'}, {'resolution_rules':market().resolution_rules+' revised'}]:
  assert not finance.supports(market(**updates),cutoff=NOW)['supported']


def test_market_prices_are_not_independent_features():
 for module,domain in [(finance,'finance'),(economics,'economics')]:
  e=evidence(domain);a=module.estimates(module.supports(market(domain,probability=.1),cutoff=NOW)['contract'],[e],cutoff=NOW)
  b=module.estimates(module.supports(market(domain,probability=.9),cutoff=NOW)['contract'],[e],cutoff=NOW)
  assert [r['probability'] for r in a]==[r['probability'] for r in b]


def test_gdp_target_quarter_in_history_is_leakage():
 m=market('economics');e=evidence('economics');p=dict(e.payload);j=json.loads(p['raw_response_utf8']);j['quarters'].append({'date':'2026 Q3','value':'.5','updateDate':NOW.isoformat()});p['raw_response_utf8']=json.dumps(j);p['raw_response_sha256']=hashlib.sha256(p['raw_response_utf8'].encode()).hexdigest();e=e.model_copy(update={'payload':p,'content_sha256':digest(p)})
 with pytest.raises(ValueError,match='pre_target'):economics.estimates(economics.supports(m,cutoff=NOW)['contract'],[e],cutoff=NOW)


def test_gdp_one_decimal_threshold_and_no_release_day_forecast():
 c=economics.supports(market('economics'),cutoff=NOW)['contract']
 assert economics.hit(c,-.05) and not economics.hit(c,-.04)
 assert not economics.supports(market('economics'),cutoff=datetime(2026,11,12,tzinfo=UTC))['supported']


def test_outcome_requires_exact_firstrelease_quarter_and_no_correction():
 c=economics.supports(market('economics'),cutoff=NOW)['contract'];raw=b'<script>{"datePublished":"2026-11-12T00:00:00Z","dateModified":"2026-11-12T00:00:00Z"}</script>Release date: 12 November 2026 UK real gross domestic product (GDP) is estimated to have increased by 0.4% in Quarter 3 (July to Sept) 2026'
 later=datetime(2026,11,13,tzinfo=UTC)
 assert economics.parse_bulletin(c,raw,available_at=later)['expected']==0
 for bad in [raw.replace(b'Quarter 3',b'Quarter 2'),raw+b' Correction',raw.replace(b'2026',b'2027')]:
  with pytest.raises(ValueError):economics.parse_bulletin(c,bad,available_at=later)
 with pytest.raises(ValueError):economics.parse_bulletin(c,raw,available_at=NOW)


async def test_finance_does_not_make_labels_from_fred_or_unsettled_quotes():
 result=await finance.verify_outcome({'event_end_time':(NOW-timedelta(days=1)).isoformat()},directory='unused',clock=lambda:NOW)
 assert not result['verified'] and 'WSJ' in result['reason']
 with pytest.raises(ValueError):finance.replay_outcome({}, {}, {}, evidence_root='unused',as_of=NOW)


async def test_native_ws_fallback_preserves_actual_timestamp_and_raw_hash(monkeypatch):
 m=market();stale=book(m).model_copy(update={'timestamp':NOW-timedelta(minutes=1)})
 raw={'event_type':'book','asset_id':m.token_id,'timestamp':str(int(NOW.timestamp()*1000)),
      'bids':[{'price':'.48','size':'100'}],'asks':[{'price':'.49','size':'100'}]}
 class Adapter:
  def __init__(self,**kw):pass
  async def book(self,*args):return stale
  async def close(self):pass
 class Socket:
  async def __aenter__(self):return self
  async def __aexit__(self,*args):pass
  async def send(self,message):assert json.loads(message)['assets_ids']==[m.token_id]
  async def recv(self):return json.dumps([raw])
 monkeypatch.setattr(finance,'OperationalPolymarketAdapter',Adapter);monkeypatch.setattr(finance,'connect',lambda *a,**kw:Socket())
 received=NOW+timedelta(seconds=3);b=await finance.fresh_book(m,stale,lambda:received)
 assert b.timestamp==NOW and b.available_at==received and b.source==finance.WS
 f=finance.bind_predictions([{}],m,b,received)[0];finance.replay_book_provenance(f,m,b,received)
 f['native_book_provenance']={**f['native_book_provenance'],'raw_sha256':'0'*64}
 with pytest.raises(ValueError):finance.replay_book_provenance(f,m,b,received)


async def test_native_ws_cancel_closes_socket_and_never_restamps_stale_book(monkeypatch):
 import asyncio
 m=market();stale=book(m).model_copy(update={'timestamp':NOW-timedelta(minutes=1)});closed=[]
 class Adapter:
  def __init__(self,**kw):pass
  async def book(self,*args):return stale
  async def close(self):pass
 class Socket:
  async def __aenter__(self):return self
  async def __aexit__(self,*args):closed.append(True)
  async def send(self,*args):pass
  async def recv(self):await asyncio.sleep(60)
 monkeypatch.setattr(finance,'OperationalPolymarketAdapter',Adapter);monkeypatch.setattr(finance,'connect',lambda *a,**kw:Socket())
 with pytest.raises(TimeoutError):await asyncio.wait_for(finance.fresh_book(m,stale,lambda:NOW),timeout=.01)
 assert closed==[True] and stale.timestamp==NOW-timedelta(minutes=1)


def test_ons_modified_publication_is_not_initial_release():
 c=economics.supports(market('economics'),cutoff=NOW)['contract']
 raw=b'<script>{"datePublished":"2026-11-12T00:00:00Z","dateModified":"2026-11-13T00:00:00Z"}</script>Release date: 12 November 2026 UK real gross domestic product (GDP) is estimated to have increased by 0.4% in Quarter 3 (July to Sept) 2026'
 with pytest.raises(ValueError,match='unchanged_original'):economics.parse_bulletin(c,raw,available_at=datetime(2026,11,14,tzinfo=UTC))
