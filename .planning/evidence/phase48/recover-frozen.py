"""Two outcome-blind eligible frozen trials, isolated native evidence only.
No live archive, journal, controller or financial writes. Metadata is only a lookup hint.
"""
import json,signal
from datetime import UTC,datetime
from pathlib import Path
from neraium_poly.research.phase17.provenance import ReadonlyArchive
from neraium_poly.research.phase14.relationships import digest
from neraium_poly.research.phase44.native import acquire,replay
HERE=Path(__file__).resolve().parent;store=ReadonlyArchive('/home/ubuntu/Neraium-Poly/data/experimental-paper')
status=json.loads((HERE/'cohort-before.json').read_text());out=[]
def deadline(*args):raise TimeoutError('bounded60s native acquisition deadline')
signal.signal(signal.SIGALRM,deadline)
for row in status['rows']:
 if row['status']!='metadata_resolved_native_proof_required':continue
 original=store.get(row['trial_id']);trial=json.loads(original[1]);f=trial['source_forecast'];assert digest(f)==trial['source_binding']['forecast_sha256']
 path=HERE/('frozen-native-'+digest(row['trial_id'])[:20]);result={'trial_id':row['trial_id'],'source_forecast_sha256':digest(f),'original_trial_sha256':digest(trial),'at':datetime.now(UTC).isoformat(),'directory':str(path.relative_to(HERE)),'official_metadata_not_payout':True,'live_archive_modified':False,'live_journal_modified':False}
 try:
  signal.alarm(60);p=acquire(f,path,disk_budget=2*1024**2);assert replay(path)==p;result.update(verified=True,proof=p)
 except (ValueError,KeyError,TypeError,OSError,TimeoutError,__import__('httpx').HTTPError) as error:result.update(verified=False,reason=type(error).__name__+':'+str(error)[:300])
 finally:signal.alarm(0)
 out.append(result)
 (HERE/'frozen-native-recovery.json').write_text(json.dumps({'at':datetime.now(UTC).isoformat(),'results':out,'no_original_forecasts_changed':True,'no_live_publication':True},indent=2)+'\n')
 print(json.dumps(result),flush=True)
