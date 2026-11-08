import asyncio,json,pathlib,sqlite3,datetime
from neraium_poly.data import EventStore
from neraium_poly.research.phase14.relationships import digest
from neraium_poly.research.phase32.scoring import DomainEventScoring
root=pathlib.Path('/home/ubuntu/.local/share/neraium-citadel/worktrees/3e041d43987e0512/poly-p32-weather-20261108/data/phase32-weather');results=json.load(open(root/'results-full-local.json'));sources={};outcomes={}
for r in results:
 x=json.load(open(root/(r['forecast_id']+'.json')));sources[x['study']['id']]=x['study'];outcomes[r['forecast_id']]=r['result']
c=sqlite3.connect('file:data/experimental-paper/research-projection.sqlite?mode=ro',uri=True);entries=[json.loads(v[0]) for v in c.execute('SELECT payload FROM entries')];c.close();entries=[r for r in entries if r.get('type')=='forecast' and r['forecast']['domain']=='weather']
NOW=datetime.datetime.now(datetime.UTC);clock=lambda:NOW
class Index:
 def report(self,**k):return {'projection':{'status':'caught_up'}}
 def snapshot(self):return entries,{'id':'ISOLATED-REPLAY-'+digest(entries),'available_at':clock().isoformat()}
store=EventStore(pathlib.Path('data/phase32/isolated-pipeline.sqlite'))
class Proxy:
 def get(self,k):return sources[k] if k in sources else store.get(k)
 def latest(self,*a,**k):return store.latest(*a,**k)
 def append(self,r):return store.append(r)
async def main():
 p=DomainEventScoring(Proxy(),Index(),root/'official',clock=clock,can_write=lambda:True)
 async def reuse(f,**k):return outcomes[f['id']]
 p.verify=reuse
 assert await p.step()
 v=p.status();assert v['verified_forecast_labels']==10 and v['event_groups_by_domain']=={'weather':3}
 v['scope']='isolated full scorer publication using authentic preserved inputs; no production journal or account writes'
 pathlib.Path('.planning/evidence/phase32/pipeline-preflight.json').write_text(json.dumps(v,indent=2)+'\n');print({k:v[k] for k in ['verified_forecast_labels','event_groups_by_domain','collection_rejections']})
 try:
  again=DomainEventScoring(Proxy(),Index(),root/'official',clock=lambda:NOW+datetime.timedelta(seconds=1),can_write=lambda:True);again.verify=reuse;await again.step();assert again.status()['verified_forecast_labels']==10
 finally:store.close()
asyncio.run(main())
