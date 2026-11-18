"""Read-only preservation attestation after the isolated benchmarks."""
import json
import shutil
import subprocess
from datetime import UTC,datetime
from pathlib import Path

from neraium_poly.research.phase17.provenance import ReadonlyArchive
from state import accounts,journal_heads,native,trials

here=Path(__file__).resolve().parent
live=Path('/home/ubuntu/Neraium-Poly')
anchor=json.loads((here/'live-config-anchor.json').read_bytes())
frozen=json.loads((here/'frozen-state.json').read_bytes())
out={'at':datetime.now(UTC).isoformat(),'services':{},'fs_free':shutil.disk_usage(live).free}
assert out['fs_free']>100*1024**3
exp=live/'data/experimental-paper'
out['state']={'accounts':accounts(live/'data'),'journals':journal_heads(exp),'native':native(exp),'trials':trials(ReadonlyArchive(exp).get)}
assert out['state']['accounts']==frozen['accounts']
assert out['state']['trials']==frozen['trials']
assert out['state']['native']['backup_sha256']==frozen['native']['backup_sha256']
assert out['state']['native']['original_files']==frozen['native']['original_files']
assert all(out['state']['native']['proofs'][key]==hash_ for key,hash_ in frozen['native']['proofs'].items())
out['forecast_heads_equal_to_snapshot']=out['state']['journals']==frozen['journals']
for unit,fields in anchor['services'].items():
    keys=('MainPID','NRestarts','MemoryMax','CPUQuotaPerSecUSec','TasksMax','MemorySwapMax')
    output=subprocess.check_output(['systemctl','show',unit,*[f'--property={key}' for key in keys]],text=True,timeout=5)
    got=dict(line.split('=',1) for line in output.splitlines())
    process=Path('/proc',got['MainPID'])
    environment=dict(value.split(b'=',1) for value in (process/'environ').read_bytes().split(b'\0') if b'=' in value)
    for key in ('PAPER_TRADING','LIVE_TRADING_ENABLED','NERAIUM_DEPLOYED_SOURCE','NERAIUM_SHADOW_RESEARCH'):
        got[key]=environment.get(key.encode(),b'unset').decode()
    assert got==fields
    out['services'][unit]=got
(here/'live-preservation.json').write_text(json.dumps(out,indent=2)+'\n')
