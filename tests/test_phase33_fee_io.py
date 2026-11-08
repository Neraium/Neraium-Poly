"""Controlled journal latency/concurrency, never authentic market evidence."""
import asyncio
import threading
import time

import httpx
import pytest
from neraium_poly.data import EventStore
from neraium_poly.data.connectivity import ConcurrentPublicAdapter
from neraium_poly.experimental.fees import AuditedFeeAdapter


@pytest.fixture
def adapter(tmp_path,monkeypatch):
    store=EventStore(tmp_path/'controlled.sqlite')
    async def response(*a,**k):return {'CONTROLLED':True}
    monkeypatch.setattr(ConcurrentPublicAdapter,'_get',response)
    client=httpx.AsyncClient();a=AuditedFeeAdapter(store,lambda:True,client=client)
    yield a,store
    store.close()


async def test_slow_journal_cannot_block_event_loop(adapter,monkeypatch):
    a,store=adapter;entered=threading.Event();release=threading.Event();get=store.get
    def delayed(k):entered.set();release.wait(2);return get(k)
    monkeypatch.setattr(store,'get',delayed)
    task=asyncio.create_task(a._get('https://clob.polymarket.com','/controlled'))
    try:
        assert await asyncio.to_thread(entered.wait,1)
        start=time.monotonic();await asyncio.sleep(.02)
        assert time.monotonic()-start<.5 and not task.done()
    finally:release.set();await task;await a.client.aclose()
    assert store.count(kind='PublicFeeReceipt')==1


async def test_concurrent_identical_content_keeps_one_response_and_each_receipt(adapter,monkeypatch):
    a,store=adapter;get=store.get
    def delayed(k):time.sleep(.02);return get(k)
    monkeypatch.setattr(store,'get',delayed)
    try:
        await asyncio.gather(*(a._get('https://clob.polymarket.com','/controlled') for _ in range(6)))
        assert store.count(kind='PublicFeeResponse')==1 and store.count(kind='PublicFeeReceipt')==6
    finally:await a.client.aclose()


async def test_repeated_cancellation_drains_receipt_before_returning(adapter,monkeypatch):
    a,store=adapter;append=store.append;entered=threading.Event();release=threading.Event()
    def delayed(record):
        if type(record).__name__=='PublicFeeReceipt':entered.set();release.wait(2)
        return append(record)
    monkeypatch.setattr(store,'append',delayed)
    task=asyncio.create_task(a._get('https://clob.polymarket.com','/controlled'))
    try:
        assert await asyncio.to_thread(entered.wait,1)
        task.cancel();await asyncio.sleep(.01);task.cancel();await asyncio.sleep(.01)
        assert not task.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):await task
        assert store.count(kind='PublicFeeReceipt')==1
    finally:
        release.set()
        if not task.done():await asyncio.gather(task,return_exceptions=True)
        await a.client.aclose()


async def test_audit_worker_count_is_bounded(adapter):
    a,_store=adapter;active=peak=0;lock=threading.Lock()
    def job():
        nonlocal active,peak
        with lock:active+=1;peak=max(peak,active)
        time.sleep(.02)
        with lock:active-=1
    try:
        await asyncio.gather(*(a._audit(job) for _ in range(8)))
        assert peak==2
    finally:await a.client.aclose()


async def test_storage_denial_prevents_any_fee_evidence_publication(adapter):
    a,store=adapter;a.can_write=lambda:False
    try:
        with pytest.raises(ValueError,match='budget'):await a._get('https://clob.polymarket.com','/controlled')
        assert store.count(kind='PublicFeeResponse')==store.count(kind='PublicFeeReceipt')==0
    finally:await a.client.aclose()


async def test_deduplicated_response_availability_never_follows_its_receipt(adapter,monkeypatch):
    from datetime import datetime
    a,store=adapter;record=a._record_response;first=[True]
    def delay_first(*args):
        if first[0]:first[0]=False;time.sleep(.05)
        return record(*args)
    monkeypatch.setattr(a,'_record_response',delay_first)
    try:
        await asyncio.gather(a._get('https://clob.polymarket.com','/controlled'),a._get('https://clob.polymarket.com','/controlled'))
        raw=store.replay(kind='PublicFeeResponse')[0]['record'];receipts=store.replay(kind='PublicFeeReceipt')
        assert len(receipts)==2
        assert all(datetime.fromisoformat(raw['available_at'])<=datetime.fromisoformat(x['record']['available_at']) for x in receipts)
    finally:await a.client.aclose()


async def test_close_drains_active_worker_before_archive_can_close(adapter,monkeypatch):
    a,store=adapter;append=store.append;entered=threading.Event();release=threading.Event()
    def delayed(record):
        if type(record).__name__=='PublicFeeReceipt':entered.set();release.wait(2)
        return append(record)
    monkeypatch.setattr(store,'append',delayed)
    request=asyncio.create_task(a._get('https://clob.polymarket.com','/controlled'))
    closer=None
    try:
        assert await asyncio.to_thread(entered.wait,1)
        closer=asyncio.create_task(a.close());await asyncio.sleep(.01)
        assert not closer.done()
        with pytest.raises(RuntimeError,match='closing'):await a._get('https://clob.polymarket.com','/other')
        release.set();await closer;await request
        assert store.count(kind='PublicFeeReceipt')==1
    finally:
        release.set();await asyncio.gather(request,*([closer] if closer else []),return_exceptions=True);await a.client.aclose()
