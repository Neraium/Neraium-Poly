"""Final read-only account, source, archive and experimental desk attestation."""
import hashlib
import importlib.util
import json
import subprocess
from datetime import UTC,datetime
from pathlib import Path

import httpx

from neraium_poly.data import EventStore
from neraium_poly.research.phase14.relationships import digest
from neraium_poly.research.phase44.cohort import LegacyCohort as StrategyEngine
from neraium_poly.risk import RiskLimits

HERE=Path(__file__).resolve().parent;ROOT=Path('/home/ubuntu/Neraium-Poly');SOURCE='1875ff2018e8f8ac670553eefd2fd46e819446b8'
spec=importlib.util.spec_from_file_location('gate',HERE/'deploy.py');gate=importlib.util.module_from_spec(spec);spec.loader.exec_module(gate);gate.OLD=SOURCE
post=gate.gate(full=True);assert all(r.get('integrity')=='verified' for r in post['journals'].values())
manifest=json.loads((HERE/'release-manifest.json').read_text());assert manifest['source']==SOURCE and all(hashlib.sha256((Path(manifest['release'])/n).read_bytes()).hexdigest()==h for n,h in manifest['files'].items())
with httpx.Client(timeout=10,trust_env=False) as client:
    report=client.get('http://127.0.0.1:18743/api/shadow-research').json();assert report['status']=='fresh'
    archive=client.get('http://127.0.0.1:18743/api/archive-state').json()
    operations=client.get('http://127.0.0.1:18743/api/operations-state').json()
store=EventStore(':memory:');risk=RiskLimits.model_validate(json.loads((ROOT/'config/experimental-paper.example.json').read_text())['risk_limits']).model_dump()
engine=StrategyEngine(store,risk_limits=risk,clock=lambda:datetime.now(UTC),can_write=lambda:True)
assert report['strategy_policy_sha256']==digest(engine.policy)
from neraium_poly.research.phase45.cohort import Explorer
explorer=Explorer(store,risk_limits=risk,clock=lambda:datetime.now(UTC),can_write=lambda:True)
assert report['phase45_explorer']['strategy_policy_sha256']==digest(explorer.policy);store.close()
assert report.get('phase45_explorer') and report.get('probability_panel')
assert report['shadow_worker']['maximum_workers']==1 and not report['trading_authority'] and not report['actual_account_access']
assert post['accounts']['experimental-paper']['risk.sqlite']['account']['kill']==1
assert post['services']['neraium-poly-paper.service']['MainPID']=='478083'
result={'source':SOURCE,'pid':post['services']['neraium-poly-experimental.service']['MainPID'],'postflight':post,'release_files_verified':len(manifest['files']),
    'policy_matches_running_code':True,'report':report,'archive':archive,'operations_health':operations.get('collector_health'),
    'source_rollback_ready':True,'rollback_executed':False,'stop_cleared':False,'account_orders_resumed':False,'reference_restarted':False}
(HERE/'postflight.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps({k:v for k,v in result.items() if k not in ('report','archive','postflight')}))
