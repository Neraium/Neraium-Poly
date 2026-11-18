"""Resume read-only rollback verification after observer interruption."""
import json
from operate import HERE, BASELINE, PAPER, DROP, cmd, startup, save, system

pre=json.loads((HERE/'preflight.json').read_bytes())
assert not DROP.exists()
last=next(r for r in reversed([json.loads(s) for s in (HERE/'startup.jsonl').read_text().splitlines()]) if r['revision']==BASELINE)
assert system(PAPER)['MainPID']==last['pid']
started=int(cmd('systemctl','show',PAPER,'--property=ExecMainStartTimestampMonotonic','--value'))/1e6-.5
save('rollback.json',startup(started,BASELINE,'863334',pre['experimental'],pre['state'],pre['files']))
