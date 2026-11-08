"""Controlled delayed I/O/transport fixtures; no genuine market or performance claim."""
import asyncio
import threading
import time
from datetime import timedelta

import pytest
from neraium_poly.data import EventStore
from neraium_poly.research.phase26 import coordination
from test_phase24_integration import NOW, inputs
from test_phase26_integration import Watcher, supported


async def pulse_until(task):
    gaps=[];last=time.monotonic()
    while not task.done():
        await asyncio.sleep(.005);now=time.monotonic();gaps.append(now-last);last=now
    return await task,gaps


async def test_native_callback_budget_and_append_stay_off_event_loop(tmp_path,monkeypatch):
    store=EventStore(tmp_path/'controlled.sqlite');_m,b,*_=inputs();main=threading.get_ident();threads=[]
    c=coordination.Inputs(store,clock=lambda:NOW,can_write=lambda:True,watcher=Watcher())
    append=store.append
    def budget():threads.append(threading.get_ident());time.sleep(.08);return True
    def slow(record):threads.append(threading.get_ident());time.sleep(.08);return append(record)
    c.can_write=budget;monkeypatch.setattr(store,'append',slow)
    try:
        _,gaps=await pulse_until(asyncio.create_task(c.on_book(b)))
        assert len(gaps)>20 and max(gaps)<.07 and main not in threads
        row=store.latest('ResearchInputObservation',1)[0]
        assert row['book']==b.model_dump(mode='json') and c.counts['archived_samples']==1
    finally:await c.close();store.close()


async def test_prepare_selection_and_preflight_offloop_keep_transport_on_original_loop(tmp_path,monkeypatch):
    store=EventStore(tmp_path/'controlled.sqlite');_m,b,_e,_f,frame=inputs();main=threading.get_ident();thread_calls=[]
    class MainLoopWatcher(Watcher):
        async def update(self,markets):assert threading.get_ident()==main;await super().update(markets)
        async def wait_fresh(self,**kwargs):assert threading.get_ident()==main;return await super().wait_fresh(**kwargs)
        def snapshot(self):assert threading.get_ident()==main;return super().snapshot()
        async def close(self):assert threading.get_ident()==main;await super().close()
    watcher=MainLoopWatcher((b,));monkeypatch.setattr(coordination,'modules',supported)
    selector=coordination.select_supplemental_markets
    def slow_select(*args,**kwargs):
        thread_calls.append(threading.get_ident());time.sleep(.08);return selector(*args,**kwargs)
    monkeypatch.setattr(coordination,'select_supplemental_markets',slow_select)
    c=coordination.Inputs(store,clock=lambda:NOW,can_write=lambda:True,watcher=watcher);append=store.append
    def slow_append(record):thread_calls.append(threading.get_ident());time.sleep(.08);return append(record)
    monkeypatch.setattr(store,'append',slow_append)
    try:
        merged,gaps=await pulse_until(asyncio.create_task(c.prepare(frame,base_tokens=set(),wait=True)))
        assert max(gaps)<.07 and len(gaps)>20 and main not in thread_calls
        assert merged.books==(b,) and merged.books[0].timestamp==b.timestamp
        assert c.selection['weather_policy_sha256']
    finally:await c.close();store.close()
    assert watcher.closed


async def reached(event):
    deadline=time.monotonic()+3
    while not event.is_set():
        assert time.monotonic()<deadline
        await asyncio.sleep(.005)


async def test_cancel_and_close_drain_one_active_write_then_reject_more_work(tmp_path,monkeypatch):
    store=EventStore(tmp_path/'controlled.sqlite');_m,b,_e,_f,frame=inputs();watcher=Watcher();entered=threading.Event();release=threading.Event()
    c=coordination.Inputs(store,clock=lambda:NOW,can_write=lambda:True,watcher=watcher);append=store.append
    def blocked(record):entered.set();assert release.wait(3);return append(record)
    monkeypatch.setattr(store,'append',blocked)
    callback=asyncio.create_task(c.on_book(b));await reached(entered);callback.cancel();await asyncio.sleep(.01);callback.cancel()
    closing=asyncio.create_task(c.close());await asyncio.sleep(.01);closing.cancel();await asyncio.sleep(.01)
    assert not callback.done() and not closing.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):await callback
    with pytest.raises(asyncio.CancelledError):await closing
    assert watcher.closed and store.count(kind='ResearchInputObservation')==1
    await c.close();await c.on_book(b)
    assert store.count(kind='ResearchInputObservation')==1
    with pytest.raises(ValueError,match='coordinator closed'):await c.prepare(frame,base_tokens=set())
    store.close()


async def test_budget_delay_does_not_make_source_quote_fresh(tmp_path):
    store=EventStore(tmp_path/'controlled.sqlite');_m,b,*_=inputs();clock=[NOW]
    c=coordination.Inputs(store,clock=lambda:clock[0],can_write=lambda:True,watcher=Watcher())
    def slow_budget():clock[0]+=timedelta(seconds=20);return True
    c.can_write=slow_budget
    try:
        await c.on_book(b)
        assert store.count(kind='ResearchInputObservation')==0 and c.counts['callback_quality_rejections']==1
    finally:await c.close();store.close()


async def test_failed_transport_close_still_drains_active_write(tmp_path,monkeypatch):
    store=EventStore(tmp_path/'controlled.sqlite');_m,b,*_=inputs();entered=threading.Event();release=threading.Event()
    class FailedWatcher(Watcher):
        async def close(self):self.closed=True;raise OSError('CONTROLLED transport close failure')
    c=coordination.Inputs(store,clock=lambda:NOW,can_write=lambda:True,watcher=FailedWatcher());append=store.append
    def blocked(record):entered.set();assert release.wait(3);return append(record)
    monkeypatch.setattr(store,'append',blocked)
    callback=asyncio.create_task(c.on_book(b));await reached(entered)
    closing=asyncio.create_task(c.close());await asyncio.sleep(.02);assert not closing.done()
    release.set();await callback
    with pytest.raises(OSError,match='transport close failure'):await closing
    await c.on_book(b);assert store.count(kind='ResearchInputObservation')==1
    store.close()
