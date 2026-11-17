"""Production ExperimentalRuntime and loopback health route on reduced isolated fixture."""
import asyncio
import hashlib
import json
import os
import resource
import shutil
import socket
import sqlite3
import sys
import time
from contextlib import closing
from pathlib import Path

import httpx
import uvicorn
from neraium_poly.experimental.config import ExperimentalConfig
from neraium_poly.experimental.executors import configure_execution_pools
from neraium_poly.experimental.runtime import ExperimentalRuntime
from neraium_poly.ops.api import create_app

snapshot,capsule,work,out=map(Path,sys.argv[1:5])
live=Path('/home/ubuntu/Neraium-Poly')
assert not work.exists() and not work.resolve().is_relative_to(live/'data')
shutil.copytree(snapshot,work/'experimental')
shutil.copytree(capsule/'experimental-paper',work/'experimental',dirs_exist_ok=True)
shutil.copytree(capsule/'paper-live',work/'reference')
dependency=capsule/'segment-00090000.sqlite'
shutil.copyfile(dependency,work/'experimental/events-segments'/dependency.name)
for path in work.rglob('*'):
    if path.is_file():
        with path.open('r+b') as stream:
            os.fsync(stream.fileno())
            os.posix_fadvise(stream.fileno(),0,0,os.POSIX_FADV_DONTNEED)

def accounts():
    output={}
    for name in ('experimental','reference'):
        directory=work/name
        with closing(sqlite3.connect((directory/'risk.sqlite').as_uri()+'?mode=ro',uri=True)) as db:
            output[name]={'risk':db.execute('SELECT * FROM account').fetchall(),
                          'positions':db.execute('SELECT * FROM positions').fetchall(),
                          'reservations':db.execute('SELECT * FROM reservations').fetchall()}
        with closing(sqlite3.connect((directory/'broker.sqlite').as_uri()+'?mode=ro',uri=True)) as db:
            output[name]['orders']=db.execute('SELECT * FROM orders').fetchall()
    return output

async def main():
    await configure_execution_pools()
    before=accounts()
    config=json.loads((live/'config/experimental-paper.example.json').read_text())
    config.update(data_dir=work/'experimental',certified_directory=work/'reference')
    server_socket=socket.socket()
    server_socket.bind(('127.0.0.1',0))
    port=server_socket.getsockname()[1]
    config['port']=port
    began=time.perf_counter()
    runtime=ExperimentalRuntime(ExperimentalConfig.model_validate(config))
    initialized=time.perf_counter()-began
    server=uvicorn.Server(uvicorn.Config(create_app(runtime=runtime,local_port=port),host='127.0.0.1',port=port,log_level='warning',lifespan='off'))
    task=asyncio.create_task(server.serve(sockets=[server_socket]))
    try:
        for _ in range(100):
            if server.started:
                break
            await asyncio.sleep(.01)
        assert server.started
        async with httpx.AsyncClient(timeout=5,trust_env=False) as client:
            resp=await client.get(f'http://127.0.0.1:{port}/api/health')
            resp.raise_for_status()
            ready=time.perf_counter()-began
            health=resp.json()
            assert health['paper_trading'] is True and health['live_trading_enabled'] is False
        assert accounts()==before
        originals=json.loads((capsule/'frozen-trials.json').read_bytes())
        for identity, raw in originals.items():
            saved=runtime.events.get(identity)
            assert saved[1]==raw and saved[2]==hashlib.sha256(raw.encode()).hexdigest()
    finally:
        server.should_exit=True
        await task
        await runtime.close()
    assert accounts()==before
    out.write_text(json.dumps({'runtime_initialized_seconds':initialized,'first_http_health_response_seconds':ready,'health':health,'accounts_identical':True,'frozen_trial_bytes_preserved':len(originals),
      'peak_rss_KiB':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
      'scope':'Identical reduced sealed corpus and independent committed account copies. Production runtime and HTTP route, no ingestion workers, original certificate data or live accounts. HTTP readiness is not full operational readiness.',
      'cache':'fsync and DONTNEED on isolated copied file inodes'},indent=2)+'\n')

asyncio.run(main())
