"""Use the two authorized same-source restarts for a bounded shadow observation."""
import json
import shutil
import subprocess
import sys
import time
from datetime import UTC, datetime

from rollout import (
    CANDIDATE, DROP, FLOOR, HERE, PAPER, PREVIOUS, RELEASES, UNIT, attest,
    continuity, install, ready, release_files, restart, save, stamp, state, system,
)


def run(resume=False):
    initial=json.loads((HERE/'ready.json').read_bytes())
    baseline=json.loads((HERE/'preflight.json').read_bytes())['state']
    assert initial['source']==CANDIDATE and initial['readiness_seconds']<=900
    assert not (HERE/'incident.json').exists()
    assert (HERE/'shadow-restart-requested.json').exists()==resume
    reference_pid=initial['reference']['service']['MainPID']
    assert system(PAPER)['MainPID']==reference_pid
    still=attest(UNIT,CANDIDATE,resume)
    old_pid=initial['experimental']['service']['MainPID']
    assert (still['service']['MainPID']!=old_pid)==resume
    continuity(baseline,state())
    rollback=HERE/'previous-source.conf'
    manifest=json.loads((HERE.parent/'phase48/activation/release-manifest.json').read_bytes())
    assert release_files(RELEASES/PREVIOUS)==manifest['files']
    assert rollback.read_bytes()==(HERE.parent/'phase49/activation/previous-source.conf').read_bytes()
    off=HERE/'experimental-source.conf'
    on=HERE/'experimental-shadow.conf'
    assert DROP.read_bytes()==(on if resume else off).read_bytes()
    on.write_bytes(off.read_bytes().replace(b'NERAIUM_SHADOW_RESEARCH=false',b'NERAIUM_SHADOW_RESEARCH=true'))
    assert on.read_bytes()!=off.read_bytes()
    stage='enable_shadow'
    if not resume:
        save('shadow-restart-requested.json',{'at':stamp(),'source':CANDIDATE,'shadow_enabled':True})
    try:
        assert shutil.disk_usage(HERE).free>FLOOR
        if resume:
            first=json.loads((HERE/'enable-readiness-polls.jsonl').read_text().splitlines()[0])
            since_poll=(datetime.now(UTC)-datetime.fromisoformat(first['at'])).total_seconds()
            start=time.monotonic()-since_poll-first['seconds']-.02
            save('guard-handover.json',{'at':stamp(),'seconds_since_original_restart':time.monotonic()-start,
                 'original_restart_pid':still['service']['MainPID'],'deadline_seconds':900,
                 'cause':'enabled cycles use ReferenceSampler rather than SharedFeedClient'})
        else:
            install(on)
            start=restart()
        enabled=ready(CANDIDATE,start,900,baseline,reference_pid,old_pid,
                      shadow_enabled=True,poll_file='enable-readiness-polls.jsonl')
        save('shadow-ready.json',enabled)
        stage='three_freshness_windows'
        subprocess.run([sys.executable,str(HERE/'observe.py'),'--three-windows'],check=True,timeout=930)
        stage='quiesce_shadow'
        save('quiesce-restart-requested.json',{'at':stamp(),'source':CANDIDATE,'shadow_enabled':False})
        assert DROP.read_bytes()==on.read_bytes(), 'running shadow drop-in changed'
        assert shutil.disk_usage(HERE).free>FLOOR
        continuity(baseline,state())
        install(off)
        start=restart()
        final=ready(CANDIDATE,start,900,baseline,reference_pid,enabled['experimental']['service']['MainPID'],
                    poll_file='quiesce-readiness-polls.jsonl')
        save('quiesced-ready.json',final)
    except BaseException as error:
        save('window-incident.json',{'at':stamp(),'stage':stage,'error':repr(error),'restoring':PREVIOUS})
        failed_pid=system(UNIT)['MainPID']
        assert release_files(RELEASES/PREVIOUS)==manifest['files']
        install(rollback)
        start=restart()
        save('window-rollback.json',ready(PREVIOUS,start,1500,baseline,reference_pid,failed_pid,
                                          poll_file='restore-readiness-polls.jsonl'))
        raise

if __name__=='__main__':
    assert sys.argv[1:] in (['--authorized-two-restarts'],['--resume-enabled-gate'])
    run('--resume-enabled-gate' in sys.argv)
