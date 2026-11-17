"""Bounded matched projection timing on one exact immutable archived cohort cycle."""
import importlib.util
import json
import statistics
import subprocess
import tempfile
import time
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from neraium_poly.research.phase16.checkpoints import unpack_checkpoint
from neraium_poly.research.phase17.provenance import ReadonlyArchive
from neraium_poly.research.phase42.desk import publish

here = Path(__file__).resolve().parent
anchor = '8d8c115d20fc86604cffc4af64657f967b499b63'
archive = ReadonlyArchive('/home/ubuntu/Neraium-Poly/data/experimental-paper')
row = archive.latest('StrategyCycle44', 1)[0]
engine = SimpleNamespace(last=row, state=unpack_checkpoint(row['checkpoint']))
report = {'profiles': {}}
now = datetime.fromisoformat(row['available_at'])
with tempfile.TemporaryDirectory() as tmp:
    module = Path(tmp)/'old_desk.py'
    module.write_bytes(subprocess.check_output(['git','show',f'{anchor}:backend/neraium_poly/research/phase42/desk.py'], timeout=10))
    spec = importlib.util.spec_from_file_location('old_desk',module)
    old = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(old)
    cache = {}
    baseline = old.publish(archive,engine,report,now,cohort='phase44')
    cached = publish(archive,engine,report,now,cohort='phase44',projected=cache)
    assert cached == baseline
    timings = {'before':[], 'after':[]}
    for _ in range(10):
        for label, fn in [('before',lambda:old.publish(archive,engine,report,now,cohort='phase44')),
                          ('after',lambda:publish(archive,engine,report,now,cohort='phase44',projected=cache,include_recent=False))]:
            start = time.perf_counter()
            out = fn()
            timings[label].append(time.perf_counter()-start)
            assert out['positions']==baseline['positions'] and out['unfilled_orders']==baseline['unfilled_orders']
(here/'project-bench.json').write_text(json.dumps({'cycle':row['id'],'runs':timings,'medians':{k:statistics.median(v) for k,v in timings.items()},
  'scope':'Same immutable closed-cohort cycle, same position projection, published cards already exist. The controller reads recent cards once at the end instead of repeating the read in each subcohort. Read-only microbenchmark; not a live performance prediction.'},indent=2)+'\n')
