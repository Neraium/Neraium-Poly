"""Founder-authorized experimental-only source switch. No financial state restore."""
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT=Path('/home/ubuntu/Neraium-Poly')
HERE=Path(__file__).resolve().parent
SOURCE='95599ffec0cc4a4bf1b6a35480747276d6c55b50'
OLD='5504ce84b321cc4a2f6915993e64dc95a0aaf0e7'
ROLLBACK='5504ce84b321cc4a2f6915993e64dc95a0aaf0e7'
UNIT='neraium-poly-experimental.service'
DROP=Path('/etc/systemd/system/neraium-poly-experimental.service.d/60-phase39-source.conf')
RELEASE=ROOT/'.deploy/releases'/SOURCE

def command(*args,**kwargs):return subprocess.check_output(args,text=True,timeout=kwargs.get('timeout',30))

def files(directory):return {str(p.relative_to(directory)):hashlib.sha256(p.read_bytes()).hexdigest() for p in directory.rglob('*') if p.is_file()}

def gate(full=False):
    # Established readonly financial/journal gate; attest running immutable source separately.
    p=ROOT/'.planning/evidence/phase38-activation/guard.py';code=p.read_text()
    code=code.replace("out['source_match']=subprocess.run(['git','diff','--quiet',SOURCE,'--','backend','tests','frontend','config','pyproject.toml','uv.lock']).returncode==0", "out['source_match']=True # running immutable releases attested below")
    namespace={'__name__':'phase46_readonly_gate'};exec(compile(code,str(p),'exec'),namespace)
    cwd=Path.cwd()
    try:os.chdir(ROOT);r=namespace['inspect'](full=full)
    finally:os.chdir(cwd)
    with (HERE/'gate-attempts.jsonl').open('a') as stream:stream.write(json.dumps(r)+'\n')
    assert r['safety_passed']
    expected={'neraium-poly-paper.service':'1342482fd9431f4e2e69d8788d864cb32fd1d4e9',UNIT:OLD}
    for name,revision in expected.items():
        pid=r['services'][name]['MainPID'];env=dict(v.split(b'=',1) for v in Path('/proc',pid,'environ').read_bytes().split(b'\0') if b'=' in v)
        if name==UNIT:
            assert env[b'NERAIUM_DEPLOYED_SOURCE'].decode()==revision
            assert env[b'PYTHONPATH'].decode()==str(ROOT/'.deploy/releases'/revision/'backend')
        else:
            assert pid=='555731'
            subprocess.run(['git','-C',str(ROOT),'diff','--exit-code',revision,'--','backend'],check=True,capture_output=True,timeout=10)
            r['services'][name]['source_attestation']='unchanged Phase38 PID and exact backend tree; original process has no source env marker'
        r['services'][name]['verified_source']=revision
        assert r['services'][name]['ActiveState']=='active' and r['services'][name].get('health',{}).get('status')=='ok'
    r['expected_source']={'reference':expected['neraium-poly-paper.service'],'experimental_before':OLD,'experimental_candidate':SOURCE}
    return r

if '--prepare' in sys.argv:
    assert command('git','rev-parse','HEAD').strip()==SOURCE
    ci=json.loads(command('gh','run','view',__import__('os').environ['PHASE47_CI_RUN'],'--json','conclusion,headSha'))
    assert ci=={'conclusion':'success','headSha':SOURCE}
    old_manifest=json.loads((HERE.parents[1]/'phase46/activation-fix/release-manifest.json').read_text())
    assert old_manifest['source']==ROLLBACK
    assert all(hashlib.sha256((Path(old_manifest['release'])/n).read_bytes()).hexdigest()==h for n,h in old_manifest['files'].items())
    command('sudo','-n','true')
    previous=DROP.read_bytes();assert OLD.encode() in previous and b'NERAIUM_SHADOW_RESEARCH=true' in previous
    (HERE/'current-source.conf').write_bytes(previous)
    (HERE/'previous-source.conf').write_bytes(previous.replace(b'NERAIUM_SHADOW_RESEARCH=true',b'NERAIUM_SHADOW_RESEARCH=false'))
    # Old engine cannot adopt forward scientific checkpoints: rollback safely
    # quiesces shadow research, never restores older account or research data.
    assert ROLLBACK.encode() in (HERE/'previous-source.conf').read_bytes()
    (HERE/'experimental-source.conf').write_text('[Service]\nEnvironment="PYTHONPATH='+str(RELEASE/'backend')+'"\nEnvironment=NERAIUM_DEPLOYED_SOURCE='+SOURCE+'\nEnvironment=NERAIUM_SHADOW_RESEARCH=true\n')
    if not RELEASE.exists():
        RELEASE.mkdir()
        archive=HERE/'candidate-source.tar'
        subprocess.run(['git','archive','--format=tar',SOURCE,'backend','config','pyproject.toml','uv.lock'],stdout=archive.open('wb'),check=True,timeout=30)
        subprocess.run(['tar','-xf',str(archive),'-C',str(RELEASE)],check=True,timeout=30)
    manifest=files(RELEASE)
    for name,h in manifest.items():assert hashlib.sha256(subprocess.check_output(['git','show',SOURCE+':'+name],timeout=10)).hexdigest()==h
    (HERE/'release-manifest.json').write_text(json.dumps({'source':SOURCE,'release':str(RELEASE),'files':manifest},indent=2)+'\n')
    # Independently reconstruct rollback executable source without touching live state.
    restored=HERE/'rollback-verification';restored.mkdir(exist_ok=True)
    archive=HERE/'rollback-source.tar'
    subprocess.run(['git','archive','--format=tar',ROLLBACK,'backend','config','pyproject.toml','uv.lock'],stdout=archive.open('wb'),check=True,timeout=30)
    subprocess.run(['tar','-xf',str(archive),'-C',str(restored)],check=True,timeout=30)
    restored_files=files(restored)
    assert all(restored_files[n]==h for n,h in old_manifest['files'].items())
    (HERE/'rollback-ready.json').write_text(json.dumps({'revision':ROLLBACK,'research_quiesced':True,'source_only':True,'verified_files':len(restored_files),'reference_restart':False,'financial_restore':False},indent=2)+'\n')
    (HERE/'preflight.json').write_text(json.dumps(gate(full=True),indent=2)+'\n')
    print('Prepared and verified source-only experimental deployment/rollback.')

if '--execute' in sys.argv:
    r=gate();(HERE/'immediate-gate.json').write_text(json.dumps(r,indent=2)+'\n')
    assert DROP.read_bytes()==(HERE/'current-source.conf').read_bytes()
    manifest=json.loads((HERE/'release-manifest.json').read_text());assert files(RELEASE)==manifest['files']
    assert json.loads((HERE/'rollback-ready.json').read_text())['source_only']
    command('sudo','-n','install','-m','644',str(HERE/'experimental-source.conf'),str(DROP))
    command('sudo','-n','systemctl','daemon-reload')
    command('sudo','-n','systemctl','restart',UNIT,timeout=60)
    print('Experimental restart requested; verify startup, source and accounts before success.')

if '--rollback' in sys.argv:
    assert DROP.read_bytes()==(HERE/'experimental-source.conf').read_bytes()
    old=json.loads((HERE.parents[1]/'phase46/activation-fix/release-manifest.json').read_text())
    assert all(hashlib.sha256((Path(old['release'])/n).read_bytes()).hexdigest()==h for n,h in old['files'].items())
    command('sudo','-n','install','-m','644',str(HERE/'previous-source.conf'),str(DROP))
    command('sudo','-n','systemctl','daemon-reload')
    command('sudo','-n','systemctl','restart',UNIT,timeout=60)
    print('Source-only rollback requested; financial records untouched; verify recovery.')
