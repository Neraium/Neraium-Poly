"""Controlled slow-I/O/cancellation tests; no authentic performance or fill claims."""
import asyncio
import threading
import time
from datetime import UTC, datetime

import pytest
from test_experimental_account import book, fee, signal
from test_experimental_runtime import runtime


async def reached(event):
    deadline=time.monotonic()+3
    while not event.is_set():
        assert time.monotonic()<deadline, 'controlled worker did not start'
        await asyncio.sleep(.005)


async def test_archive_and_risk_reconcile_do_not_block_loop(tmp_path,monkeypatch):
    r,clock,_=runtime(tmp_path,datetime(2026,11,6,12,tzinfo=UTC))
    append=r.events.append;advance=r.account.advance;threads=[]
    def slow_append(record):
        threads.append(threading.get_ident());time.sleep(.08);return append(record)
    def slow_advance(*args,**kwargs):
        threads.append(threading.get_ident());time.sleep(.12);return advance(*args,**kwargs)
    monkeypatch.setattr(r.events,'append',slow_append);monkeypatch.setattr(r.account,'advance',slow_advance)
    task=asyncio.create_task(r.cycle());gaps=[];last=time.monotonic()
    try:
        while not task.done():
            await asyncio.sleep(.005);now=time.monotonic();gaps.append(now-last);last=now
        await task
        assert len(gaps)>20 and max(gaps)<.07
        assert len(set(threads))==1 and threads[0]!=threading.get_ident()
        assert r.account.snapshot(now=clock())['cash']==500
    finally:await r.close()


async def test_shutdown_during_worker_advance_prevents_new_admission(tmp_path,monkeypatch):
    r,clock,_=runtime(tmp_path,datetime(2026,11,6,12,tzinfo=UTC));entered=threading.Event();release=threading.Event();advance=r.account.advance
    b=book(clock());s=signal(clock(),b)
    monkeypatch.setattr(r.engine,'evaluate_frame',lambda *args:[s])
    def blocked(*args,**kwargs):entered.set();assert release.wait(3);return advance(*args,**kwargs)
    monkeypatch.setattr(r.account,'advance',blocked)
    def forbidden(*args,**kwargs):raise AssertionError('new admission after shutdown request')
    monkeypatch.setattr(r.account,'submit',forbidden)
    cycle=asyncio.create_task(r.cycle());await reached(entered)
    close=asyncio.create_task(r.close());await asyncio.sleep(.02);assert r.stopping and not close.done()
    close.cancel();close.cancel();await asyncio.sleep(.02);assert not close.done()
    release.set();await cycle
    with pytest.raises(asyncio.CancelledError):await close
    await r.close()  # Idempotent recovery of the completed close task.
    assert r._io_closed


async def test_worker_reads_current_risk_stop_after_archival_wait(tmp_path,monkeypatch):
    r,clock,_=runtime(tmp_path,datetime(2026,11,6,12,tzinfo=UTC));entered=threading.Event();release=threading.Event();append=r.events.append
    b=book(clock());s=signal(clock(),b);r.fees[b.token_id]=fee(clock());seen=[]
    monkeypatch.setattr(r.engine,'evaluate_frame',lambda *args:[s])
    def blocked(record):
        if type(record).__name__=='MarketSnapshot':entered.set();assert release.wait(3)
        return append(record)
    monkeypatch.setattr(r.events,'append',blocked);submit=r.account.submit
    def inspect(*args,**kwargs):
        assert r.account.snapshot(now=clock())['kill_switch'];result=submit(*args,**kwargs);seen.append(result);return result
    monkeypatch.setattr(r.account,'submit',inspect)
    cycle=asyncio.create_task(r.cycle());await reached(entered)
    try:
        r.account.stop(now=clock(),reason='CONTROLLED integrity stop');release.set();await cycle
        assert seen and seen[0]['status']!='submitted'
        assert r.account.snapshot(now=clock())['cash']==500
    finally:release.set();await r.close()


async def test_cancelled_cycle_drains_worker_and_withholds_admission(tmp_path,monkeypatch):
    r,_,_=runtime(tmp_path,datetime(2026,11,6,12,tzinfo=UTC));entered=threading.Event();release=threading.Event();append=r.events.append
    def blocked(record):
        if type(record).__name__=='MarketSnapshot':entered.set();assert release.wait(3)
        return append(record)
    monkeypatch.setattr(r.events,'append',blocked)
    def forbidden(*args,**kwargs):raise AssertionError('admission after caller cancellation')
    monkeypatch.setattr(r.engine,'evaluate_frame',forbidden)
    cycle=asyncio.create_task(r.cycle());await reached(entered);cycle.cancel();await asyncio.sleep(.01);cycle.cancel();await asyncio.sleep(.01)
    assert not cycle.done() and r._cycle_abort.is_set()
    release.set()
    with pytest.raises(asyncio.CancelledError):await cycle
    await r.close()


async def test_sync_lane_has_one_worker_and_releases_after_failure(tmp_path):
    r,_,_=runtime(tmp_path,datetime(2026,11,6,12,tzinfo=UTC));active=peak=0;threads=set()
    def work():
        nonlocal active,peak
        active+=1;peak=max(peak,active);threads.add(threading.get_ident());time.sleep(.01);active-=1
    try:
        await asyncio.gather(*(r._sync_io(work) for _ in range(12)))
        assert peak==1 and len(threads)==1
        def fail():raise ValueError('CONTROLLED')
        with pytest.raises(ValueError,match='CONTROLLED'):await r._sync_io(fail)
        await r._sync_io(work)
    finally:await r.close()
    with pytest.raises(RuntimeError,match='lane closed'):await r._sync_io(work)


async def test_operations_read_is_current_without_writer_lock_or_side_effects(tmp_path,monkeypatch):
    from neraium_poly.experimental.operations_ledger import operations_ledger
    r,clock,_=runtime(tmp_path,datetime(2026,11,6,12,tzinfo=UTC));entered=threading.Event();release=threading.Event()
    def held_audit():
        with r.account.risk._lock:
            entered.set();assert release.wait(3)
    worker=asyncio.create_task(asyncio.to_thread(held_audit));await reached(entered)
    def forbidden(*args,**kwargs):raise AssertionError('operational read may not expire/admit/reconcile')
    monkeypatch.setattr(r.account.risk,'snapshot',forbidden)
    try:
        start=time.monotonic();capital,counts=operations_ledger(r.account.directory,clock=clock)
        assert time.monotonic()-start<.2
        assert capital['cash']==500 and counts['capital_observation']['admission_authority'] is False
        assert not capital['kill_switch']
        # A fresh connection observes a stop committed after the first read.
        r.account.risk.db.execute('UPDATE account SET kill=1 WHERE id=1')
        capital,_=operations_ledger(r.account.directory,clock=clock);assert capital['kill_switch']
    finally:
        release.set();await worker
        monkeypatch.undo();await r.close()


async def test_readonly_monitor_failure_does_not_create_or_substitute_a_balance(tmp_path):
    import sqlite3

    from neraium_poly.experimental.operations_ledger import operations_ledger
    clock=lambda:datetime(2026,11,6,12,tzinfo=UTC)
    with pytest.raises(ValueError,match='existing regular'):operations_ledger(tmp_path,clock=clock)
    assert not (tmp_path/'risk.sqlite').exists()
    # SQLite lock handling is bounded; a broken/inaccessible ledger is unavailable.
    path=tmp_path/'risk.sqlite';path.write_bytes(b'CONTROLLED corrupt fixture')
    with pytest.raises(sqlite3.DatabaseError):operations_ledger(tmp_path,clock=clock)


async def test_monitor_sqlite_lock_wait_is_bounded_and_never_returns_cached_cash(tmp_path):
    import sqlite3

    from neraium_poly.experimental.operations_ledger import operations_ledger
    r,clock,_=runtime(tmp_path/'original',datetime(2026,11,6,12,tzinfo=UTC))
    copied=tmp_path/'CONTROLLED-copy';copied.mkdir()
    locked=sqlite3.connect(copied/'risk.sqlite',isolation_level=None)
    r.account.risk.db.backup(locked)
    locked.execute('PRAGMA journal_mode=DELETE');locked.execute('BEGIN EXCLUSIVE')
    try:
        start=time.monotonic()
        with pytest.raises(sqlite3.OperationalError,match='locked'):
            operations_ledger(copied,clock=clock)
        assert .15<time.monotonic()-start<1
    finally:
        locked.execute('ROLLBACK');locked.close();await r.close()
