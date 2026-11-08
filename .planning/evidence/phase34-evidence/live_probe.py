"""One isolated prospective source probe; no production journal/account writes."""
import asyncio,datetime,hashlib,json,pathlib,sqlite3
import httpx
from neraium_poly.data import EventStore
from neraium_poly.data.polymarket import normalize_market
from neraium_poly.data.operational import OperationalPolymarketAdapter
from neraium_poly.experimental.fees import AuditedFeeAdapter
from neraium_poly.research.phase25 import weather
from neraium_poly.research.phase14.relationships import digest
from neraium_poly.research.phase34.weather import weather_economic_diagnostic
clock=lambda:datetime.datetime.now(datetime.UTC)
local=pathlib.Path('data/phase34-evidence');out=pathlib.Path('.planning/evidence/phase34-evidence')
async def main():
 c=httpx.AsyncClient(timeout=8,follow_redirects=False);store=EventStore(local/'source-journal.sqlite');fee=AuditedFeeAdapter(store,lambda:True,client=c);adapter=OperationalPolymarketAdapter(client=c,clock=clock,retries=1)
 record={'scope':'isolated prospective source-backed research only; not production forecast enrollment, calibrated estimate, trade or position','started_at':clock().isoformat(),'target_market_id':'6772951'}
 try:
  response=await c.get('https://gamma-api.polymarket.com/markets/6772951');response.raise_for_status();raw=response.content
  name=hashlib.sha256(raw).hexdigest()+'.json';(local/name).write_bytes(raw);observed=clock()
  record.update(metadata_url=str(response.url),metadata_retrieved_at=observed.isoformat(),metadata_raw_sha256=hashlib.sha256(raw).hexdigest())
  parent=await c.get('https://gamma-api.polymarket.com/events/1330011');parent.raise_for_status();parent_raw=parent.content
  parent_sha=hashlib.sha256(parent_raw).hexdigest();(local/(parent_sha+'.json')).write_bytes(parent_raw)
  event=parent.json();assert str(event['id'])=='1330011'
  children=[m for m in event['markets'] if str(m.get('id'))=='6772951'];assert len(children)==1
  child=children[0];original=response.json();assert child['conditionId']==original['conditionId'] and child['question']==original['question'] and child['clobTokenIds']==original['clobTokenIds'] and child['description']==original['description']
  child={**child,'eventId':str(event['id'])};observed=clock();record.update(parent_event_url=str(parent.url),parent_event_raw_sha256=parent_sha,parent_event_retrieved_at=observed.isoformat(),identity_binding='official parent child exact market/condition/question/token/rules match')
  token='2837344778740768706611833632901205223551899115628035920885877581443772947047';m=next(m for m in normalize_market(child,observed) if m.token_id==token)
  obs=await fee.observed_fee(token);record['fee_observation']=obs
  b=await adapter.book(m.market_id,m.token_id);probe=await weather.forecast(m,b,clock=clock)
  for f in probe['forecasts']:f['id']=digest(f)
  record['probe']=probe;record['completed_at']=clock().isoformat()
  diagnostics=[weather_economic_diagnostic(f,probe['evidence'],as_of=clock(),fee_observation=obs,store=store) for f in probe['forecasts']];record['diagnostics']=diagnostics
  digest_value=digest(record);path=local/('prospective-'+digest_value+'.json')
  with path.open('x') as stream:json.dump(record,stream)
  summary={k:v for k,v in record.items() if k!='probe'};summary['prospective_record_sha256']=digest_value;summary['prospective_local_file']=str(path);summary['forecasts_generated']=len(probe['forecasts']);summary['source_rejections']=probe['rejections'];summary['evidence_sha256']=digest(probe['evidence'])
  (out/'prospective.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps(summary),flush=True)
 finally:await fee.close();await c.aclose();store.close()
asyncio.run(main())
