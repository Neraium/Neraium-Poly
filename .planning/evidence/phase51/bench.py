"""Production paper runtime with an isolated, full archive and timed readiness."""
import asyncio
import json
import os
import socket
import sqlite3
import sys
import time
from collections import defaultdict
from datetime import UTC,datetime
from pathlib import Path

import httpx
import uvicorn

from neraium_poly.data import cold,segmented
from neraium_poly.experimental.config import ExperimentalConfig
from neraium_poly.experimental.executors import configure_execution_pools
from neraium_poly.experimental.runtime import ExperimentalRuntime
from neraium_poly.ops.api import create_app
from state import accounts,journal_heads,native,trials

root,anchor_path,out=map(Path,sys.argv[1:4])
live=Path('/home/ubuntu/Neraium-Poly')
assert bool(os.statvfs(live).f_flag & os.ST_RDONLY)
assert root==live/'data'
mounts=Path('/proc/self/mountinfo').read_text().splitlines()
assert any(line.split()[4]==str(root) and ' - overlay ' in line for line in mounts)
assert not any(line.split()[4]==str(root) and ' - ext4 ' in line for line in mounts)
assert not bool(os.statvfs(root).f_flag & os.ST_RDONLY)
assert os.environ['NERAIUM_SHADOW_RESEARCH']=='false'
baseline=json.loads(anchor_path.read_text())
stats=defaultdict(lambda:{'calls':0,'seconds':0.,'bytes':0})

def io():
    return {key:int(value) for key,value in (l.split(':',1) for l in Path('/proc/self/io').read_text().splitlines())}

def emit(path,data):
    (out/path).write_text(json.dumps(data,indent=2)+'\n')

def wrap(target,name,measure_bytes=False):
    original=getattr(target,name)
    stage=f'{getattr(target,"__name__",type(target).__name__)}.{name}'
    def timed(*args,**kwargs):
        row=stats[stage]
        row['calls']+=1
        if measure_bytes:
            row['bytes']+=args[0].stat().st_size
        start=time.monotonic()
        try:
            return original(*args,**kwargs)
        finally:
            row['seconds']+=time.monotonic()-start
            if name=='_index_segment' and row['calls']%500==0:
                emit('progress.json',{'elapsed':time.monotonic()-began,'timing':stats,'io':io()})
    setattr(target,name,timed)

for name in ('__init__','_recover','_index_segment','_verify_compressed','_verify_cold','_catalog_record','status'):
    wrap(segmented.ManagedEventStore,name)
wrap(segmented,'_sha',True)
wrap(cold,'_sha',True)
wrap(segmented,'_tree_size')

class TimedConnection(sqlite3.Connection):
    def execute(self, sql, parameters=()):
        if sql.strip().upper()!='PRAGMA QUICK_CHECK':
            return super().execute(sql,parameters)
        start=time.monotonic()
        try:
            return super().execute(sql,parameters)
        finally:
            row=stats['sqlite.quick_check']
            row['calls']+=1
            row['seconds']+=time.monotonic()-start

connect=sqlite3.connect
def timed_connect(*args,**kwargs):
    kwargs.setdefault('factory',TimedConnection)
    return connect(*args,**kwargs)

async def main():
    global began
    await configure_execution_pools()
    config=json.loads((live/'config/experimental-paper.example.json').read_text())
    listener=socket.socket()
    listener.bind(('127.0.0.1',0))
    port=listener.getsockname()[1]
    if port in (18740,18741,18742,18743):
        raise RuntimeError('unexpected production loopback port')
    config.update(data_dir=root/'experimental-paper',certified_directory=root/'paper-live',port=port)
    pre=accounts(root)
    assert pre==baseline['accounts']
    sqlite3.connect=timed_connect
    before=io()
    began=int(os.environ['PHASE51_LAUNCH_NS'])/1e9
    emit('started.json',{'utc':datetime.now(UTC).isoformat(),'port':port,'source':os.environ['NERAIUM_DEPLOYED_SOURCE'],
                         'readonly_live_checkout_verified':True,'canonical_data_path_is_overlay_verified':True,'cold_cache_scope':'shared sealed ext4 backing; new overlay and private mutable copy-up; no eviction'})
    runtime=ExperimentalRuntime(ExperimentalConfig.model_validate(config))
    runtime_initialized=time.monotonic()-began
    source_read={key:value-before[key] for key,value in io().items()}
    verified_at_init={'accounts':accounts(root),'journals':journal_heads(root/'experimental-paper'),
                      'native':native(root/'experimental-paper'),'trials':trials(runtime.events.get)}
    assert verified_at_init==baseline
    attest=time.monotonic()-began
    server=uvicorn.Server(uvicorn.Config(create_app(runtime=runtime,local_port=port),host='127.0.0.1',port=port,log_level='warning',lifespan='off'))
    serving=asyncio.create_task(server.serve(sockets=[listener]))
    work=asyncio.create_task(runtime.run(lambda:server.should_exit))
    first=None
    gate=None
    rejected=[]
    try:
        async with httpx.AsyncClient(timeout=4,trust_env=False) as client:
            while time.monotonic()-began<1180:
                if serving.done() or work.done():
                    raise RuntimeError('isolated service exited before readiness')
                try:
                    response=await client.get(f'http://127.0.0.1:{port}/api/health')
                    response.raise_for_status()
                    if first is None:
                        first=time.monotonic()-began
                    health=response.json()
                    if (health['status']=='ok' and health['paper_trading'] is True and health['live_trading_enabled'] is False
                       and (health.get('public_feed') or {}).get('status')=='ok'):
                        shadow=(await client.get(f'http://127.0.0.1:{port}/api/shadow-research')).json()
                        assert shadow['status']=='withheld' and not shadow['trading_authority']
                        assert accounts(root)==pre
                        gate=time.monotonic()-began
                        break
                    rejected.append({'at':time.monotonic()-began,'health':health['status'],'last_error':health['last_error']})
                except httpx.HTTPError as error:
                    rejected.append({'at':time.monotonic()-began,'error':type(error).__name__})
                await asyncio.sleep(.5)
        result={'source':os.environ['NERAIUM_DEPLOYED_SOURCE'],'runtime_initialized_seconds':runtime_initialized,
                'state_verification_complete_seconds':attest,'first_http_seconds':first,'readiness_seconds':gate,
                'passed_900_seconds':gate is not None and gate<=900,'margin_seconds':900-gate if gate is not None else None,
                'state_equivalent_at_start':verified_at_init,'stage_metrics_inclusive':dict(stats),'io_until_initialized':source_read,
                'readiness':'real experimental runtime, archive reconstructed; isolated state verified, healthy live-reference ingest and paper flags, shadow report withheld',
                'poll_rejections':rejected}
        emit('result.json',result)
    finally:
        server.should_exit=True
        await serving
        await work
        await runtime.close()
    emit('post.json',{'accounts_unchanged':accounts(root)==pre,'forecast_heads_equal_at_gate':journal_heads(root/'experimental-paper')==baseline['journals']})
    assert accounts(root)==pre

asyncio.run(main())
