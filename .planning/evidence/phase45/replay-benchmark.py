"""Matched warm audit on frozen authentic inputs; no simulated economic results."""
import json
import signal
import subprocess
import sys
import time
import types
from datetime import UTC,datetime
from pathlib import Path

from neraium_poly.research.phase14.relationships import digest
from neraium_poly.research.phase42 import controller,sources
from neraium_poly.research.phase44.reference import ReferenceSampler
from neraium_poly.risk import RiskLimits

signal.alarm(90);HERE=Path(__file__).resolve().parent
prelude=(HERE/'rehearse.py').read_text().split('store=Overlay();clock=')[0].replace("HERE/'final-rehearsal.sqlite'","HERE/'benchmark-unassigned.sqlite'")
namespace={'__file__':str(HERE/'rehearse.py')};exec(compile(prelude,'benchmark-overlay','exec'),namespace)
# Different isolated output stores, one original archive/source inventory.
shared_latest={}
prelude=prelude.replace(' def latest(self,kind,limit=100):', ' def original_latest(self,kind,limit):\n  key=(kind,limit)\n  if key not in shared_latest:shared_latest[key]=self.original.latest(kind,limit)\n  return shared_latest[key]\n def latest(self,kind,limit=100):').replace('self.original.latest(kind,limit),*self.local.latest','self.original_latest(kind,limit),*self.local.latest')
old_ns={'__file__':str(HERE/'rehearse.py'),'shared_latest':shared_latest};exec(compile(prelude.replace('benchmark-unassigned.sqlite','benchmark-before-v3.sqlite'),'before-overlay','exec'),old_ns)
new_ns={'__file__':str(HERE/'rehearse.py'),'shared_latest':shared_latest};exec(compile(prelude.replace('benchmark-unassigned.sqlite','benchmark-after-v3.sqlite'),'after-overlay','exec'),new_ns)
old_store=old_ns['Overlay']();new_store=new_ns['Overlay']()
old=types.ModuleType('frozen_before45');sys.modules[old.__name__]=old;old.__file__=str(HERE/'frozen-controller')
raw=subprocess.check_output(['git','show','1875ff2018e8f8ac670553eefd2fd46e819446b8:backend/neraium_poly/research/phase42/controller.py'])
exec(compile(raw,old.__file__,'exec'),old.__dict__)
release=Path('/home/ubuntu/Neraium-Poly/.deploy/releases/1875ff2018e8f8ac670553eefd2fd46e819446b8/backend/neraium_poly/research')
def frozen_module(name,path):
 module=types.ModuleType(name);sys.modules[name]=module;module.__file__=str(path)
 code=path.read_text().replace('from neraium_poly.research.phase42.engine import','from frozen_engine45 import')
 exec(compile(code,str(path),'exec'),module.__dict__);return module
frozen_module('frozen_engine45',release/'phase42/engine.py')
cohort44=frozen_module('frozen_cohort44',release/'phase44/cohort.py')
cohort45=frozen_module('frozen_cohort45',release/'phase45/cohort.py')
old.Cohort=cohort44.Cohort;old.LegacyCohort=cohort44.LegacyCohort;old.Explorer=cohort45.Explorer

risk=RiskLimits(**json.loads(Path('config/experimental-paper.example.json').read_text())['risk_limits']).model_dump()
clock_state=[None]
clock=lambda:clock_state[0] or datetime.now(UTC)
cohorts=[(name,module,module.Controller(store,risk_limits=risk,clock=clock,can_write=lambda:True,directory=HERE/('benchmark-native-'+name))) for name,module,store in [('before',old,old_store),('after',controller,new_store)]]
studies,audit=sources.forecast_studies(old_store);sources.forecast_studies=lambda *_:(studies,audit)
sampler=ReferenceSampler('http://127.0.0.1:18742/api/market-frame',clock=lambda:datetime.now(UTC));sampler.observe();frame=sampler.latest();frozen=datetime.now(UTC);clock_state[0]=frozen
result={'scope':'isolated matched warm inventory audit; frozen authentic source records/native frame; host process outside service cgroup, not a deployed speed claim','baseline_source':'1875ff2018e8f8ac670553eefd2fd46e819446b8','frame_sha256':digest(frame.model_dump(mode='json')),'study_sha256':[digest(s) for s in studies],'clock':frozen.isoformat(),'cycles':{}}
for name,module,c in cohorts:
 calls=[0];real=module.replay_model
 def counted(*args,_real=real,**kwargs):calls[0]+=1;return _real(*args,**kwargs)
 module.replay_model=counted
 c.tick(frame,{},frame_provider=lambda:frame);calls[0]=0;c.next_sources=None
 start=time.perf_counter();r=c.tick(frame,{},frame_provider=lambda:frame);elapsed=time.perf_counter()-start
 result['cycles'][name]={'seconds':elapsed,'full_model_replays':calls[0],'source_withholding':r['source_withholding'],'forecasts':r['forecasts'],'cache':r.get('source_replay_cache')}
assert result['cycles']['after']['full_model_replays']<result['cycles']['before']['full_model_replays']
assert result['cycles']['after']['source_withholding']==result['cycles']['before']['source_withholding']
assert result['cycles']['after']['forecasts']==result['cycles']['before']['forecasts']
(HERE/'replay-benchmark.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result['cycles']))
