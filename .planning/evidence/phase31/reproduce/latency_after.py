import asyncio,json,time,datetime,pathlib
import httpx
async def main():
 async with httpx.AsyncClient(timeout=10) as c:
  deadline=time.monotonic()+240
  while True:
   try:
    r=await c.get('http://127.0.0.1:18743/api/operations-state');r.raise_for_status();v=r.json()
    ev=v.get('operations_research',{}).get('event_intelligence',{})
    if v.get('domain_scorecard',{}).get('status')=='research_only':break
   except httpx.HTTPError:pass
   if time.monotonic()>deadline:raise RuntimeError('current scorecard unavailable after bounded recovery')
   await asyncio.sleep(5)
  rows=[]
  for _ in range(3):
   start=time.monotonic();r=await c.get('http://127.0.0.1:18743/api/operations-state');r.raise_for_status();v=r.json()
   rows.append({'seconds':time.monotonic()-start,'status':r.status_code,'bytes':len(r.content)})
  out=pathlib.Path('.planning/evidence/phase31')
  (out/'latency-after.json').write_text(json.dumps({'at':datetime.datetime.now(datetime.UTC).isoformat(),'samples':rows},indent=2)+'\n')
  (out/'scorecard-live.json').write_text(json.dumps(v.get('domain_scorecard'),indent=2)+'\n')
  (pathlib.Path('data/phase31')/'operations-after.json').write_text(json.dumps(v)+'\n')
  print(json.dumps({'latency':rows,'scorecard_status':v['domain_scorecard']['status'],'research_keys':list(v.get('operations_research',{}))}))
asyncio.run(main())
