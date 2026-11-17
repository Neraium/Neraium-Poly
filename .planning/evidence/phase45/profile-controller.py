"""One bounded authentic controller profile, isolated writes, no service changes."""
import cProfile
import io
import json
import pstats
from datetime import UTC,datetime
from pathlib import Path

HERE=Path(__file__).resolve().parent
prelude=(HERE/'rehearse.py').read_text().split('store=Overlay();clock=')[0].replace("HERE/'final-rehearsal.sqlite'","HERE/'profile.sqlite'")
namespace={'__file__':str(HERE/'rehearse.py')};exec(compile(prelude,'profile-overlay','exec'),namespace)
store=namespace['Overlay']();clock=lambda:datetime.now(UTC)
from neraium_poly.research.phase42.controller import Controller
from neraium_poly.research.phase44.reference import ReferenceSampler
from neraium_poly.risk import RiskLimits
risk=RiskLimits(**json.loads(Path('config/experimental-paper.example.json').read_text())['risk_limits']).model_dump()
c=Controller(store,risk_limits=risk,clock=clock,can_write=lambda:True,directory=HERE/'profile-native')
sampler=ReferenceSampler('http://127.0.0.1:18742/api/market-frame',clock=clock);sampler.observe();frame=sampler.latest()
def refresh():sampler.observe();return sampler.latest()
p=cProfile.Profile();error=None;p.enable()
try:r=c.tick(frame,{},frame_provider=refresh)
except Exception as e:error=type(e).__name__+':'+str(e)
finally:p.disable()
s=io.StringIO();pstats.Stats(p,stream=s).strip_dirs().sort_stats('cumulative').print_stats(25)
(HERE/'profile.txt').write_text('scope=actual frozen archive and current public quotes; host process outside service cgroup; cannot infer deployed throughput\nerror='+str(error)+'\n'+s.getvalue());print(s.getvalue())
