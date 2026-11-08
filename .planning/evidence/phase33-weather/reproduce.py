import asyncio,datetime,json,pathlib,sqlite3
from neraium_poly.research.phase17.provenance import ReadonlyArchive
from neraium_poly.research.phase14.relationships import digest
from neraium_poly.research.phase30.coverage import discover_weather
from neraium_poly.research.phase33.weather import weather_cohort,prioritize_weather
from neraium_poly.data.operational import OperationalPolymarketAdapter
import httpx
ROOT=pathlib.Path('/home/ubuntu/Neraium-Poly');out=pathlib.Path('.planning/evidence/phase33-weather');local=pathlib.Path('data/phase33-weather');clock=lambda:datetime.datetime.now(datetime.UTC)
c=sqlite3.connect(f'file:{ROOT}/data/experimental-paper/research-projection.sqlite?mode=ro',uri=True);entries=[json.loads(r[0]) for r in c.execute('SELECT payload FROM entries')];c.close();refs=[r for r in entries if r.get('type')=='forecast' and r['forecast']['domain']=='weather'];records=[]
with ReadonlyArchive(ROOT/'data/experimental-paper') as archive:
 current=archive.latest('EventScoreSnapshot',limit=1)[0]['enrollment_id'];labels={r['forecast_id']:r['result'] for r in archive.latest('OfficialEventLabelStudy',limit=64) if r['enrollment_id']==current}
 for ref in refs:
  s=archive.get(ref['source_id']);s=s if isinstance(s,dict) else json.loads(s[1]);assert digest(s)==ref['source_study_sha256']
  f=next(f for f in s['forecasts'] if f['id']==ref['forecast_id']);assert digest(f)==ref['forecast_sha256']
  records.append({'study':s,'forecast':f,'result':labels.get(f['id'])})
r=weather_cohort(records,evidence_root=ROOT/'data/experimental-paper/phase30-official-event-evidence',as_of=clock());(out/'cohort.json').write_text(json.dumps(r,indent=2)+'\n');print('cohort',{k:r[k] for k in ['forecasts_replayed','official_reference_forecasts_scored','distinct_scored_station_days','forecasts_with_any_prior_qualified_station_day','pending_forecasts','rejections']},flush=True)
async def main():
 markets=await discover_weather(clock=clock)
 async with httpx.AsyncClient(timeout=10) as c:
  reply=await c.get('http://127.0.0.1:18742/api/market-frame');reply.raise_for_status();frame=reply.json()
 books=frame['books'];initial=prioritize_weather(markets,books,entries,as_of=clock())
 chosen=[row for row in initial['candidates'] if not row['station_day_already_forecast'] and not row['book_eligible_at_evaluation']][:6];selected={r['token_id'] for r in chosen};collected=[];errors=[]
 client=httpx.AsyncClient(timeout=6,follow_redirects=False);adapter=OperationalPolymarketAdapter(client=client,clock=clock,retries=1)
 try:
  for m in markets:
   if m.token_id not in selected:continue
   try:collected.append((await adapter.book(m.market_id,m.token_id)).model_dump(mode='json'))
   except Exception as e:errors.append({'market_id':m.market_id,'error':str(e)[:180]})
 finally:await client.aclose()
 replacements={b['token_id']:b for b in collected};books=[b for b in books if b['token_id'] not in replacements]+collected
 r=prioritize_weather(markets,books,entries,as_of=clock());r.update(source_metadata='https://gamma-api.polymarket.com/public-search',source_books='https://clob.polymarket.com/book',supplemental_books_requested=len(selected),supplemental_books_received=len(collected),source_errors=errors)
 (local/'metadata.json').write_text(json.dumps([m.model_dump(mode='json') for m in markets]));(local/'books.json').write_text(json.dumps(books));(out/'selection.json').write_text(json.dumps(r,indent=2)+'\n');print('selection',{k:r[k] for k in ['supported_outcome_tokens','supported_station_days','new_station_days_with_eligible_books','supplemental_books_requested','supplemental_books_received']},flush=True)
asyncio.run(main())
