"""Isolated matched fixture, not live market evidence. Run each mode in a new process."""
import asyncio
import json
import resource
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, 'tests')
from test_connectivity import Socket, full
from test_phase24_integration import NOW, inputs
from neraium_poly.data import EventStore
from neraium_poly.research.phase26.coordination import Inputs

async def run():
    cls=Inputs
    if sys.argv[1]=='baseline':
        path='backend/neraium_poly/research/phase26/coordination.py'
        source=subprocess.check_output(['git','show','1342482:'+path],text=True)
        ns={'__file__':'/home/ubuntu/Neraium-Poly/'+path,'__name__':'frozen_coordination'}
        exec(compile(source,path,'exec'),ns);cls=ns['Inputs']
    with tempfile.TemporaryDirectory() as tmp:
        store=EventStore(Path(tmp)/'fixture.sqlite');m,*_=inputs()
        c=cls(store,clock=lambda:NOW,can_write=lambda:True)
        feed=c.watcher.feed;feed.queue_size=64;feed.queue_put_timeout=1;feed.max_reconnects=0
        raw=[full(NOW,token=m.token_id,bids=[{'price':'.39','size':str(100+i)}]) for i in range(200)]
        feed.connector=lambda *a,**kw:Socket([json.dumps(raw)])
        append=store.append
        def slow(record):
            if type(record).__name__=='ResearchInputObservation':time.sleep(3.313)
            return append(record)
        store.append=slow
        lags=[];done=False
        async def probe():
            while not done:
                before=time.monotonic();await asyncio.sleep(.01);lags.append(max(0,time.monotonic()-before-.01))
        probe_task=asyncio.create_task(probe());started=time.monotonic();cpu=time.process_time()
        await c.watcher.update([m]);await asyncio.sleep(4.5)
        metrics=feed.metrics();last=feed.latest.get(m.token_id)
        await c.close();done=True;await probe_task
        print(json.dumps({'mode':sys.argv[1],'fixture_events':200,'archive_delay_seconds':3.313,
            'window_seconds':time.monotonic()-started,'cpu_seconds':time.process_time()-cpu,
            'peak_rss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            'loop_lag_max_seconds':max(lags),'metrics':metrics,
            'callbacks':c.watcher.counts['callbacks_observed'],'final_bid_size':last.bids[0].size if last else None,
            'archive_samples':store.count(kind='ResearchInputObservation'),
            'sqlite_quick_check':store.connection.execute('PRAGMA quick_check').fetchone()[0]}))
        store.close()

asyncio.run(run())
