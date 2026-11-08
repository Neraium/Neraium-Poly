"""Controlled worker isolation; no market forecasting/performance evidence."""
import asyncio
import threading
import time

import pytest
from neraium_poly.experimental.research_worker import ResearchWorker


async def reached(event):
    deadline=time.monotonic()+3
    while not event.is_set():
        assert time.monotonic()<deadline
        await asyncio.sleep(.005)


async def test_slow_sync_research_archive_work_does_not_block_caller_loop():
    worker=ResearchWorker();entered=threading.Event();release=threading.Event()
    async def slow():
        entered.set();assert release.wait(3);return threading.get_ident()
    task=asyncio.create_task(worker.run(slow));await reached(entered);gaps=[];last=time.monotonic()
    try:
        for _ in range(10):
            await asyncio.sleep(.005);now=time.monotonic();gaps.append(now-last);last=now
        assert max(gaps)<.06 and not task.done()
        release.set();assert await task!=threading.get_ident()
    finally:release.set();await worker.close()


async def test_same_loop_and_loop_bound_state_survive_multiple_calls():
    worker=ResearchWorker();lock=None;loops=[]
    async def model():
        nonlocal lock
        if lock is None:lock=asyncio.Lock()
        async def contend():
            async with lock:
                loops.append(asyncio.get_running_loop());await asyncio.sleep(.005)
        await asyncio.gather(contend(),contend())
        return threading.get_ident()
    try:
        identities=[await worker.run(model) for _ in range(3)]
        assert len(set(identities))==1 and len(set(loops))==1
        assert loops[0] is not asyncio.get_running_loop()
        async def inside():
            with pytest.raises(RuntimeError,match='submit to itself'):await worker.run(model)
        await worker.run(inside)
    finally:await worker.close()


async def test_one_active_job_queued_cancellation_submits_nothing():
    worker=ResearchWorker();entered=threading.Event();release=threading.Event();calls=[]
    async def active():calls.append('active');entered.set();assert release.wait(3)
    async def queued():calls.append('queued')
    task=asyncio.create_task(worker.run(active));await reached(entered)
    waiting=asyncio.create_task(worker.run(queued));await asyncio.sleep(.01);waiting.cancel()
    with pytest.raises(asyncio.CancelledError):await waiting
    try:
        assert calls==['active'] and worker.status()['submitted']==1
        release.set();await task
        assert worker.status()['active_jobs']==0
    finally:release.set();await worker.close()


async def test_repeated_cancellation_drains_running_job_and_shutdown():
    worker=ResearchWorker();entered=threading.Event();release=threading.Event();finished=[]
    async def active():entered.set();assert release.wait(3);finished.append(True)
    task=asyncio.create_task(worker.run(active));await reached(entered);task.cancel();await asyncio.sleep(.01);task.cancel()
    close=asyncio.create_task(worker.close());await asyncio.sleep(.01);close.cancel();await asyncio.sleep(.01);close.cancel()
    assert not task.done() and not close.done() and not finished
    release.set()
    with pytest.raises(asyncio.CancelledError):await task
    with pytest.raises(asyncio.CancelledError):await close
    assert finished==[True] and worker.status()['closed'] and not worker.status()['worker_alive']
    await worker.close()
    with pytest.raises(RuntimeError,match='closed'):await worker.run(active)


async def test_failure_keeps_lane_usable_and_closes_without_leaks():
    worker=ResearchWorker()
    async def fail():raise ValueError('CONTROLLED failed verification')
    with pytest.raises(ValueError,match='failed verification'):await worker.run(fail)
    async def success():return 'CONTROLLED'
    assert await worker.run(success)=='CONTROLLED'
    await asyncio.gather(worker.close(),worker.close())
    assert not worker.status()['worker_alive'] and worker.status()['completed']==2


async def test_close_before_use_and_invalid_factories():
    worker=ResearchWorker()
    with pytest.raises(TypeError,match='callable'):await worker.run(None)
    with pytest.raises(TypeError,match='coroutine'):await worker.run(lambda:42)
    await worker.close();await worker.close()
    unused=ResearchWorker();await unused.close()
    assert not unused.status()['worker_alive']


async def test_shutdown_failure_propagates_after_thread_is_joined():
    worker=ResearchWorker()
    async def arm_failure():
        loop=asyncio.get_running_loop()
        async def fail():raise ValueError('CONTROLLED cleanup failure')
        loop.shutdown_asyncgens=fail
    await worker.run(arm_failure)
    with pytest.raises(RuntimeError,match='shutdown failed'):await worker.close()
    assert worker.status()['closed'] and not worker.status()['worker_alive']
    with pytest.raises(RuntimeError,match='shutdown failed'):await worker.close()


async def test_pending_call_queue_is_explicitly_bounded():
    worker=ResearchWorker();entered=threading.Event();release=threading.Event();called=[]
    async def active():entered.set();assert release.wait(3)
    async def queued():called.append(True)
    running=asyncio.create_task(worker.run(active));await reached(entered)
    waiting=[asyncio.create_task(worker.run(queued)) for _ in range(4)];await asyncio.sleep(.01)
    try:
        assert worker.status()['pending_calls']==worker.status()['maximum_pending_calls']==5
        with pytest.raises(RuntimeError,match='backpressure'):await worker.run(queued)
        assert not called
        for task in waiting:task.cancel()
        await asyncio.gather(*waiting,return_exceptions=True)
        release.set();await running
        assert worker.status()['pending_calls']==0 and not called
    finally:release.set();await worker.close()
