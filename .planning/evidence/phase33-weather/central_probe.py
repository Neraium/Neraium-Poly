import asyncio,datetime,json,pathlib,sqlite3
import httpx
from neraium_poly.data.operational import OperationalPolymarketAdapter
from neraium_poly.contracts import MarketSnapshot
from neraium_poly.research.phase33.weather import prioritize_weather
from neraium_poly.research.phase25 import weather
clock=lambda:datetime.datetime.now(datetime.UTC);local=pathlib.Path('data/phase33-weather');out=pathlib.Path('.planning/evidence/phase33-weather')
c=sqlite3.connect('file:/home/ubuntu/Neraium-Poly/data/experimental-paper/research-projection.sqlite?mode=ro',uri=True);entries=[json.loads(v[0]) for v in c.execute('SELECT payload FROM entries')];c.close();markets=[MarketSnapshot.model_validate(m) for m in json.load(open(local/'metadata.json'))]
async def main():
 r=prioritize_weather(markets,[],entries,as_of=clock());chosen=[row for row in r['candidates'] if not row['station_day_already_forecast']][:6];ids={r['token_id'] for r in chosen};books=[];errors=[]
 client=httpx.AsyncClient(timeout=6,follow_redirects=False);adapter=OperationalPolymarketAdapter(client=client,clock=clock,retries=1)
 try:
  for m in markets:
   if m.token_id not in ids:continue
   try:books.append(await adapter.book(m.market_id,m.token_id))
   except Exception as e:errors.append({'market_id':m.market_id,'error':str(e)[:180]})
 finally:await client.aclose()
 r=prioritize_weather(markets,books,entries,as_of=clock());r.update(supplemental_books_requested=len(ids),supplemental_books_received=len(books),source_errors=errors)
 (local/'central-books.json').write_text(json.dumps([b.model_dump(mode='json') for b in books]));(out/'central-selection.json').write_text(json.dumps(r,indent=2)+'\n')
 print({k:r[k] for k in ['supported_outcome_tokens','supported_station_days','new_station_days_with_eligible_books','supplemental_books_requested','supplemental_books_received']},flush=True)
 print([(x['market_id'],x['token_id'],x['best_bid'],x['best_ask'],x['blockers'][:1]) for x in r['candidates'] if not x['station_day_already_forecast']],flush=True)
 # Use unchanged models only if a genuinely fresh book and exact future market passed.
 good=[x for x in r['candidates'] if x['book_eligible_at_evaluation'] and not x['station_day_already_forecast']]
 for chosen in good[:1]:
  m=next(m for m in markets if m.token_id==chosen['token_id']);b=next(b for b in books if b.token_id==m.token_id)
  f=await weather.forecast(m,b,clock=clock);(local/'prospective-model-probe.json').write_text(json.dumps(f))
  print('prospective_forecast_probe',{'forecasts':len(f['forecasts']),'rejections':f['rejections']},flush=True)
asyncio.run(main())
