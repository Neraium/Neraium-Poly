"""Controlled archive pacing; no genuine price/fill or profitability evidence."""
import asyncio
import time
from datetime import datetime, timedelta

from neraium_poly.experimental.contracts import SharedMarketFrame
from neraium_poly.experimental.runtime import ExperimentalRuntime
from test_experimental_account import book
from test_experimental_runtime import runtime


async def test_archive_batches_yield_before_strategy_admission(tmp_path,monkeypatch):
    moment=datetime.fromisoformat('2026-11-06T12:00:00+00:00');r,clock,feed=runtime(tmp_path,moment)
    r.config=r.config.model_copy(update={'max_tokens':64});r.engine.max_tokens=64
    async def read():
        ms=tuple(feed.market.model_copy(update={'id':f'M{i}','market_id':f'M{i}','event_id':f'E{i}','token_id':f'T{i}'}) for i in range(64))
        bs=tuple(book(clock()).model_copy(update={'id':f'B{i}','market_id':f'M{i}','token_id':f'T{i}'}) for i in range(64))
        return SharedMarketFrame(timestamp=clock(),available_at=clock(),source='CONTROLLED-public-shaped',producer_health={'status':'ok'},markets=ms,books=bs)
    monkeypatch.setattr(feed,'read',read);append=r.events.append
    def slow(record):time.sleep(.003);return append(record)
    monkeypatch.setattr(r.events,'append',slow)
    done=[False];gaps=[]
    async def ticker():
        last=time.monotonic()
        while not done[0]:
            await asyncio.sleep(.005);now=time.monotonic();gaps.append(now-last);last=now
    pulse=asyncio.create_task(ticker());await asyncio.sleep(0)
    try:
        await r.cycle();done[0]=True;await pulse
        assert max(gaps)<.5
        assert r.account.snapshot(now=clock())['cash']==500
    finally:done[0]=True;await pulse;await r.close()


async def test_execution_clock_follows_archival_delay(tmp_path,monkeypatch):
    moment=datetime.fromisoformat('2026-11-06T12:00:00+00:00');r,clock,_feed=runtime(tmp_path,moment);append=r.events.append;first=[True]
    def delayed(record):
        if type(record).__name__=='MarketSnapshot' and first[0]:first[0]=False;clock.now+=timedelta(seconds=20)
        return append(record)
    monkeypatch.setattr(r.events,'append',delayed)
    try:
        await r.cycle()
        assert datetime.fromisoformat(r.last_cycle['timestamp'])==clock()
        assert r.last_cycle['rejection_counts'].get('stale_book',0)>0
        assert r.account.snapshot(now=clock())['cash']==500
    finally:await r.close()


async def test_shutdown_waits_for_cycle_not_its_callers_unrelated_work():
    r=ExperimentalRuntime.__new__(ExperimentalRuntime);r.stopping=False;entered=asyncio.Event();release=asyncio.Event();later=asyncio.Event()
    async def work():entered.set();await release.wait()
    r._cycle_impl=work
    async def caller():await r.cycle();await later.wait()
    task=asyncio.create_task(caller());await entered.wait();r.stopping=True
    close=asyncio.create_task(r._finish_cycle());await asyncio.sleep(.01)
    close.cancel();await asyncio.sleep(.01);assert not close.done()
    release.set();assert await close is True
    assert not task.done()
    later.set();await task


async def test_cycle_calls_are_serialized_and_stop_prevents_new_work():
    r=ExperimentalRuntime.__new__(ExperimentalRuntime);r.stopping=False;active=peak=calls=0
    async def work():
        nonlocal active,peak,calls
        active+=1;peak=max(peak,active);calls+=1;await asyncio.sleep(.01);active-=1
    r._cycle_impl=work
    await asyncio.gather(r.cycle(),r.cycle());assert peak==1 and calls==2
    r.stopping=True;await r.cycle();assert calls==2


async def test_stop_during_archive_batch_prevents_financial_admission(tmp_path,monkeypatch):
    moment=datetime.fromisoformat('2026-11-06T12:00:00+00:00');r,clock,feed=runtime(tmp_path,moment)
    r.config=r.config.model_copy(update={'max_tokens':8});r.engine.max_tokens=8
    async def read():
        ms=tuple(feed.market.model_copy(update={'id':f'M{i}','market_id':f'M{i}','event_id':f'E{i}','token_id':f'T{i}'}) for i in range(8))
        bs=tuple(book(clock()).model_copy(update={'id':f'B{i}','market_id':f'M{i}','token_id':f'T{i}'}) for i in range(8))
        return SharedMarketFrame(timestamp=clock(),available_at=clock(),source='CONTROLLED-public-shaped',producer_health={'status':'ok'},markets=ms,books=bs)
    monkeypatch.setattr(feed,'read',read)
    append=r.events.append
    def stopping_append(record):
        result=append(record)
        if type(record).__name__=='MarketSnapshot':r.stopping=True
        return result
    monkeypatch.setattr(r.events,'append',stopping_append)
    def forbidden(*args,**kwargs):raise AssertionError('financial admission after shutdown')
    monkeypatch.setattr(r.engine,'evaluate_frame',forbidden)
    try:
        await r.cycle()
        assert r.account.snapshot(now=clock())['cash']==500
    finally:await r.close()
