"""Controlled concurrency/cleanup checks; not actual service throughput evidence."""
import asyncio
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from anyio import to_thread
from neraium_poly.experimental.executors import configure_execution_pools


async def test_loop_scoped_caps_are_idempotent_and_bound_actual_workers():
    before=to_thread.current_default_thread_limiter().total_tokens
    first=await configure_execution_pools();executor=asyncio.get_running_loop()._default_executor
    assert first['previous_anyio_worker_tokens']==before
    assert await configure_execution_pools()==first
    assert asyncio.get_running_loop()._default_executor is executor
    active={'default':0,'anyio':0};peak=dict(active);threads={'default':set(),'anyio':set()};lock=threading.Lock()
    def work(kind):
        with lock:
            active[kind]+=1;peak[kind]=max(peak[kind],active[kind]);threads[kind].add(threading.current_thread())
        time.sleep(.02)
        with lock:active[kind]-=1
    await asyncio.gather(*(asyncio.to_thread(work,'default') for _ in range(24)),
        *(to_thread.run_sync(work,'anyio') for _ in range(12)))
    assert peak['default']==8 and len(threads['default'])==8
    assert peak['anyio']==4 and len(threads['anyio'])==4
    assert all(t.name.startswith('research-io') for t in threads['default'])
    assert not first['trading_authority'] and not first['certification_authority']


async def test_existing_foreign_pool_is_preserved_without_silent_replacement():
    loop=asyncio.get_running_loop();existing=ThreadPoolExecutor(max_workers=1,thread_name_prefix='CONTROLLED-foreign')
    loop.set_default_executor(existing);limiter=to_thread.current_default_thread_limiter();tokens=limiter.total_tokens
    with pytest.raises(RuntimeError,match='before existing'):
        await configure_execution_pools()
    assert loop._default_executor is existing and limiter.total_tokens==tokens
    assert await asyncio.to_thread(lambda:'CONTROLLED')=='CONTROLLED'


async def test_changed_installed_cap_is_not_reported_as_healthy():
    await configure_execution_pools();limiter=to_thread.current_default_thread_limiter();limiter.total_tokens=9
    try:
        with pytest.raises(RuntimeError,match='cap changed'):await configure_execution_pools()
    finally:limiter.total_tokens=4


def test_loop_shutdown_reaps_created_workers_and_next_loop_has_own_pools():
    observed=[]
    async def lifetime():
        report=await configure_execution_pools();loop=asyncio.get_running_loop()
        def observe():observed.append(threading.current_thread())
        await asyncio.to_thread(observe);await to_thread.run_sync(observe)
        return loop,loop._default_executor,report
    first=asyncio.run(lifetime());second=asyncio.run(lifetime())
    assert first[0].is_closed() and second[0].is_closed() and first[1] is not second[1]
    for thread in observed:
        thread.join(timeout=1)
        assert not thread.is_alive()
