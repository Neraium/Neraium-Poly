"""Frozen exploratory bid-mark replay on immutable authentic archive-derived frames.

Read-only native sources; no account objects, trades, model activation or source
rewrites. One CPU process. Results are not prospective forecasts or paper P/L.
"""
import datetime,hashlib,json,math,os,pathlib,resource,sqlite3,time
from collections import Counter,OrderedDict
from urllib.parse import urlparse
from neraium_poly.contracts import MarketSnapshot,OrderBookSnapshot
from neraium_poly.research.archive import BookReceipt,BookDelta,apply_observation
from neraium_poly.research.phase16.history import CausalHistory
from neraium_poly.research.phase16.execution import assess_execution
from neraium_poly.research.phase16.short_horizon import replay_forecasts,MODEL_VERSION,FEATURE_VERSION
ROOT=pathlib.Path('/home/ubuntu/Neraium-Poly');DATA=ROOT/'data/phase16/prepared-core';OUT=ROOT/'data/phase16/experiments';BASE=ROOT/'data/experimental-paper'
def digest(v):return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
def at(v):
 x=datetime.datetime.fromisoformat(v);assert x.tzinfo is not None;return x

def read_db(p,immutable=False):
 c=sqlite3.connect(f'file:{p.resolve()}?mode=ro'+('&immutable=1' if immutable else ''),uri=True,timeout=15);c.row_factory=sqlite3.Row;c.execute('PRAGMA query_only=ON');return c
class SourceArchive:
 def __init__(self):
  self.cat=read_db(BASE/'events-archive.sqlite');self.segments={r['name']:dict(r) for r in self.cat.execute('SELECT * FROM segments')};self.connections=OrderedDict();self.cache=OrderedDict();self.verified=Counter()
 def get(self,identity):
  if identity in self.cache:return self.cache[identity]
  row=self.cat.execute('SELECT * FROM records WHERE id=?',(identity,)).fetchone()
  if row is None:return None
  segment=row['segment'];p=BASE/'events.sqlite' if segment=='legacy' else BASE/'events-segments'/segment;assert p.is_file() and not p.is_symlink()
  sealed=self.segments.get(segment,{}).get('status') in ['sealed','legacy'];con=self.connections.get(segment)
  if con is None:
   con=read_db(p,sealed)
   if sealed:
    if len(self.connections)>=4:self.connections.popitem(last=False)[1].close()
    self.connections[segment]=con
  try:r=con.execute('SELECT * FROM events WHERE id=?',(identity,)).fetchone()
  finally:
   if not sealed:con.close()
  assert r and r['kind']==row['kind'] and r['digest']==row['digest'] and hashlib.sha256(r['payload'].encode()).hexdigest()==row['digest']
  value=(r['kind'],json.loads(r['payload']),row['digest']);self.cache[identity]=value;self.verified[r['kind']]+=1
  if len(self.cache)>4096:self.cache.popitem(last=False)
  return value
 def book(self,identity):
  item=self.get(identity) or self.get(hashlib.sha256(('book-observation:'+identity).encode()).hexdigest());assert item
  kind,v,_=item
  if kind=='OrderBookSnapshot':return v
  assert kind in ['BookReceipt','BookDelta'];ob=(BookDelta if kind=='BookDelta' else BookReceipt).model_validate(v);base=self.get(ob.full_book_id);assert base and base[0]=='OrderBookSnapshot'
  old=OrderBookSnapshot.model_validate(base[1]);assert old.available_at<=ob.available_at
  return apply_observation(old,ob).model_dump(mode='json')
 def close(self):
  for con in self.connections.values():con.close()
  self.cat.close()

def fee_from_frame(raw,token,observed,archive,cycle):
 if not isinstance(raw,dict):return None,None
 assert raw['evidence_id'] in cycle.get('fee_evidence_ids',[])
 item=archive.get(raw['evidence_id']);assert item and item[0]=='FeeObservation';f=item[1]
 assert f['token_id']==token and f['source']=='https://clob.polymarket.com' and at(f['available_at'])<=observed
 assert 0<=(observed-at(f['available_at'])).total_seconds()<=300
 assert f['fee_rate']==raw['fee_rate'] and f['raw_response_ids']==raw['raw_response_ids']
 responses=[]
 for ref in f['raw_response_ids']:
  response=archive.get(ref);assert response and response[0]=='PublicFeeResponse';v=response[1]
  assert v['source']=='https://clob.polymarket.com' and at(v['available_at'])<=at(f['available_at'])
  assert digest(v['payload'])==v['content_sha256'];responses.append(v)
 parent=next(v['payload'] for v in responses if v['url']==f'https://clob.polymarket.com/markets-by-token/{token}')
 assert token in {str(parent['primary_token_id']),str(parent['secondary_token_id'])};condition=parent['condition_id']
 details=next(v['payload'] for v in responses if v['url']==f'https://clob.polymarket.com/clob-markets/{condition}')
 assert details.get('c',condition)==condition and token in {str(t['t']) for t in details['t']}
 curve=details['fd'];rate=float(curve['r']);exponent=float(curve['e']);assert curve['to'] is True and math.isfinite(rate) and 0<=rate<=1 and exponent==1 and abs(rate-f['fee_rate'])<=1e-12
 compact={k:raw[k] for k in ['fee_rate','effective_notional_bound','observed_at','available_at','timestamp','source','reference','id','evidence_id','raw_response_ids'] if k in raw}
 return float(raw['fee_rate']),compact

def vwap(levels):
 quantity=5.;value=0.
 for level in levels[:3]:
  take=min(quantity,float(level['size'])*.25);quantity-=take;value+=take*float(level['price'])
 return value/5 if quantity<=1e-9 else None

def verify_point(point,binding):
 try:
  rawm,rawb,frame_observed,fee_rate,fee_raw,frame_id=binding
  m=MarketSnapshot.model_validate(rawm);b=OrderBookSnapshot.model_validate(rawb);observed=at(point['observed_at'])
  assert observed==frame_observed and b.timestamp<=b.available_at<=observed and m.timestamp<=observed and m.available_at<=observed
  assert (b.market_id,b.token_id,b.exchange)==(m.market_id,m.token_id,m.exchange)
  assert b.source in ['https://clob.polymarket.com','wss://ws-subscriptions-clob.polymarket.com/ws/market'] and m.source=='https://gamma-api.polymarket.com'
  assert m.status=='active' and (m.end_time is None or m.end_time>observed) and m.resolution_rules and m.resolution_source and b.complete and b.bids and b.asks
  assert 0<=(observed-b.timestamp).total_seconds()<=15 and b.asks[0].price-b.bids[0].price<=.05
  semantic={k:m.model_dump(mode='json')[k] for k in ['exchange','market_id','token_id','event_id','question','outcome','resolution_rules','resolution_source','end_time','min_order_size','tick_size']}
  rules=digest(semantic)
  assert point['id']==digest(['phase16-point',b.id,rules]) and point['rules_sha256']==rules
  assert point['book_sha256']==digest(rawb) and point['metadata_sha256']==digest(rawm)
  assert point['book_id']==b.id and point['source_at']==b.timestamp.isoformat() and point['available_at']==b.available_at.isoformat()
  assert point['market_id']==m.market_id and point['token_id']==m.token_id and point['event_id']==m.event_id
  assert point['bid']==b.bids[0].price and point['ask']==b.asks[0].price and point['source']==b.source
  bids=[v.model_dump() for v in b.bids[:3]];asks=[v.model_dump() for v in b.asks[:3]]
  assert point['bids']==bids and point['asks']==asks and point['bid_vwap']==vwap(bids) and point['ask_vwap']==vwap(asks)
  assert point['quantity']==5. and point['participation']==.25 and point['depth_scope']=='top3_observed'
  assert point['fee_rate']==fee_rate and point['fee_observation']==fee_raw
  assert point['fee_observation_valid']==(fee_rate is not None) and point['fee_evidence_sha256']==(digest(fee_raw) if fee_raw else None)
  assert point['source_frame_id']==frame_id
  return True
 except (KeyError,ValueError,TypeError,AssertionError):return False

started=datetime.datetime.now(datetime.timezone.utc).isoformat();clock=time.monotonic();cpu=time.process_time();manifest=json.loads((DATA/'manifest.json').read_text());file=DATA/'frames.jsonl'
actual_sha=hashlib.sha256(file.read_bytes()).hexdigest();assert actual_sha==manifest['sha256']=='76a512397eecaef89328ac3dfd1885b0863b283acff8cd522417d138f56def46';assert file.stat().st_size==manifest['bytes']
archive=SourceArchive();history=CausalHistory(max_tokens=8);points=[];bindings={};observed_frames=0;last=None;costs={str(n):{'observations':0,'execution_supported':0,'rejections':Counter(),'modeled_vwap_cost_sum':0.,'priced':0} for n in [2,5,15,25]};source_fee_missing=0
try:
 with file.open() as f:
  for line in f:
   record=json.loads(line);frame=record['frame'];now=at(record['observed_at']);last=now
   cycle=archive.get(record['source_cycle_id']);assert cycle and cycle[0]=='ExperimentalCycle' and cycle[2]==record['source_cycle_sha256'];cycle=cycle[1]
   assert frame['id']==cycle['source_frame_id'] and at(cycle['available_at'])==now
   markets={m['token_id']:m for m in frame['markets']};rawbooks={b['token_id']:b for b in frame['books']};fees={}
   for token,m in markets.items():
    assert m['id'] in cycle.get('market_record_ids',[]);original=archive.get(m['id']);assert original and original[0]=='MarketSnapshot' and original[1]==m
   for token,b in rawbooks.items():
    assert b['id'] in cycle['observed_book_ids'];assert archive.book(b['id'])==b
    rate,rawfee=fee_from_frame(frame['fees'].get(token),token,now,archive,cycle);fees[token]=(rate,rawfee)
    source_fee_missing+=int(rate is None)
    if token not in markets:continue
    for notional in [2,5,15,25]:
     check=assess_execution(markets[token],b,now=now,target_notional=notional,fee_observation=rawfee)
     counter=costs[str(notional)];counter['observations']+=1;counter['execution_supported']+=int(check['execution_checks_pass']);counter['rejections'].update(check['execution_reasons'])
     sweep=check.get('hypothetical_sweep_entry',{})
     if notional<=5 and sweep.get('complete') and rate is not None:
      counter['modeled_vwap_cost_sum']+=sweep['notional']*(1+rate)+check['quantity_shares']*.01;counter['priced']+=1
   emitted=history.observe(frame,now=now)
   for point in emitted['accepted']:
    token=point['token_id'];rate,rawfee=fees.get(token,(None,None));binding=(markets[token],rawbooks[token],now,rate,rawfee,frame['id'])
    assert verify_point(point,binding);bindings[digest(point)]=binding;points.append(point)
   observed_frames+=1
 assert observed_frames==manifest['frames']
 replay=replay_forecasts(points,cutoff=last,verify_point=lambda p:verify_point(p,bindings[digest(p)]) if digest(p) in bindings else False)
 source_counts=dict(archive.verified)
finally:archive.close()
for row in costs.values():
 row['rejections']=dict(row['rejections']);row['mean_observed_entry_cash_plus_slippage_bound']=row['modeled_vwap_cost_sum']/row['priced'] if row['priced'] else None
 row['operational_tier_supported']=row['observations']>0
costs['15']['operational_tier_supported']=False;costs['25']['operational_tier_supported']=False
result={'started_at':started,'completed_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'actual_worker_processes':1,'pid':os.getpid(),'elapsed_seconds':time.monotonic()-clock,'cpu_seconds':time.process_time()-cpu,'max_rss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,'dataset':manifest,'dataset_sha256_verified':True,'source_archive_records_revalidated':source_counts,'accepted_points_total':len(points),'missing_fee_observations':source_fee_missing,'history_summary':history.summary(),'model_source_sha256':hashlib.sha256((ROOT/'backend/neraium_poly/research/phase16/short_horizon.py').read_bytes()).hexdigest(),'feature_source_sha256':hashlib.sha256((ROOT/'backend/neraium_poly/research/phase16/history.py').read_bytes()).hexdigest(),'model_version':MODEL_VERSION,'feature_version':FEATURE_VERSION,'replay':replay,'wager_cost_sensitivity':costs,'authorization':{'research_only':True,'execution_certified':False,'trading_authority':False,'model_promotion_authority':False},'limitations':['Producer health and original frame timestamps were not recorded in legacy cycles; cannot certify execution.','Point evidence independently rebound to raw archived cycle/market/quote/fee records, not current quotes or constant verification.','Quote MAE and fee/slippage mark arithmetic are not account P/L, actual fills or independently verified event outcomes.','Frozen temporal heldout is exploratory; six shared parent groups and repeated tokens cannot establish100training+100heldoutindependentevents.','No parameter selection or threshold change followed viewing heldout results.']}
raw=(json.dumps(result,indent=2,allow_nan=False)+'\n').encode();assert len(raw)<=16*1024**2;(OUT/'frozen-depth-mark-results.json').write_bytes(raw)
print(json.dumps({k:v for k,v in result.items() if k not in ['replay','history_summary','dataset']},indent=2));print(json.dumps({k:v for k,v in replay.items() if k!='records'},indent=2))
