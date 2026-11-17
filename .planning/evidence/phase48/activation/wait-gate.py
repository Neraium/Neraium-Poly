"""Bounded unchanged health-gate retry; safety failures abort, never relax limits."""
import json,time,sys
from pathlib import Path
import deploy
HERE=Path(__file__).resolve().parent;end=time.monotonic()+90
post='--post' in sys.argv
if post:deploy.OLD=deploy.SOURCE
expected_pid=json.loads((HERE/'observation/samples.jsonl').read_text().splitlines()[0])['service']['MainPID'] if post else '588342'
while True:
 try:
  r=deploy.gate(full=True)
  assert r['services'][deploy.UNIT]['health']['research_reference']['status']=='fresh'
  (HERE/('postflight-health.json' if post else 'preflight.json')).write_text(json.dumps(r,indent=2)+'\n');print('All immediate health, source, account and journal gates passed',flush=True);break
 except AssertionError:
  r=json.loads((HERE/'gate-attempts.jsonl').read_text().splitlines()[-1])
  if not r.get('safety_passed'):raise
  expected={'neraium-poly-paper.service':'555731',deploy.UNIT:expected_pid}
  assert all(r['services'][n]['MainPID']==pid and r['services'][n]['ActiveState']=='active' for n,pid in expected.items())
  if time.monotonic()>=end:raise ValueError('Immediate health gates did not pass within90s') from None
  time.sleep(5)
