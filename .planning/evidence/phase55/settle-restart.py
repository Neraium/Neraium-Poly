"""Finish the already authorized startup gate without starting a capture."""
import json
import time
from datetime import UTC, datetime
from operate import HERE, DROP, PAPER, SHA, BASELINE, cmd, save, startup, system, source_check

pre=json.loads((HERE/'preflight.json').read_text())
restart=json.loads((HERE/'restart.json').read_text())
assert restart['source']==SHA and DROP.read_bytes()==(HERE/'reference-trace.conf').read_bytes()
old=pre['reference']['service']['MainPID']
assert system(PAPER)['MainPID']!=old
begun=time.monotonic()-(datetime.now(UTC)-datetime.fromisoformat(restart['at'])).total_seconds()-.1
try:
    save('ready.json',startup(begun,SHA,old,pre['experimental'],pre['state'],pre['files']))
except BaseException as error:
    save('incident.json',{'reason':repr(error)})
    source_check()
    previous=system(PAPER)['MainPID']
    cmd('sudo','-n','unlink',str(DROP))
    cmd('sudo','-n','systemctl','daemon-reload')
    begun=time.monotonic()
    cmd('sudo','-n','systemctl','restart',PAPER,timeout=90)
    save('rollback.json',startup(begun,BASELINE,previous,pre['experimental'],pre['state'],pre['files']))
    raise
