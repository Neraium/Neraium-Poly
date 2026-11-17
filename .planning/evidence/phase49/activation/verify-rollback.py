"""Verify source-only rollback recovery without shadow orders or financial restoration."""
import json
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx

import deploy

HERE = Path(__file__).resolve().parent
deploy.OLD = deploy.ROLLBACK
deadline = time.monotonic()+1500
with httpx.Client(timeout=5,trust_env=False) as client:
    while True:
        pid = deploy.command('systemctl','show',deploy.UNIT,'-p','MainPID','--value').strip()
        at = datetime.now(UTC).isoformat()
        row = {'at':at,'pid':pid}
        try:
            reply = client.get('http://127.0.0.1:18743/api/health')
            reply.raise_for_status()
            row['health'] = reply.json()
        except httpx.HTTPError as exc:
            row['error'] = type(exc).__name__
        with (HERE/'rollback-observation.jsonl').open('a') as out:
            out.write(json.dumps(row)+'\n')
        if row.get('health',{}).get('status')=='ok':
            try:
                gates = deploy.gate(full=True)
                env = dict(v.split(b'=',1) for v in Path('/proc',pid,'environ').read_bytes().split(b'\0') if b'=' in v)
                assert env[b'NERAIUM_SHADOW_RESEARCH']==b'false'
                assert env[b'PAPER_TRADING']==b'true' and env[b'LIVE_TRADING_ENABLED']==b'false'
                assert deploy.DROP.read_bytes()==(HERE/'previous-source.conf').read_bytes()
            except AssertionError:
                recent = json.loads((HERE/'gate-attempts.jsonl').read_text().splitlines()[-1])
                if not recent['safety_passed']:
                    raise
            else:
                (HERE/'rollback-verified.json').write_text(json.dumps({'ready_at':at,'pid':pid,'source':deploy.ROLLBACK,'shadow_research_quiesced':True,'gates':gates},indent=2)+'\n')
                break
        if time.monotonic()>=deadline:
            subprocess.run(['systemctl','show',deploy.UNIT,'-p','MainPID','-p','NRestarts','-p','ActiveState'],check=False,timeout=5)
            raise RuntimeError('rollback API did not pass recovery verification within 1500 seconds')
        time.sleep(5)
