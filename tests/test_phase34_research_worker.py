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


async def test_close_during_startup_cannot_publish_a_new_job(monkeypatch):
    worker=ResearchWorker();entered=asyncio.Event();release=asyncio.Event();start=worker._start;called=[]
    async def slow_start():await start();entered.set();await release.wait()
    monkeypatch.setattr(worker,'_start',slow_start)
    async def forbidden():called.append(True)
    running=asyncio.create_task(worker.run(forbidden));await entered.wait()
    close=asyncio.create_task(worker.close());await asyncio.sleep(.01)
    release.set()
    with pytest.raises(RuntimeError,match='closed'):await running
    await close
    assert not called and worker.status()['submitted']==0 and not worker.status()['worker_alive']


async def test_transient_owner_loop_closing_reaps_idle_non_daemon_worker():
    worker=ResearchWorker()
    def transient_owner():
        async def model():return 'CONTROLLED'
        async def once():assert await worker.run(model)=='CONTROLLED'
        asyncio.run(once())
    await asyncio.to_thread(transient_owner)
    deadline=time.monotonic()+3
    while worker.status()['worker_alive']:
        assert time.monotonic()<deadline,'orphan research loop did not terminate'
        await asyncio.sleep(.01)
    assert worker.status()['closed'] and not worker._thread.daemon
    await worker.close()


async def test_owner_disappearing_during_native_job_drains_write_before_exit():
    worker=ResearchWorker();entered=threading.Event();release=threading.Event();completed=[];owner_closed=threading.Event()
    async def model():
        entered.set();await asyncio.to_thread(release.wait)
        # Stand-in for a source transaction that must finish, never real evidence.
        completed.append(True)
    def disappearing_owner():
        loop=asyncio.new_event_loop();asyncio.set_event_loop(loop)
        task=loop.create_task(worker.run(model))
        while not entered.is_set():loop.run_until_complete(asyncio.sleep(.005))
        loop.stop();loop.close();owner_closed.set()
        # Keep the abandoned caller Task referenced until native draining ends;
        # suppress only its expected destroyed-pending warning in this fixture.
        task._log_destroy_pending=False
    owner=asyncio.create_task(asyncio.to_thread(disappearing_owner));await reached(owner_closed)
    try:
        await asyncio.sleep(.08)
        assert worker.status()['worker_alive'] and not completed
        release.set();await owner
        deadline=time.monotonic()+3
        while worker.status()['worker_alive']:
            assert time.monotonic()<deadline
            await asyncio.sleep(.01)
        assert completed==[True] and worker.status()['closed']
    finally:release.set()


async def test_cancellation_interrupts_async_source_once_and_drains_finally_promptly():
    worker=ResearchWorker();entered=threading.Event();cleaning=threading.Event();finished=[]
    async def slow_network():
        entered.set()
        try:await asyncio.sleep(60)
        finally:
            cleaning.set();await asyncio.sleep(.06)
            finished.append(asyncio.current_task().cancelling())
    running=asyncio.create_task(worker.run(slow_network));await reached(entered)
    start=time.monotonic();running.cancel();await reached(cleaning)
    running.cancel();await asyncio.sleep(.01);running.cancel()
    assert not running.done()
    with pytest.raises(asyncio.CancelledError):await running
    assert time.monotonic()-start<1 and finished==[1]
    assert worker.status()['active_jobs']==0
    await worker.close()


async def test_cancelled_source_drains_shielded_native_io_before_releasing_slot():
    worker=ResearchWorker();entered=threading.Event();release=threading.Event();written=[]
    def durable_work():entered.set();assert release.wait(3);written.append(True)
    async def source():
        native=asyncio.create_task(asyncio.to_thread(durable_work))
        try:await asyncio.shield(native)
        except asyncio.CancelledError:
            await asyncio.gather(native,return_exceptions=True)
            raise
    running=asyncio.create_task(worker.run(source));await reached(entered);running.cancel();await asyncio.sleep(.01);running.cancel()
    assert not running.done() and not written
    release.set()
    with pytest.raises(asyncio.CancelledError):await running
    assert written==[True]
    await worker.close()
