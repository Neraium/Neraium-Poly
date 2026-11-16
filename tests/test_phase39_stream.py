"""Frozen burst/storage fixtures; no live forecasts, fills, or performance claims."""
import asyncio
import json
import threading
from datetime import timedelta

import pytest
from neraium_poly.data import EventStore
from neraium_poly.research.phase26.coordination import Inputs
from neraium_poly.research.phase29.outcomes import maturity_report, projected_maturity_report
from test_connectivity import Socket, full
from test_phase24_integration import NOW, inputs
from test_phase26_integration import Watcher
from test_phase29_outcomes import entry


async def until(predicate, seconds=3):
    async with asyncio.timeout(seconds):
        while not predicate():await asyncio.sleep(.002)


async def test_slow_archive_does_not_block_native_queue_or_lose_authoritative_updates(tmp_path,monkeypatch):
    store=EventStore(tmp_path/'fixture.sqlite');m,*_=inputs();c=Inputs(store,clock=lambda:NOW,can_write=lambda:True)
    feed=c.watcher.feed;feed.queue_size=4;feed.queue_put_timeout=.02;feed.max_reconnects=0
    events=[full(NOW,token=m.token_id,bids=[{'price':'.39','size':str(100+i)}]) for i in range(100)]
    feed.connector=lambda *a,**kw:Socket([json.dumps(events)])
    append=store.append;entered=threading.Event();release=threading.Event()
    def blocked(record):
        if type(record).__name__=='ResearchInputObservation':entered.set();assert release.wait(3)
        return append(record)
    monkeypatch.setattr(store,'append',blocked)
    try:
        await c.watcher.update([m]);await until(lambda:entered.is_set())
        await until(lambda:c.watcher.counts['callbacks_observed']==100)
        assert feed.metrics()['queue_overflows']==feed.metrics()['reconnects']==0
        assert feed.latest[m.token_id].bids[0].size==199
        assert c._sample_task and not c._sample_task.done()
        assert c.counts['transport_notifications']==100
        # One task and one wake bit, no accumulated book/task queue.
        assert not hasattr(c,'_sample_queue')
        closing=asyncio.create_task(c.close());await asyncio.sleep(.03)
        assert not closing.done()  # SQLite writer cannot be abandoned.
        release.set();await closing
        assert store.count(kind='ResearchInputObservation')==1
        assert store.connection.execute('PRAGMA quick_check').fetchone()==('ok',)
    finally:release.set();await c.close();store.close()


async def test_archive_error_withholds_qualification_and_is_visible(tmp_path,monkeypatch):
    store=EventStore(tmp_path/'fixture.sqlite');_m,b,*_=inputs();watcher=Watcher((b,));c=Inputs(store,clock=lambda:NOW,can_write=lambda:True,watcher=watcher)
    append=store.append
    def full_disk(record):
        if type(record).__name__=='ResearchInputObservation':raise OSError('CONTROLLED disk full')
        return append(record)
    monkeypatch.setattr(store,'append',full_disk)
    try:
        c.notify_book(b);await until(lambda:c.status()['sampling_error'])
        assert store.count(kind='ResearchInputObservation')==0
        with pytest.raises(ValueError,match='sampling_unavailable'):c.qualify({})
        with pytest.raises(ValueError,match='sampling_unavailable'):await c.prepare({},base_tokens=set())
    finally:await c.close();store.close()


async def test_invalidated_cache_is_not_resurrected_by_coalesced_wake(tmp_path):
    store=EventStore(tmp_path/'fixture.sqlite');_m,b,*_=inputs();watcher=Watcher(());c=Inputs(store,clock=lambda:NOW,can_write=lambda:True,watcher=watcher)
    try:
        for _ in range(500):c.notify_book(b)
        await asyncio.sleep(.03)
        assert store.count(kind='ResearchInputObservation')==0
        assert c.counts['coalesced_notifications']==499
        task=c._sample_task;await c.close();c.notify_book(b)
        assert task.done() and c._sample_task is task
    finally:await c.close();store.close()


async def test_slow_budget_preserves_source_age_and_sampling_caps(tmp_path):
    store=EventStore(tmp_path/'fixture.sqlite');_m,b,*_=inputs();clock=[NOW];c=Inputs(store,clock=lambda:clock[0],can_write=lambda:True,watcher=Watcher((b,)))
    def delayed_budget():clock[0]+=timedelta(seconds=20);return True
    c.can_write=delayed_budget
    try:
        c.notify_book(b);await until(lambda:c.counts['callback_quality_rejections']==1)
        assert store.count(kind='ResearchInputObservation')==0
    finally:await c.close();store.close()


def test_projection_outcomes_do_not_consume_forecast_inventory_budget():
    one=entry()
    rows=[{'type':'outcome'}]*15249+[{'type':'declaration'}]*20+[one]
    report=projected_maturity_report(iter(rows),as_of=NOW+timedelta(days=1))
    assert report==maturity_report([one],as_of=NOW+timedelta(days=1))
    assert report['independently_verified_outcomes'] is None
    with pytest.raises(ValueError,match='bounded_outcome_readiness'):
        projected_maturity_report([one]*10001,as_of=NOW+timedelta(days=1))
