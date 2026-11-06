"""Bounded read-only archive extraction; no active SQLite owner or long reader lock."""
import hashlib,json,pathlib,sqlite3,datetime,time
root=pathlib.Path('/home/ubuntu/Neraium-Poly');base=root/'data/experimental-paper';out=root/'data/phase16/prepared-core';out.mkdir(exist_ok=True)
def read_db(p,immutable=False):
 c=sqlite3.connect(f'file:{p.resolve()}?mode=ro'+('&immutable=1' if immutable else ''),uri=True,timeout=15);c.row_factory=sqlite3.Row;c.execute('PRAGMA query_only=ON');return c
cat=read_db(base/'events-archive.sqlite');segments={r['name']:dict(r) for r in cat.execute('SELECT * FROM segments')};cached={}
def fetch(row):
 name=row['segment'];p=base/'events.sqlite' if name=='legacy' else base/'events-segments'/name
 if not p.is_file():raise ValueError('source absent; original not recreated')
 sealed=segments.get(name,{}).get('status') in ['sealed','legacy']
 c=cached.get(name)
 if c is None:
  c=read_db(p,immutable=sealed)
  if sealed:
   if len(cached)>=4:cached.pop(next(iter(cached))).close()
   cached[name]=c
 try:r=c.execute('SELECT kind,payload,digest FROM events WHERE id=?',(row['id'],)).fetchone()
 finally:
  if not sealed:c.close()
 if r is None or r['kind']!=row['kind'] or r['digest']!=row['digest'] or hashlib.sha256(r['payload'].encode()).hexdigest()!=r['digest']:raise ValueError('archived record integrity mismatch')
 return json.loads(r['payload'])

from collections import OrderedDict
from neraium_poly.contracts import OrderBookSnapshot
from neraium_poly.research.archive import BookReceipt,BookDelta,apply_observation
from neraium_poly.research.phase16.execution import assess_execution
cache=OrderedDict()
def get(rid):
 if rid in cache:return cache[rid]
 row=cat.execute('SELECT * FROM records WHERE id=?',(rid,)).fetchone()
 if row is None:return None
 value=(row['kind'],fetch(row),row['digest']);cache[rid]=value
 if len(cache)>2048:cache.popitem(last=False)
 return value
def book(rid):
 item=get(rid)
 if item is None:item=get(hashlib.sha256(('book-observation:'+rid).encode()).hexdigest())
 if item is None:raise ValueError('missing archived source observation')
 kind,raw,sha=item
 if kind=='OrderBookSnapshot':return raw
 if kind not in ['BookReceipt','BookDelta']:raise ValueError('unsupported historical quote record')
 receipt=(BookDelta if kind=='BookDelta' else BookReceipt).model_validate(raw);base=get(receipt.full_book_id)
 assert base and base[0]=='OrderBookSnapshot';basebook=OrderBookSnapshot.model_validate(base[1]);assert basebook.available_at<=receipt.available_at
 return apply_observation(basebook,receipt).model_dump(mode='json')
cycles=list(reversed(cat.execute("SELECT * FROM records WHERE kind='ExperimentalCycle' ORDER BY available_at DESC,id DESC LIMIT 900").fetchall()))
cohort=None;count=total=0;first=None;last=None;parents=set();start=time.monotonic();rejected=0
with (out/'frames.jsonl').open('x') as dest:
 for row in cycles:
  v=fetch(row);at=datetime.datetime.fromisoformat(v['available_at']);markets=[get(rid)[1] for rid in v.get('market_record_ids',[])];books=[book(rid) for rid in v['observed_book_ids']];fees={}
  for fid in v.get('fee_evidence_ids',[]):
   item=get(fid)
   if item is None or item[0]!='FeeObservation':raise ValueError('missing historical fee evidence')
   f=item[1];assert datetime.datetime.fromisoformat(f['available_at'])<=at
   for ref in f['raw_response_ids']:
    response=get(ref);assert response and response[0]=='PublicFeeResponse';raw=response[1];assert hashlib.sha256(json.dumps(raw['payload'],sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()==raw['content_sha256'];assert datetime.datetime.fromisoformat(raw['available_at'])<=datetime.datetime.fromisoformat(f['available_at'])
   if 0<=(at-datetime.datetime.fromisoformat(f['available_at'])).total_seconds()<=300:fees[f['token_id']]={'fee_rate':f['fee_rate'],'source':f['source'],'observed_at':f['available_at'],'available_at':f['available_at'],'evidence_id':f['id'],'reference':f"/markets-by-token/{f['token_id']}",'raw_response_ids':f['raw_response_ids']}
  if cohort is None:
   bytoken={m['token_id']:m for m in markets};eligible=[]
   for b in books:
    m=bytoken[b['token_id']];report=assess_execution(m,b,now=at,fee_observation=fees.get(b['token_id']))
    if report['execution_checks_pass']:eligible.append(b['token_id'])
   if len(eligible)<8:rejected+=1;continue
   cohort=sorted(eligible)[:8];selected_at=at.isoformat()
  markets=[m for m in markets if m['token_id'] in cohort];books=[b for b in books if b['token_id'] in cohort]
  frame={'id':v['source_frame_id'],'source':'reconstructed_from_authentic_archived_experimental_cycle','timestamp':v['timestamp'],'available_at':v['available_at'],'producer_health':{'status':'unknown','reason':'not archived in legacy ExperimentalCycle'},'markets':markets,'books':books,'fees':{k:f for k,f in fees.items() if k in cohort}}
  record={'observed_at':v['available_at'],'frame':frame,'source_cycle_id':v['id'],'source_cycle_sha256':row['digest'],'selection_policy':'first chronologically execution-compatible8tokens, fixed thereafter; no future labels or current-universe substitution','missing_fields':['original_producer_health','original_frame_timestamp'],'research_only':True}
  line=json.dumps(record,sort_keys=True,separators=(',',':'),allow_nan=False)+'\n';total+=len(line.encode());assert total<=64*1024**2;dest.write(line);count+=1;first=first or v['available_at'];last=v['available_at'];parents.update(m['event_id'] for m in markets)
for c in cached.values():c.close()
cat.close();assert count>0
manifest={'created_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'frames':count,'first_at':first,'last_at':last,'tokens':cohort,'selected_at':selected_at,'parent_groups':len(parents),'bytes':total,'sha256':hashlib.sha256((out/'frames.jsonl').read_bytes()).hexdigest(),'selection_rejected_initial_cycles':rejected,'source':'authentic ExperimentalCycle/MarketSnapshot/OrderBookSnapshot/BookDelta/BookReceipt/FeeObservation/PublicFeeResponse','known_missingness':['producer_health','original_frame_timestamp'],'execution_certification':False,'independent_event_certification':False,'preparation_seconds':time.monotonic()-start}
(out/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n');print(json.dumps(manifest,indent=2))
