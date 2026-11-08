import asyncio,json,pathlib,time,datetime,subprocess
import httpx
async def main():
 end=time.monotonic()+240;p=pathlib.Path('data/phase31/operations-after.json')
 while True:
  try:
   v=json.loads(p.read_text());meta=v['operations_research']['event_summary_verification']
   if meta.get('summary_status')=='cached_verified_snapshot':break
  except (OSError,ValueError,KeyError):pass
  if time.monotonic()>end:raise RuntimeError('final deployed verification metadata not current')
  await asyncio.sleep(2)
 assert 0<=meta['summary_age_seconds']<=meta['summary_max_age_seconds']==120
 samples=[]
 async with httpx.AsyncClient(timeout=10) as c:
  for i in range(2):
   if i:await asyncio.sleep(15)
   now=datetime.datetime.now(datetime.UTC);r=await c.get('http://127.0.0.1:18742/api/market-frame');r.raise_for_status();f=r.json()
   fresh=[b for b in f['books'] if 0<=(now-datetime.datetime.fromisoformat(b['timestamp'])).total_seconds()<=15]
   assert fresh
   samples.append({'observed_at':now.isoformat(),'markets':len({m['market_id'] for m in f['markets']}),'fresh_native_books_15s':len(fresh),'latest_source_timestamp':max(b['timestamp'] for b in fresh),'examples':[{k:b[k] for k in ['market_id','token_id','timestamp','available_at']} for b in fresh[:2]],'connectivity':f['connectivity']})
  assert samples[-1]['latest_source_timestamp']>samples[0]['latest_source_timestamp']
  for port in [18742,18743]:
   r=await c.get(f'http://127.0.0.1:{port}/api/health');r.raise_for_status();h=r.json();assert h['paper_trading'] and not h['live_trading_enabled']
 subprocess.run(['uv','run','python','data/phase31/accounts.py','after'],check=True,stdout=subprocess.DEVNULL)
 out={'at':datetime.datetime.now(datetime.UTC).isoformat(),'scope':'15-second final metadata-release check following 60-second integrated-source observation; not indefinite stability evidence','verification_snapshot':meta,'samples':samples,'services':subprocess.check_output(['systemctl','show','neraium-poly-paper','neraium-poly-experimental','-p','MainPID','-p','NRestarts','-p','MemoryCurrent','-p','MemoryMax','-p','CPUQuotaPerSecUSec','-p','ActiveState'],text=True),'experimental_memory_events':pathlib.Path('/sys/fs/cgroup/system.slice/neraium-poly-experimental.service/memory.events').read_text()}
 pathlib.Path('.planning/evidence/phase31/final-live.json').write_text(json.dumps(out,indent=2)+'\n');print(json.dumps({'samples':[{k:x[k] for k in ['observed_at','markets','fresh_native_books_15s']} for x in samples],'summary_status':meta['summary_status']}))
asyncio.run(main())
