"""Wait for the three baseline windows before an experimental-only source switch."""
import json
import subprocess
import sys
import time
from pathlib import Path

import deploy

HERE = Path(__file__).resolve().parent
EVIDENCE = HERE.parent
BASELINE = EVIDENCE/'baseline/result.json'
end = time.monotonic()+960
while not BASELINE.exists():
    if (BASELINE.parent/'incident.json').exists() or time.monotonic()>=end:
        raise RuntimeError('baseline did not finish; deployment withheld')
    time.sleep(5)
baseline = json.loads(BASELINE.read_text())
assert baseline['post_ready_seconds'] >= 900 and baseline['accounts_unchanged']
subprocess.run([sys.executable,str(EVIDENCE/'preserve.py'),str(EVIDENCE/'preservation-preactivation.json')],check=True,timeout=45)
pre = json.loads((EVIDENCE/'preservation-preactivation.json').read_text())
prior = json.loads((EVIDENCE/'preservation-before.json').read_text())
for key in ('frozen_trials','backup_sha256','plan_sha256'):
    assert pre[key] == prior[key], key

# Only health can retry. Investigate a failed account, source or journal gate immediately.
end = time.monotonic()+90
while True:
    try:
        result = deploy.gate(full=True)
        assert result['services'][deploy.UNIT]['health']['research_reference']['status']=='fresh'
    except AssertionError:
        row = json.loads((HERE/'gate-attempts.jsonl').read_text().splitlines()[-1])
        if not row['safety_passed']:
            raise
        expected = {'neraium-poly-paper.service':'555731', deploy.UNIT:baseline['pid']}
        assert all(row['services'][unit]['MainPID']==pid for unit,pid in expected.items())
        assert deploy.DROP.read_bytes()==(HERE/'current-source.conf').read_bytes()
        if time.monotonic()>=end:
            raise RuntimeError('immediate health gate did not pass within 90 seconds') from None
        time.sleep(5)
    else:
        break

manifest = json.loads((HERE/'release-manifest.json').read_text())
assert manifest['source'] == deploy.SOURCE and deploy.files(deploy.RELEASE) == manifest['files']
assert deploy.DROP.read_bytes() == (HERE/'current-source.conf').read_bytes()
assert json.loads((HERE/'rollback-ready.json').read_text())['source_only']
(HERE/'immediate-gate.json').write_text(json.dumps(result,indent=2)+'\n')
try:
    deploy.command('sudo','-n','install','-m','644',str(HERE/'experimental-source.conf'),str(deploy.DROP))
    deploy.command('sudo','-n','systemctl','daemon-reload')
    deploy.command('sudo','-n','systemctl','restart',deploy.UNIT,timeout=90)
    print('Experimental source switched. Recording readiness and observation.',flush=True)
    subprocess.run([sys.executable,str(EVIDENCE/'observe.py'),'--out',str(EVIDENCE/'after'),'--source',deploy.SOURCE,'--startup'],check=True,timeout=1870)
except (OSError,subprocess.SubprocessError) as exc:
    (HERE/'activation-error.json').write_text(json.dumps({'failure':str(exc)},indent=2)+'\n')
    if deploy.DROP.read_bytes() == (HERE/'experimental-source.conf').read_bytes():
        subprocess.run([sys.executable,str(HERE/'deploy.py'),'--rollback'],check=True,timeout=120)
    raise
