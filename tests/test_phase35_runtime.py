"""Controlled research isolation fixtures, not forecasts or execution evidence."""
from datetime import UTC, datetime
from threading import get_ident
from types import SimpleNamespace

import pytest
from test_experimental_runtime import runtime


@pytest.mark.parametrize('allowed,native_failure',[(True,False),(True,True),(False,False)])
async def test_research_lanes_fail_closed_independently_and_never_touch_accounts(tmp_path,monkeypatch,allowed,native_failure):
    r,clock,_=runtime(tmp_path,datetime(2026,11,9,tzinfo=UTC))
    calls=[]
    def native():
        calls.append(('native',get_ident()))
        if native_failure:raise ValueError('controlled corrupt native proof')
    async def discover(frame):calls.append(('discover',None));return frame
    async def forecast(frame):calls.append(('forecast',None))
    r.phase35_native=SimpleNamespace(step=native)
    r.phase35_universe=SimpleNamespace(frame=discover)
    r.phase35=SimpleNamespace(step=forecast)
    before=r.account.snapshot(now=clock())
    monkeypatch.setattr(r,'_budget_ok',lambda:allowed)
    try:
        await r._phase35_research_once()
        assert [call[0] for call in calls]==(['native','discover','forecast'] if allowed else [])
        if allowed and not native_failure:
            assert r.phase35_native_error is None
            assert calls[0][1] != r._research_worker._thread.ident
        if native_failure:assert 'controlled corrupt native proof' in r.phase35_native_error
        assert r.account.snapshot(now=clock())==before
        assert not before['positions'] and before['cash']==500
    finally:await r.close()
