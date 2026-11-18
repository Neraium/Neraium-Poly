"""Guarded reference-only restart and bounded, read-only loopback capture."""
import hashlib
import json
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx

HERE = Path(__file__).resolve().parent
for phase in ('phase38-activation','phase52'):
    sys.path.insert(0,str(HERE.parent/phase))
from sample import sample
from rollout import BASE, ROOT, PAPER, UNIT, attest, state, continuity, flags, system, save as unused
from neraium_poly.research.phase44.reference import ReferenceSampler

BASELINE='1342482fd9431f4e2e69d8788d864cb32fd1d4e9'
EXP='8d9756ff8a514ad87947646ffc330f0c3e10efc8'
SHA=(HERE/'reference-sha.txt').read_text().strip()
RELEASE=ROOT/'.deploy/releases'/SHA
DROP=Path('/etc/systemd/system/neraium-poly-paper.service.d/60-phase55-tracing.conf')
BACKUP=BASE/'paper-live/archive-baseline/events-pre-segmentation.sqlite'
UNIT_FILE=Path('/etc/systemd/system/neraium-poly-paper.service')
CONFIG=ROOT/'config/paper-live.example.json'

def cmd(*args,timeout=30):
    return subprocess.check_output(args,timeout=timeout)

def digest(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f,'sha256').hexdigest()

def save(name,row):
    (HERE/name).write_text(json.dumps(row,indent=2)+'\n')

def log(name,row):
    with (HERE/name).open('a') as f:
        f.write(json.dumps(row)+'\n')

def now():
    return datetime.now(UTC).isoformat()

def source_check():
    cmd('git','-C',str(ROOT),'diff','--exit-code',BASELINE,'--','backend','config','pyproject.toml','uv.lock')
    names=cmd('git','ls-tree','-r','--name-only',SHA,'backend','config','pyproject.toml','uv.lock').decode().splitlines()
    for name in names:
        assert digest(RELEASE/name)==hashlib.sha256(cmd('git','show',f'{SHA}:{name}')).hexdigest(),name
    changed=cmd('git','diff','--name-only',BASELINE,SHA).decode().splitlines()
    assert set(changed)=={'backend/neraium_poly/experimental/feed.py','backend/neraium_poly/experimental/feed_trace.py','backend/neraium_poly/ops/api.py'}
    assert b'return frame' in (RELEASE/'backend/neraium_poly/ops/api.py').read_bytes()

def startup(begun, revision, prior, experiment, before, baseline_files):
    good=0
    first=None
    while time.monotonic()-begun<1500:
        row=sample(with_operations=True)
        ref=row['services'][PAPER]
        elapsed=time.monotonic()-begun
        assert attest(UNIT,EXP)==experiment, 'experimental changed'
        assert not row['unsafe'] and ref['NRestarts']=='0' and not ref.get('memory.events',{}).get('oom_kill',0), row['unsafe']
        if ref.get('health') and first is None:first=elapsed
        conn=ref.get('connectivity') or {}
        healthy=(ref.get('health',{}).get('status')=='ok' and ref.get('archive',{}).get('health')=='ok'
                 and conn.get('ws_connected') and conn.get('fresh_books',0)>0
                 and conn.get('native_books_delivered',0)>0 and 'consumer_events' in conn)
        good=good+1 if healthy else 0
        log('startup.jsonl',{'revision':revision,'elapsed':elapsed,'pid':ref['MainPID'],'health':ref.get('health',{}).get('status'),
                            'archive':ref.get('archive',{}).get('health'),'fresh_books':conn.get('fresh_books'),'healthy':bool(healthy)})
        if good>=2:
            validated=attest(PAPER)
            assert validated['service']['MainPID']!=prior
            env=validated['flags']
            if revision==SHA:
                assert env['PYTHONPATH']==str(RELEASE/'backend') and env['NERAIUM_DEPLOYED_SOURCE']==SHA
            else:
                assert not env['PYTHONPATH'] and not env['NERAIUM_DEPLOYED_SOURCE']
            after=state()
            continuity(before,after)
            assert digest(BACKUP)==baseline_files['reference_backup_sha256']
            assert digest(UNIT_FILE)==baseline_files['unit_sha256'] and digest(CONFIG)==baseline_files['config_sha256']
            elapsed=time.monotonic()-begun
            assert elapsed<=1500
            return {'source':revision,'at':now(),'seconds':elapsed,'first_http_seconds':first,'reference':validated,'state':after}
        time.sleep(10)
    raise TimeoutError('original 1500-second reference readiness gate missed')

def capture(pid, experiment, before):
    sampler=ReferenceSampler('http://127.0.0.1:18742/api/market-frame')
    began=time.monotonic()
    deadline=began+900
    requests=[]
    bracket=None
    while time.monotonic()+5<=deadline:
        assert system(PAPER)['MainPID']==pid and attest(UNIT,EXP)==experiment
        assert accounts_unchanged(before)
        start=time.monotonic()
        wall=now()
        sampler.observe()
        receipt=sampler.status()['recent_reads'][-1]
        row={**receipt,'ordinal':len(requests)+1,'wall_started_at':wall,'wall_finished_at':now(),'duration_seconds':time.monotonic()-start}
        requests.append(row)
        log('requests.jsonl',row)
        if len(requests)>=3 and requests[-1]['status']=='accepted' and requests[-3]['status']=='accepted' and requests[-2].get('error','').startswith('ReadTimeout:'):
            bracket=[r['ordinal'] for r in requests[-3:]]
            break
        time.sleep(max(0,5-(time.monotonic()-start)))
    save('capture.json',{'requests':len(requests),'bracket':bracket,'duration_seconds':time.monotonic()-began,'timeouts':sum(r.get('error','').startswith('ReadTimeout:') for r in requests)})
    time.sleep(12)
    output=cmd('sudo','-n','journalctl','-u',PAPER,f'_PID={pid}','--no-pager','-o','cat',timeout=40).decode()
    ids={r['request_id'] for r in requests}
    records=[json.loads(l.split('market_frame_timing ',1)[1]) for l in output.splitlines() if 'market_frame_timing ' in l]
    save('producer.json',[r for r in records if r['request_id'] in ids])

def accounts_unchanged(before):
    from rollout import accounts
    return accounts(BASE)==before['accounts']

def main():
    assert not DROP.exists() and not (HERE/'restart.json').exists()
    source_check()
    assert cmd('systemctl','show',PAPER,'-p','DropInPaths','--value').strip()==b''
    reference=attest(PAPER)
    assert reference['service']['MainPID']=='555731'
    assert not reference['flags']['PYTHONPATH']
    experiment=attest(UNIT,EXP)
    files={'unit_sha256':digest(UNIT_FILE),'config_sha256':digest(CONFIG),'reference_backup_sha256':digest(BACKUP)}
    from guard import inspect
    guard=inspect(full=True)
    assert guard['safety_passed']
    before=state()
    prior=json.loads((HERE.parent/'phase52/final-attestation.json').read_text())
    assert before['native']['backup_sha256']==prior['backup_sha256']
    continuity(json.loads((HERE.parent/"phase52/quiesced-ready.json").read_bytes())["state"],before)
    save('preflight.json',{'verified_baseline':BASELINE,'reference':reference,'experimental':experiment,'files':files,
                           'safety':guard,'state':before})
    config=HERE/'reference-trace.conf'
    config.write_text(f'[Service]\nEnvironment="PYTHONPATH={RELEASE}/backend"\nEnvironment=NERAIUM_DEPLOYED_SOURCE={SHA}\n')
    cmd('sudo','-n','install','-D','-m','644',str(config),str(DROP))
    cmd('sudo','-n','systemctl','daemon-reload')
    begun=time.monotonic()
    save('restart.json',{'at':now(),'source':SHA})
    try:
        cmd('sudo','-n','systemctl','restart',PAPER,timeout=90)
        ready=startup(begun,SHA,reference['service']['MainPID'],experiment,before,files)
        save('ready.json',ready)
        capture(ready['reference']['service']['MainPID'],experiment,before)
        after=state()
        continuity(before,after)
        save('final.json',{'at':now(),'reference':attest(PAPER),'experimental':attest(UNIT,EXP),'state':after})
    except BaseException as error:
        save('incident.json',{'at':now(),'reason':repr(error)})
        prior_pid=system(PAPER)['MainPID']
        assert DROP.read_bytes()==config.read_bytes()
        cmd('sudo','-n','unlink',str(DROP))
        cmd('sudo','-n','systemctl','daemon-reload')
        begun=time.monotonic()
        cmd('sudo','-n','systemctl','restart',PAPER,timeout=90)
        save('rollback.json',startup(begun,BASELINE,prior_pid,experiment,before,files))
        raise

if __name__=='__main__':
    main()
