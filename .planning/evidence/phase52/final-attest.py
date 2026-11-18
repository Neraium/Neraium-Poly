"""Record serving source, paper balances, stop, and original evidence checks."""
import json
import shutil
import sqlite3
from contextlib import closing
from pathlib import Path

import httpx

from rollout import BASE, CANDIDATE, DROP, FLOOR, HERE, PAPER, PREVIOUS, UNIT, attest, continuity, get, save, stamp, state

baseline=json.loads((HERE/'preflight.json').read_bytes())
final_file=next(
    HERE/name for name in ('window-rollback.json','rollback.json','quiesced-ready.json')
    if (HERE/name).is_file()
)
completed=json.loads(final_file.read_bytes())
source=completed['source']
expected_drop='experimental-source.conf' if source==CANDIDATE else 'previous-source.conf'
assert source in (CANDIDATE,PREVIOUS) and DROP.read_bytes()==(HERE/expected_drop).read_bytes()
service=attest(UNIT,source)
reference=attest(PAPER)
assert reference['service']['MainPID']==baseline['reference']['service']['MainPID']
assert reference['service']['NRestarts']==baseline['reference']['service']['NRestarts']
assert service['service']['MainPID']==completed['experimental']['service']['MainPID']
assert service['service']['NRestarts']=='0'
after=state()
continuity(baseline['state'],after)
balances={}
for account in ('paper-live','experimental-paper'):
    risk=BASE/account/'risk.sqlite'
    with closing(sqlite3.connect(risk.as_uri()+'?mode=ro',uri=True,timeout=3)) as conn:
        cash,realized,kill=conn.execute('SELECT cash,realized,kill FROM account WHERE id=1').fetchone()
    balances[account]={'paper_cash':cash,'realized':realized,'stop_latched':bool(kill)}
events_path=Path('/sys/fs/cgroup/system.slice',UNIT,'memory.events')
memory=dict(line.split() for line in events_path.read_text().splitlines())
assert memory['oom_kill']=='0'
free=shutil.disk_usage(BASE).free
assert free>FLOOR
with httpx.Client(timeout=5,trust_env=False) as client:
    health=get(client,18743,'health')
    shadow=get(client,18743,'shadow-research')
    ref_health=get(client,18742,'health')
assert health['paper_trading'] and not health['live_trading_enabled']
assert ref_health['paper_trading'] and not ref_health['live_trading_enabled']
assert shadow['status']=='withheld' and shadow['trading_authority'] is False
save('final-attestation.json',{'at':stamp(),'source':source,'completion_record':final_file.name,
     'experimental':service,'reference':reference,'disk_free_bytes':free,
     'experimental_health':health['status'],'reference_health':ref_health['status'],
     'shadow':shadow,'balances':balances,'paper_state_matches_preflight':True,
     'original_journal_heads_preserved_as_prefixes':True,'journal_heads':after['journals'],
     'original_proofs':len(baseline['state']['native']['proofs']),'current_proofs':len(after['native']['proofs']),
     'original_proof_file_identities':after['native']['original_files'],
     'backup_sha256':after['native']['backup_sha256'],'frozen_trials':len(after['trials']),
     'memory_events':memory})
