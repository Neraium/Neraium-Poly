"""Three Phase 49 five-minute windows from the experimental shadow endpoint."""
import gzip
import json
import shutil
import sys
import time
from pathlib import Path

import httpx

from rollout import BASE, CANDIDATE, FLOOR, HERE, PAPER, UNIT, accounts, flags, get, stamp, system

polls = HERE / 'freshness-polls.jsonl.gz'
ready = json.loads((HERE / 'ready.json').read_bytes())
reference_pid = ready['reference']['service']['MainPID']
baseline_accounts = ready['state']['accounts']
pid = system(UNIT)['MainPID']

def verify():
    service = system(UNIT)
    env = flags(service['MainPID'])
    assert service['MainPID'] == pid and service['NRestarts'] == '0' and service['ActiveState'] == 'active'
    assert env['NERAIUM_DEPLOYED_SOURCE'] == CANDIDATE and env['NERAIUM_SHADOW_RESEARCH'] == 'true'
    assert env['PAPER_TRADING'] == 'true' and env['LIVE_TRADING_ENABLED'] == 'false'
    assert service['MemoryMax'] == str(2 * 1024**3) and service['CPUQuotaPerSecUSec'] == '1s' and service['TasksMax'] == '32'
    assert system(PAPER)['MainPID'] == reference_pid
    assert shutil.disk_usage(BASE).free > FLOOR
    memory = Path('/sys/fs/cgroup/system.slice',UNIT,'memory.events').read_text()
    assert dict(line.split() for line in memory.splitlines())['oom_kill'] == '0'

def slim_health(health):
    keys = ('status','paper_trading','live_trading_enabled','last_error','research_reference','public_feed')
    result={key:health.get(key) for key in keys}
    result['research_reference']=result['research_reference'] or {}
    return result

def slim_report(report):
    keys = ('status','reason','as_of','cycles','age_seconds','runtime_error','input_frame_available_at',
            'exploratory_frame_available_at','shadow_worker','processing_stages_seconds',
            'freshness_trace','freshness_sample','trading_authority','actual_account_access')
    return {key:report[key] for key in keys if key in report}

if __name__ == '__main__':
    assert sys.argv[1:] == ['--three-windows']
    assert not polls.exists()
    verify()
    assert accounts(BASE) == baseline_accounts
    with httpx.Client(timeout=5,trust_env=False) as client, gzip.open(polls,'xt') as stream:
        start=time.monotonic()
        count=0
        while (elapsed:=time.monotonic()-start) < 900:
            verify()
            row={'at':stamp(),'elapsed':elapsed,'window':int(elapsed//300),'pid':pid}
            try:
                begin=time.monotonic()
                health=get(client,18743,'health')
                assert health['paper_trading'] is True and health['live_trading_enabled'] is False
                row['health']=slim_health(health)
                row['latency']=time.monotonic()-begin
                report=get(client,18743,'shadow-research')
                assert report['trading_authority'] is False and report.get('actual_account_access') in (False,None)
                row['research']=slim_report(report)
                row['sampled_at']=stamp()
            except httpx.HTTPError as error:
                row['api_error']=type(error).__name__
            if count % 6 == 0:
                assert accounts(BASE) == baseline_accounts
                row['accounts_unchanged']=True
            stream.write(json.dumps(row)+'\n')
            stream.flush()
            count+=1
            time.sleep(min(5,max(0,900-(time.monotonic()-start))))
    assert accounts(BASE) == baseline_accounts
