"""Resume the in-flight quiescence gate after the external monitor exited."""
import gzip
import json
import time
from datetime import UTC, datetime

from rollout import CANDIDATE, DROP, HERE, PAPER, PREVIOUS, RELEASES, UNIT, attest, install, ready, release_files, restart, save, stamp, system

assert (HERE/'quiesce-restart-requested.json').is_file()
assert all(not (HERE/name).exists() for name in ('window-incident.json','quiesced-ready.json','window-rollback.json'))
assert DROP.read_bytes()==(HERE/'experimental-source.conf').read_bytes()
with gzip.open(HERE/'freshness-polls.jsonl.gz','rt') as stream:
    assert {json.loads(line)['window'] for line in stream}=={0,1,2}
preflight=json.loads((HERE/'preflight.json').read_bytes())
enabled=json.loads((HERE/'shadow-ready.json').read_bytes())
reference_pid=preflight['reference']['service']['MainPID']
before=preflight['state']
assert system(PAPER)['MainPID']==reference_pid
pid=attest(UNIT,CANDIDATE)['service']['MainPID']
assert pid!=enabled['experimental']['service']['MainPID']
poll_file='quiesce-readiness-polls.jsonl'
first=json.loads((HERE/poll_file).read_text().splitlines()[0])
assert pid==first['MainPID']
since_poll=(datetime.now(UTC)-datetime.fromisoformat(first['at'])).total_seconds()
start=time.monotonic()-since_poll-first['seconds']-.02
save('quiesce-guard-handover.json',{'at':stamp(),'seconds_since_original_restart':time.monotonic()-start,
     'pid':pid,'deadline_seconds':900,'cause':'external monitor exited with status 143 while the service kept recovering'})
try:
    final=ready(CANDIDATE,start,900,before,reference_pid,enabled['experimental']['service']['MainPID'],poll_file=poll_file)
    save('quiesced-ready.json',final)
except BaseException as error:
    save('window-incident.json',{'at':stamp(),'stage':'quiesce_shadow','error':repr(error),'restoring':PREVIOUS})
    manifest=json.loads((HERE.parent/'phase48/activation/release-manifest.json').read_bytes())
    assert release_files(RELEASES/PREVIOUS)==manifest['files']
    install(HERE/'previous-source.conf')
    start=restart()
    save('window-rollback.json',ready(PREVIOUS,start,1500,before,reference_pid,pid,poll_file='restore-readiness-polls.jsonl'))
    raise
