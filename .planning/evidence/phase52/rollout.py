"""Guard and time a source-only restart of the experimental paper service."""
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx

HERE = Path(__file__).resolve().parent
ROOT = Path('/home/ubuntu/Neraium-Poly')
BASE = ROOT / 'data'
UNIT = 'neraium-poly-experimental.service'
PAPER = 'neraium-poly-paper.service'
DROP = Path('/etc/systemd/system/neraium-poly-experimental.service.d/60-phase39-source.conf')
CANDIDATE = '8d9756ff8a514ad87947646ffc330f0c3e10efc8'
PREVIOUS = '8d8c115d20fc86604cffc4af64657f967b499b63'
RELEASES = ROOT / '.deploy/releases'
FLOOR = 100 * 1024**3
sys.path.insert(0, str(HERE.parent / 'phase51'))
from state import accounts, journal_heads, native, trials
from neraium_poly.research.phase17.provenance import ReadonlyArchive

def save(name, data):
    with (HERE / name).open('w') as stream:
        json.dump(data,stream,indent=2)
        stream.write('\n')

def stamp():
    return datetime.now(UTC).isoformat()

def command(*args, timeout=15):
    return subprocess.check_output(args,cwd=ROOT,timeout=timeout)

def system(unit):
    fields = ['MainPID','ActiveState','SubState','NRestarts','MemoryMax','CPUQuotaPerSecUSec','TasksMax','WorkingDirectory']
    return dict(x.split('=',1) for x in command('systemctl','show',unit,*['-p'+f for f in fields]).decode().splitlines())

def flags(pid):
    environment = dict(x.split(b'=',1) for x in Path(f'/proc/{pid}/environ').read_bytes().split(b'\0') if b'=' in x)
    keys = ('PAPER_TRADING','LIVE_TRADING_ENABLED','NERAIUM_SHADOW_RESEARCH','NERAIUM_DEPLOYED_SOURCE','PYTHONPATH')
    return {key:environment.get(key.encode(),b'').decode() for key in keys}

def digest(data):
    return hashlib.sha256(data).hexdigest()

def release_files(path):
    return {str(p.relative_to(path)):digest(p.read_bytes()) for p in path.rglob('*') if p.is_file() and '__pycache__' not in p.parts}

def state():
    exp = BASE / 'experimental-paper'
    return {'accounts':accounts(BASE),'journals':journal_heads(exp),'native':native(exp),'trials':trials(ReadonlyArchive(exp).get)}

def continuity(old, current):
    for key in ('accounts','trials'):
        assert current[key] == old[key], key
    assert current['native']['backup_sha256'] == old['native']['backup_sha256'], 'backup SHA mismatch'
    assert current['native']['original_files'] == old['native']['original_files'], 'original proof file count'
    assert all(current['native']['proofs'].get(key) == sha for key,sha in old['native']['proofs'].items()), 'proofs changed'
    for suffix, anchor in old['journals'].items():
        actual=current['journals'][suffix]
        assert actual['records'] >= anchor['records'], suffix
        if actual == anchor:
            continue
        path=BASE/'experimental-paper/event-intelligence'/suffix
        table='records' if suffix=='sports/prospective.sqlite' else 'journal'
        with sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=3) as db:
            row=db.execute(f'SELECT chain FROM {table} ORDER BY seq LIMIT 1 OFFSET ?', (anchor['records']-1,)).fetchone()
            assert row and row[0]==anchor['head_sha256'], suffix

def attest(unit, revision=None, shadow_enabled=False):
    service=system(unit)
    env=flags(service['MainPID'])
    assert (env['PAPER_TRADING'],env['LIVE_TRADING_ENABLED'])==('true','false'), unit
    assert service['CPUQuotaPerSecUSec']=='1s'
    assert int(service['MemoryMax'])==(2 if revision else 1)*1024**3
    assert int(service['TasksMax'])==(32 if revision else 64)
    if revision:
        assert env['NERAIUM_DEPLOYED_SOURCE']==revision
        assert env['PYTHONPATH']==str(RELEASES/revision/'backend')
        assert env['NERAIUM_SHADOW_RESEARCH']==str(shadow_enabled).lower()
    # Only retain paper/source fields.
    return {'service':service,'flags':env}

def get(client, port, route):
    r=client.get(f'http://127.0.0.1:{port}/api/{route}')
    r.raise_for_status()
    return r.json()

def ready(source, begun, budget, before, reference_pid, new_pid_from, *, shadow_enabled=False,
          poll_file='readiness-polls.jsonl'):
    deadline = begun + budget
    first_http = None
    with httpx.Client(timeout=3.,trust_env=False) as client:
        while time.monotonic() < deadline:
            row={'at':stamp(),'seconds':time.monotonic()-begun,'source':source}
            assert shutil.disk_usage(ROOT).free > FLOOR, '100 GiB reserve'
            assert system(PAPER)['MainPID']==reference_pid, 'reference PID changed'
            service=system(UNIT)
            row.update(service)
            if service['NRestarts']!='0' or service['ActiveState']=='failed':
                raise RuntimeError('experimental recovery failed or restarted internally')
            try:
                health=get(client,18743,'health')
                row.update(status=health['status'], public_feed=(health.get('public_feed') or {}).get('status'), last_error=health.get('last_error'))
                if first_http is None:
                    first_http=time.monotonic()-begun
                reference=health.get('research_reference') or {}
                row['shared_research_feed']=reference.get('status')
                feed_ok=reference.get('status')=='fresh' if shadow_enabled else row['public_feed']=='ok'
                if row['status']=='ok' and feed_ok:
                    verified=attest(UNIT,source,shadow_enabled)
                    assert verified['service']['MainPID']!=new_pid_from, 'experimental PID did not change'
                    assert health['paper_trading'] is True and health['live_trading_enabled'] is False
                    shadow=get(client,18743,'shadow-research')
                    assert shadow['trading_authority'] is False and shadow.get('actual_account_access') in (None,False)
                    if shadow_enabled:
                        if not (shadow.get('phase45_explorer') and shadow.get('reference_feed')):
                            row['shadow_status']=shadow['status']
                            with (HERE/poll_file).open('a') as stream:
                                stream.write(json.dumps(row)+'\n')
                            time.sleep(min(5.,max(0.,deadline-time.monotonic())))
                            continue
                        assert shadow['actual_account_access'] is False
                    else:
                        assert shadow['status']=='withheld'
                    ref_health=get(client,18742,'health')
                    assert ref_health['status']=='ok' and ref_health['paper_trading'] and not ref_health['live_trading_enabled']
                    after=state()
                    continuity(before,after)
                    elapsed=time.monotonic()-begun
                    assert elapsed<=budget, f'integrity readiness exceeded {budget}s'
                    return {'at':stamp(),'source':source,'first_http_seconds':first_http,
                            'readiness_seconds':elapsed,'budget_seconds':budget,'margin_seconds':budget-elapsed,
                            'experimental':verified,'reference':attest(PAPER),'state':after,
                            'shadow':{k:shadow.get(k) for k in ('status','reason','trading_authority','actual_account_access','cycles')},
                            'disk_free_bytes':shutil.disk_usage(ROOT).free}
            except httpx.HTTPError as error:
                row['http_error']=type(error).__name__
            with (HERE/poll_file).open('a') as stream:
                stream.write(json.dumps(row)+'\n')
            time.sleep(min(5.,max(0.,deadline-time.monotonic())))
    raise RuntimeError(f'paper readiness missed {budget}s gate')

def install(path):
    command('sudo','-n','install','-m','644',str(path),str(DROP))
    command('sudo','-n','systemctl','daemon-reload')

def restart():
    begun=time.monotonic()
    command('sudo','-n','systemctl','restart',UNIT,timeout=120)
    return begun

def main():
    assert not (HERE/'restart-requested.json').exists(), 'guarded rollout already requested'
    assert shutil.disk_usage(ROOT).free > FLOOR
    reference=attest(PAPER)
    experimental=attest(UNIT,PREVIOUS)
    assert experimental['service']['NRestarts']=='0'
    initial_drop=DROP.read_bytes()
    expected_initial = (
        '[Service]\nEnvironment="PYTHONPATH='+str(RELEASES/PREVIOUS/'backend')+'"\n'
        +'Environment=NERAIUM_DEPLOYED_SOURCE='+PREVIOUS+'\nEnvironment=NERAIUM_SHADOW_RESEARCH=false\n'
    ).encode()
    assert initial_drop==expected_initial, 'experimental rollback drop-in differs'
    saved=HERE/'previous-source.conf'
    saved.write_bytes(initial_drop)
    target=HERE/'experimental-source.conf'
    target.write_bytes(initial_drop.replace(PREVIOUS.encode(),CANDIDATE.encode()))
    manifest=json.loads((HERE.parent/'phase48/activation/release-manifest.json').read_bytes())
    assert manifest['source']==PREVIOUS and release_files(RELEASES/PREVIOUS)==manifest['files'], 'rollback release differs'
    ci=json.loads(command('gh','run','view','44187256997','-R','Neraium/Neraium-Poly','--json','conclusion,headSha',timeout=30))
    assert ci=={'conclusion':'success','headSha':CANDIDATE}, 'candidate CI differs'
    release=RELEASES/CANDIDATE
    allowed=('backend','config','pyproject.toml','uv.lock')
    if not release.exists():
        release.mkdir()
        archive=command('git','archive',CANDIDATE,*allowed,timeout=25)
        subprocess.run(['tar','-x','-C',str(release)],input=archive,check=True,timeout=25)
    observed=release_files(release)
    expected_names=command('git','ls-tree','-r','--name-only',CANDIDATE,*allowed).decode().splitlines()
    assert sorted(observed)==sorted(expected_names), 'candidate release file inventory differs'
    for name, hash_ in observed.items():
        assert hash_==digest(command('git','show',f'{CANDIDATE}:{name}')), name
    config=ROOT/'config/experimental-paper.example.json'
    assert config.read_bytes()==(release/'config/experimental-paper.example.json').read_bytes()
    before=state()
    baseline=json.loads((HERE.parent/'phase51/frozen-state.json').read_bytes())
    continuity(baseline,before)
    with httpx.Client(timeout=5,trust_env=False) as client:
        ref=get(client,18742,'health')
        assert ref['status']=='ok' and ref['paper_trading'] and not ref['live_trading_enabled']
        health=get(client,18743,'health')
        assert health['paper_trading'] and not health['live_trading_enabled']
    assert attest(PAPER)['service']['MainPID']==reference['service']['MainPID']
    assert attest(UNIT,PREVIOUS)['service']['MainPID']==experimental['service']['MainPID']
    free=shutil.disk_usage(ROOT).free
    assert free>FLOOR and DROP.read_bytes()==initial_drop
    save('preflight.json',{'at':stamp(),'candidate_ci':ci,'candidate_ci_run':44187256997,
         'release_files':len(observed),'rollback_files':len(manifest['files']),'disk_free_bytes':free,
         'reference':reference,'experimental':experimental,'state':before,'initial_experimental_health':health['status']})
    reference_pid=reference['service']['MainPID']
    old_pid=experimental['service']['MainPID']
    save('restart-requested.json',{'at':stamp(),'source':CANDIDATE,'unit':UNIT,'shadow_quiesced':True})
    try:
        install(target)
        begun=restart()
        save('ready.json',ready(CANDIDATE,begun,900,before,reference_pid,old_pid))
    except BaseException as error:
        save('incident.json',{'at':stamp(),'error':repr(error),'restoring':PREVIOUS})
        failed_pid=system(UNIT)['MainPID']
        assert release_files(RELEASES/PREVIOUS)==manifest['files']
        install(saved)
        begun=restart()
        save('rollback.json',ready(PREVIOUS,begun,1500,before,reference_pid,failed_pid))
        raise

if __name__=='__main__':
    try:
        main()
    except Exception as error:
        print(f'{type(error).__name__}: {error}',file=sys.stderr)
        raise
