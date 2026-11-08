"""Bounded supplemental public books; freshness always uses exchange time."""

import asyncio
import inspect
from collections import Counter
from datetime import UTC, datetime

from neraium_poly.contracts import MarketSnapshot
from neraium_poly.data import assess_book
from neraium_poly.data.connectivity import CoverageFeed
from neraium_poly.data.operational import OperationalPolymarketAdapter
from neraium_poly.experimental.account import PUBLIC_BOOK_SOURCES
from neraium_poly.research.phase14.relationships import digest


def _identity(m):
    raw=m.model_dump(mode='json')
    return digest({k:raw[k] for k in ('exchange','market_id','event_id','token_id','outcome','question',
        'resolution_rules','resolution_source','end_time','tick_size','min_order_size')})


class SupplementalBooks:
    """One public stream for at most32 tokens; never an order submission client.

    Call update after metadata refresh and snapshot before research evaluation.
    Cached invalidations remain authoritative: no second stale callback cache.
    Counts describe observed transport/qualification events, not independent data.
    """
    def __init__(self,*,clock=None,on_book=None,feed=None,max_tokens=32):
        if type(max_tokens) is not int or not 1<=max_tokens<=32:raise ValueError('supplemental32_token_budget_required')
        self.clock=clock or (lambda:datetime.now(UTC));self.on_book=on_book;self.max_tokens=max_tokens
        self.feed=feed or CoverageFeed(OperationalPolymarketAdapter(clock=self.clock),max_tokens=max_tokens,
            concurrency=2,rate=2,queue_size=64,max_reconnects=8,max_gap_seconds=30)
        self._markets={};self._signature=None;self._task=None;self._closed=False;self._lock=asyncio.Lock()
        self._quarantined={};self.counts=Counter();self.last_error=None;self.last_qualified_at=None
        self._changed=asyncio.Event()

    def _reason(self,book,market,now):
        if market is None:return ('unmapped_token',)
        if market.status!='active' or not market.end_time or market.end_time<=now:return ('market_not_upcoming_active',)
        if book.market_id!=market.market_id or book.exchange!=market.exchange:return ('book_market_identity_mismatch',)
        if book.source not in PUBLIC_BOOK_SOURCES:return ('nonpublic_book_source',)
        return assess_book(book,now,max_age_seconds=15,max_spread=.05,expected_token=market.token_id).reasons

    async def _accept(self,book):
        now=self.clock();reasons=self._reason(book,self._markets.get(book.token_id),now)
        self.counts['callbacks_observed']+=1
        if reasons:
            self.counts.update('callback_'+r for r in reasons);return
        self.counts['callbacks_qualified']+=1;self.last_qualified_at=now;self._changed.set()
        if self.on_book is not None:
            result=self.on_book(book)
            if inspect.isawaitable(result):await result

    async def update(self,markets):
        if self._closed:raise ValueError('supplemental_watcher_closed')
        values=list(markets)
        if len(values)>self.max_tokens:raise ValueError('supplemental32_token_budget_required')
        now=self.clock();selected={}
        for value in values:
            m=MarketSnapshot.model_validate(value.model_dump() if hasattr(value,'model_dump') else value)
            if m.exchange!='polymarket' or m.source!='https://gamma-api.polymarket.com' or not m.timestamp<=m.available_at<=now:
                raise ValueError('authentic_causal_supplemental_metadata_required')
            if m.token_id in selected and _identity(selected[m.token_id])!=_identity(m):
                async with self._lock:
                    await self.feed.stop_stream();self._task=None;self._signature=None;self._markets={}
                    self.last_error='ambiguous_supplemental_token_identity';self.counts['metadata_identity_conflicts']+=1
                raise ValueError(self.last_error)
            if m.status=='active' and m.end_time and m.end_time>now:selected[m.token_id]=m
        async with self._lock:
            if self._closed:raise ValueError('supplemental_watcher_closed')
            changed=[token for token,m in selected.items() if token in self._markets and _identity(m)!=_identity(self._markets[token])]
            changed += [token for token,m in selected.items() if token in self._quarantined and _identity(m)!=self._quarantined[token]]
            if changed:
                for token in changed:
                    if token not in self._quarantined and len(self._quarantined)<self.max_tokens:
                        self._quarantined[token]=_identity(self._markets[token])
                self.counts['metadata_identity_conflicts']+=len(set(changed))
                await self.feed.stop_stream();self._task=None;self._signature=None;self._markets={}
                self.last_error='supplemental_token_identity_conflict';raise ValueError(self.last_error)
            signature=digest(sorted((token,_identity(m)) for token,m in selected.items()))
            running=self._task is not None and not self._task.done()
            self._markets=selected
            if signature==self._signature and running:
                self.feed.set_markets(tuple(selected.values()));return False
            await self.feed.stop_stream();self._task=None
            self._signature=signature;self.last_error=None
            if selected:
                self._task=self.feed.start_stream(tuple(selected.values()),self._accept)
                self._task.add_done_callback(self._finished)
                self.counts['stream_starts']+=1
            self._changed.clear();return True

    def _finished(self,task):
        if task.cancelled():return
        error=task.exception()
        if task is not self._task:return
        if error is not None:
            self.last_error=type(error).__name__+':'+str(error)[:120]
            self.counts['stream_failures']+=1

    def snapshot(self):
        now=self.clock();result=[];reasons=Counter()
        if self._closed:return ()
        for token,m in self._markets.items():
            book=self.feed.latest.get(token)
            if book is None:reasons['missing_book']+=1;continue
            found=self._reason(book,m,now)
            if found:reasons.update(found)
            else:result.append(book)
        self._last_rejections=dict(reasons)
        return tuple(result)

    async def wait_fresh(self,*,timeout=1):
        if not 0<=timeout<=30:raise ValueError('bounded_fresh_book_wait_required')
        if self._closed:return ()
        result=self.snapshot()
        if result or timeout==0:return result
        self._changed.clear()
        try:await asyncio.wait_for(self._changed.wait(),timeout=timeout)
        except TimeoutError:return ()
        return self.snapshot()

    def status(self):
        books=self.snapshot();metrics=self.feed.metrics()
        return {'status':'closed' if self._closed else 'degraded' if self.last_error else 'public_research_only',
            'subscribed_tokens':len(self._markets),'qualified_books':len(books),'max_tokens':self.max_tokens,
            'native_max_age_seconds':15,'max_spread':.05,'counts':dict(self.counts),
            'book_rejections':getattr(self,'_last_rejections',{}),'transport':metrics,
            'last_qualified_at':self.last_qualified_at.isoformat() if self.last_qualified_at else None,
            'last_error':self.last_error,'quarantined_tokens':len(self._quarantined),
            'trading_authority':False,'counter_scope':'transport callbacks and current snapshots; never independent observations'}

    async def close(self):
        async with self._lock:
            if self._closed:return
            self._closed=True;self._markets={};self._changed.set()
            await self.feed.close();self._task=None
