"""Controlled worker/budget boundaries, never operational trading evidence."""
import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from neraium_poly.experimental.research_fee_cache import AsyncBudgetResearchFeeCache
from test_experimental_account import book, market
from test_experimental_runtime import runtime


@pytest.mark.parametrize('allowed',[True,False])
async def test_async_research_budget_is_awaited_and_denial_makes_no_requests(allowed):
    now=datetime(2026,11,8,tzinfo=UTC);calls=[];checks=[]
    async def budget():
        await asyncio.sleep(.001);checks.append(True);return allowed
    async def observed(token):calls.append(token);
    m=market(now);b=book(now)
    cache=AsyncBudgetResearchFeeCache(None,SimpleNamespace(observed_fee=observed),clock=lambda:now,can_write=budget)
    await cache.refresh(SimpleNamespace(markets=(m,),books=(b,)),forecast_tokens=[m.token_id])
    assert checks==[True]
    assert calls==([m.token_id] if allowed else [])


async def test_stop_during_signal_archival_cannot_start_pending_fill_advance(tmp_path,monkeypatch):
    now=datetime(2026,11,8,tzinfo=UTC);r,clock,_=runtime(tmp_path,now)
    original=r.engine.evaluate_frame
    def stop_after_evaluation(frame,at):
        result=original(frame,at);r.stopping=True;return result
    monkeypatch.setattr(r.engine,'evaluate_frame',stop_after_evaluation)
    def forbidden(*args,**kwargs):raise AssertionError('new pending fill work after stop')
    monkeypatch.setattr(r.account,'advance',forbidden)
    try:
        await r.cycle()
        assert r.account.snapshot(now=clock())['cash']==500
    finally:await r.close()


async def test_late_research_checkpoint_survives_close_and_restart(tmp_path):
    import threading
    now=datetime(2026,11,8,tzinfo=UTC);r,_,_=runtime(tmp_path,now)
    entered=threading.Event();release=threading.Event()
    async def research():
        entered.set()
        while not release.is_set():await asyncio.sleep(.001)
        r.totals['cycles']=17
    job=asyncio.create_task(r._research_io(research))
    while not entered.is_set():await asyncio.sleep(.001)
    closing=asyncio.create_task(r.close());await asyncio.sleep(.02)
    assert not closing.done()
    release.set();await job;await closing
    recovered,_,_=runtime(tmp_path,now)
    try:assert recovered.totals['cycles']==17
    finally:await recovered.close()
