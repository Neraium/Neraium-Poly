"""Offline raw-RPC replay and RO original journal lookup; no production writes."""
import importlib.util
import json
from datetime import UTC, datetime
from pathlib import Path

from neraium_poly.research.phase14.relationships import digest
from neraium_poly.research.phase17.provenance import ReadonlyArchive
from neraium_poly.research.phase24.operations import original
from neraium_poly.research.phase26.reporting import callbacks
from neraium_poly.research.phase35.validation import native_market_baseline_report

native_root=Path('/home/ubuntu/.local/share/neraium-citadel/worktrees/3e041d43987e0512/poly-p35-native-20261109')
spec=importlib.util.spec_from_file_location('native_raw_replay',native_root/'backend/neraium_poly/research/phase35/native.py')
native=importlib.util.module_from_spec(spec);spec.loader.exec_module(native)
source=Path('/home/ubuntu/Neraium-Poly/data/experimental-paper');store=ReadonlyArchive(source)
originals={}
for label in store.latest('OfficialEventLabelStudy',64):
    study=original(store,label['original_study_id'])
    if digest(study)!=label['original_study_sha256']:raise ValueError('original study hash')
    f=next(f for f in study['forecasts'] if f['id']==label['forecast_id'])
    if digest(f)!=label['original_forecast_sha256']:raise ValueError('original forecast hash')
    originals[digest(f)]={'study':study,'forecast':f}
items=[];unmatched=[];failed=[]
for path in sorted((native_root/'data/phase35-native').iterdir()):
    if not path.is_dir() or not (path/'bundle.json').is_file() or not (path/'manifest.json').is_file():continue
    try:
        proof=native.replay_native_directory(path)
        item=originals.get(proof['forecast_sha256'])
        if item is None:unmatched.append(str(path));continue
        items.append({**item,'proof':proof,'proof_directory':str(path)})
    except (KeyError,ValueError,OSError) as error:failed.append({'path':str(path),'error':str(error)})
r=native_market_baseline_report(items,as_of=datetime.now(UTC),forecast_verifier=callbacks(store,source)[0],
    native_verifier=lambda item,**_:native.replay_native_directory(item['proof_directory']))
r['unmatched_originals']=unmatched;r['failed_native_attempts']=failed
print(json.dumps(r,sort_keys=True,indent=2))
