"""Bound existing paper-service worker pools within its unchanged task limit."""
import asyncio
from concurrent.futures import ThreadPoolExecutor

from anyio.to_thread import current_default_thread_limiter

ASYNCIO_WORKERS=8
ANYIO_TOKENS=4
_STATE='_neraium_execution_pool_state_v34'


async def configure_execution_pools():
    """Install once before any default-executor work on the current event loop.

    Never replace an unknown live pool. Loop shutdown owns executor cleanup;
    AnyIO's limiter is scoped to this loop. No process/service limit is changed.
    """
    loop=asyncio.get_running_loop()
    limiter=current_default_thread_limiter()
    state=getattr(loop,_STATE,None)
    current=getattr(loop,'_default_executor',None)
    if state is not None:
        if current is not state['executor'] or limiter is not state['limiter']:
            raise RuntimeError('paper execution pool ownership changed')
        if limiter.total_tokens!=ANYIO_TOKENS:
            raise RuntimeError('paper AnyIO worker cap changed')
        return dict(state['report'])
    if current is not None:
        raise RuntimeError('configure paper pools before existing default-executor work')
    previous_tokens=limiter.total_tokens
    executor=ThreadPoolExecutor(max_workers=ASYNCIO_WORKERS,thread_name_prefix='research-io')
    try:
        loop.set_default_executor(executor)
        limiter.total_tokens=ANYIO_TOKENS
    except BaseException:
        # Nothing was submitted and there is no await in this installation.
        if getattr(loop,'_default_executor',None) is executor:loop._default_executor=None
        executor.shutdown(wait=True,cancel_futures=False)
        raise
    report={'asyncio_default_workers':ASYNCIO_WORKERS,'asyncio_thread_prefix':'research-io',
        'anyio_worker_tokens':ANYIO_TOKENS,'previous_anyio_worker_tokens':previous_tokens,
        'scope':'current event loop default executor and AnyIO thread limiter; service task/CPU/memory limits unchanged',
        'research_only':True,'trading_authority':False,'certification_authority':False}
    setattr(loop,_STATE,{'executor':executor,'limiter':limiter,'report':report})
    return dict(report)
