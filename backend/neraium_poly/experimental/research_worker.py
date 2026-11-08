"""Bounded research-only coroutine isolation with one persistent worker loop.

Frozen research models keep their loop-bound locks/clients and synchronous
archive checks. No financial account or strategy authority is provided here.
"""
import asyncio
import inspect
import threading


async def _drain(future):
    """Cancellation cannot abandon a running archive operation or release a slot."""
    interrupted=False
    while not future.done():
        try:
            await asyncio.shield(future)
        except asyncio.CancelledError:
            interrupted=True
        except Exception:  # noqa: BLE001 - propagate the finished future below
            break
    if interrupted:
        if not future.cancelled():future.exception()
        raise asyncio.CancelledError
    return future.result()


class ResearchWorker:
    """One active submitted job, no executor/task backlog, stable research loop.

    Submit callable factories, not coroutines constructed on a foreign loop.
    Caller cancellation drains the active job; queued callers never publish work.
    Close model-owned clients through run() before close() stops this loop.
    """
    def __init__(self):
        self._gate=asyncio.Lock()
        self._ready=threading.Event()
        self._thread=None
        self._loop=None
        self._startup_error=None
        self._shutdown_error=None
        self._close_task=None
        self._closing=False
        self._closed=False
        self._active=False
        self._pending=0
        self._max_pending=5
        self._submitted=0
        self._completed=0

    def _thread_main(self):
        try:
            self._loop=asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
        except BaseException as error:  # noqa: BLE001 - report startup failure to the owning caller
            self._startup_error=error
            self._ready.set()
            return
        self._ready.set()
        try:
            self._loop.run_forever()
        finally:
            try:
                pending=asyncio.all_tasks(self._loop)
                for task in pending:task.cancel()
                if pending:self._loop.run_until_complete(asyncio.gather(*pending,return_exceptions=True))
                self._loop.run_until_complete(self._loop.shutdown_asyncgens())
                self._loop.run_until_complete(self._loop.shutdown_default_executor())
            except BaseException as error:  # noqa: BLE001 - relay cleanup failure after thread termination
                self._shutdown_error=error
            finally:self._loop.close()

    async def _start(self):
        if self._thread is None:
            self._thread=threading.Thread(target=self._thread_main,name='research-async-io',daemon=False)
            self._thread.start()
        if not self._ready.is_set():
            await _drain(asyncio.create_task(asyncio.to_thread(self._ready.wait)))
        if self._startup_error is not None:raise RuntimeError('research worker loop startup failed') from self._startup_error

    @staticmethod
    async def _invoke(factory,args,kwargs):
        value=factory(*args,**kwargs)
        if not inspect.isawaitable(value):raise TypeError('research coroutine factory required')
        return await value

    async def run(self,factory,*args,**kwargs):
        if self._thread is not None and threading.get_ident()==self._thread.ident:
            raise RuntimeError('research worker cannot submit to itself')
        if not callable(factory):raise TypeError('research callable factory required')
        if self._pending >= self._max_pending:
            raise RuntimeError('research worker pending-call backpressure')
        self._pending+=1
        try:
            async with self._gate:
                if self._closing or self._closed:raise RuntimeError('research worker closed')
                await self._start()
                concurrent=asyncio.run_coroutine_threadsafe(self._invoke(factory,args,kwargs),self._loop)
                self._active=True;self._submitted+=1
                try:
                    return await _drain(asyncio.wrap_future(concurrent))
                finally:
                    self._active=False;self._completed+=1
        finally:
            self._pending-=1

    async def close(self):
        if self._thread is not None and threading.get_ident()==self._thread.ident:
            raise RuntimeError('research worker cannot close itself')
        self._closing=True
        if self._close_task is None:self._close_task=asyncio.create_task(self._finish())
        return await _drain(self._close_task)

    async def _finish(self):
        async with self._gate:
            if self._thread is not None and self._thread.ident is not None:
                # Startup is complete before releasing run()'s gate, even on cancel.
                if self._loop is not None and not self._loop.is_closed():
                    self._loop.call_soon_threadsafe(self._loop.stop)
                await asyncio.to_thread(self._thread.join)
            self._closed=True
            if self._shutdown_error is not None:raise RuntimeError('research worker shutdown failed') from self._shutdown_error

    def status(self):
        return {'active_jobs':int(self._active),'maximum_submitted_jobs':1,'pending_calls':self._pending,
            'maximum_pending_calls':self._max_pending,'submitted':self._submitted,
            'completed':self._completed,'closing':self._closing,'closed':self._closed,
            'worker_alive':self._thread.is_alive() if self._thread else False,
            'research_only':True,'trading_authority':False,'certification_authority':False}
