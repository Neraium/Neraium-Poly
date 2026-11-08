import asyncio,datetime,json,pathlib,time,subprocess
import httpx
GIB=1024**3
out=pathlib.Path('.planning/evidence/phase31')
async def sample(client):
 async def get(name,port,path):
  r=await client.get(f'http://127.0.0.1:{port}/api/{path}');r.raise_for_status();return name,r.json()
 return dict(await asyncio.gather(get('collector',18742,'operations-state'),get('experimental',18743,'operations-state'),get('health',18742,'health'),get('experimental_health',18743,'health'),get('frame',18742,'market-frame')))
async def main():
 deadline=time.monotonic()+300;attempts=[];samples=[]
 async with httpx.AsyncClient(timeout=15) as client:
  while True:
   try:
    r=await sample(client)
    for name in ['collector','experimental']:
     a=r[name]['archive'];assert a['budget_bytes']==150*GIB,(name,a['budget_bytes']);assert a['global_floor_bytes']==100*GIB
    assert not r['health']['live_trading_enabled'] and not r['experimental_health']['live_trading_enabled']
    if all(r[n]['archive']['health']=='ok' for n in ['collector','experimental']) and r['health']['status']=='ok' and r['experimental_health']['status']=='ok':break
    attempts.append({'at':datetime.datetime.now(datetime.UTC).isoformat(),'status':'initial_recovery_pending'})
   except httpx.HTTPError as e:attempts.append({'at':datetime.datetime.now(datetime.UTC).isoformat(),'status':type(e).__name__})
   if time.monotonic()>deadline:raise RuntimeError('bounded recovery deadline exceeded')
   await asyncio.sleep(5)
  for i in range(3):
   if i:
    await asyncio.sleep(30);r=await sample(client)
   now=datetime.datetime.now(datetime.UTC);frame=r.pop('frame');fresh=[b for b in frame['books'] if 0<=(now-datetime.datetime.fromisoformat(b['timestamp'])).total_seconds()<=15]
   for n in ['collector','experimental']:
    a=r[n]['archive'];assert a['health']=='ok';assert a['budget_bytes']==150*GIB;assert a['global_floor_bytes']==100*GIB
   assert fresh and r['health']['ledger_consistent'];assert r['health']['paper_trading'] and not r['health']['live_trading_enabled']
   assert r['experimental_health']['paper_trading'] and not r['experimental_health']['live_trading_enabled']
   r.update(observed_at=now.isoformat(),markets=len({m['market_id'] for m in frame['markets']}),tokens=len(frame['markets']),fresh_native_books_15s=len(fresh),example_fresh_books=[{k:b[k] for k in ['id','market_id','token_id','timestamp','available_at']} for b in fresh[:2]])
   # Retain only relevant operational evidence; full originals live in journal.
   rr=r['experimental'].get('operations_research',{});p26=rr.get('phase26',{});projection=p26.get('projection') or {}
   r['experimental']['operations_research']={'phase28':rr.get('phase28',{}),'phase26':{'status':p26.get('status'),'projection':{k:projection.get(k) for k in ['counts','certification_requirements','sii_incremental_value','as_of']}}}
   for name in ['collector','experimental']:
    mem=r[name].get('memory',r[name].get('operation',{}).get('memory',{}))
    if isinstance(mem,dict):mem.pop('history',None)
   samples.append(r);(out/f'live-{i}.json').write_text(json.dumps(r,indent=2)+'\n');print(json.dumps({'at':r['observed_at'],'markets':r['markets'],'fresh_books':len(fresh),'collector_budget_gib':r['collector']['archive']['budget_bytes']/GIB,'experimental_budget_gib':r['experimental']['archive']['budget_bytes']/GIB}),flush=True)
 result={'readiness_attempts':attempts,'observed_seconds':(datetime.datetime.fromisoformat(samples[-1]['observed_at'])-datetime.datetime.fromisoformat(samples[0]['observed_at'])).total_seconds(),'samples':len(samples),'scope':'one bounded post-change observation, not proof of indefinite operation','services':subprocess.check_output(['systemctl','show','neraium-poly-paper','neraium-poly-experimental','--property=MainPID','--property=ActiveState','--property=NRestarts','--property=MemoryMax','--property=CPUQuotaPerSecUSec'],text=True)}
 (out/'observation.json').write_text(json.dumps(result,indent=2)+'\n')
asyncio.run(main())
