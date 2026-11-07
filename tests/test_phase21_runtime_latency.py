"""Controlled blocking maintenance; no fixture trading or actual source claims."""
import asyncio
from datetime import UTC, datetime
from threading import Event
from types import SimpleNamespace

from neraium_poly.ops.live import LivePaperRuntime


async def test_archive_maintenance_keeps_loop_responsive_and_precedes_admission():
    started, release = Event(), Event()
    sequence = []
    def maintain():
        sequence.append('maintenance-start')
        started.set()
        assert release.wait(2), 'CONTROLLED maintenance was not released'
        sequence.append('maintenance-complete')
    def budget():
        sequence.append('budget')
        return False
    runtime = SimpleNamespace(clock=lambda: datetime.now(UTC),
        config=SimpleNamespace(archive_management_enabled=True), events=SimpleNamespace(maintain=maintain),
        _budget_ok=budget, _archive_status=lambda: {'last_error': 'CONTROLLED denied'},
        coverage=None, archive_fault=None, stopping=False)
    task = asyncio.create_task(LivePaperRuntime.cycle(runtime))
    try:
        assert await asyncio.to_thread(started.wait, 2)
        assert not task.done() and 'budget' not in sequence
        sequence.append('event-loop-responsive')
    finally:
        release.set()
        await task
    assert sequence == ['maintenance-start', 'event-loop-responsive', 'maintenance-complete', 'budget']


async def test_cancelled_cycle_waits_for_worker_before_owner_can_close():
    started, release, finished = Event(), Event(), Event()
    def maintain():
        started.set()
        assert release.wait(2)
        finished.set()
    runtime = SimpleNamespace(clock=lambda: datetime.now(UTC), config=SimpleNamespace(archive_management_enabled=True),
        events=SimpleNamespace(maintain=maintain), coverage=None, stopping=False, archive_fault=None,
        _budget_ok=lambda: False, _archive_status=lambda: {'last_error': 'CONTROLLED denied'})
    task = asyncio.create_task(LivePaperRuntime.cycle(runtime))
    assert await asyncio.to_thread(started.wait, 2)
    task.cancel()
    await asyncio.sleep(.01)
    assert not task.done() and not finished.is_set()
    release.set()
    try:
        await task
    except asyncio.CancelledError:
        pass
    assert finished.is_set() and runtime._archive_maintenance_task is None
