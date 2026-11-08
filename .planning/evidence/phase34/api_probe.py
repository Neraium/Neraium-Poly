import asyncio,httpx,json,pathlib,datetime,time,statistics,os
async def main(label):
 output=pathlib.Path(f'.planning/evidence/phase34/latency-{label}.json')
 if output.exists():raise FileExistsError('use a unique label; original evidence is immutable')
 result={'started_at':datetime.datetime.now(datetime.UTC).isoformat(),'scope':'120s real collection load, two bounded sequential samplers ops and health, no latency-timeout masking; quantiles empirical not asymptotic tail guarantees','samples':{},'resource_samples':[]}
 async def poll(client,path):
  rows=[];start=time.monotonic();next_at=start
  while time.monotonic()-start<120:
   at=time.monotonic();r={'at':datetime.datetime.now(datetime.UTC).isoformat()}
   try:
    x=await client.get(f'http://127.0.0.1:18743/api/{path}');x.raise_for_status();r['status']=x.status_code
   except httpx.HTTPError as e:r['error']=type(e).__name__
   r['seconds']=time.monotonic()-at;rows.append(r);next_at+=2;await asyncio.sleep(max(0,min(next_at-start,120)-(time.monotonic()-start)))
  return rows
 async def resources():
  for i in range(25):
   row={'at':datetime.datetime.now(datetime.UTC).isoformat()}
   for n in ('paper','experimental'):
    p=pathlib.Path('/sys/fs/cgroup/system.slice/neraium-poly-'+n+'.service');row[n]={k:(p/k).read_text().strip() for k in ('cpu.stat','memory.current','memory.peak','memory.events','memory.stat')}
   st=os.statvfs('.');row['filesystem_free_bytes']=st.f_bavail*st.f_frsize;result['resource_samples'].append(row)
   if i<24:await asyncio.sleep(5)
 async with httpx.AsyncClient(timeout=15,limits=httpx.Limits(max_connections=2,max_keepalive_connections=2)) as c:
  ops,health,_=await asyncio.gather(poll(c,'operations-state'),poll(c,'health'),resources())
 for name,rows in [('operations',ops),('health',health)]:
  values=sorted(r['seconds'] for r in rows)
  def q(p):
   i=(len(values)-1)*p;low=int(i);high=min(low+1,len(values)-1);return values[low]+(values[high]-values[low])*(i-low)
  result['samples'][name]=rows;result.setdefault('summary',{})[name]={'requests':len(values),'median':statistics.median(values),'p95':q(.95),'p99':q(.99),'maximum':max(values),'timeouts':sum(r.get('error')=='ReadTimeout' for r in rows),'errors':sum('error'in r for r in rows)}
 result['finished_at']=datetime.datetime.now(datetime.UTC).isoformat();pathlib.Path(f'.planning/evidence/phase34/latency-{label}.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result['summary']))
import sys
asyncio.run(main(sys.argv[1]))
