"""One bounded reference reader shared by research consumers.

No request queue, historical fallback, risk state or order access. Failed reads
invalidate the retained frame; healthy immutable observations expire after15s.
Parsing and HTTP streaming run in one owned worker, away from the event loop.
"""
import asyncio
import statistics
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Lock

import httpx

from neraium_poly.data import assess_book
from neraium_poly.experimental.feed import SharedFeedClient, loopback_url
from neraium_poly.experimental.research_worker import _drain
from neraium_poly.research.phase42.sources import read_reference


class ReferenceSampler:
    def __init__(self, url, *, clock=lambda:datetime.now(UTC), reader=None):
        self.url=loopback_url(url);self.clock=clock;self.reader=reader or read_reference
        self.lock=Lock();self.frame=None;self.attempts=0;self.failures=0;self.error=None
        self.last_attempt=None;self.latencies=deque(maxlen=128);self.fresh_books=0
        self.last_failure=None;self.failure_types={}
        self.receipt=None;self.recent_reads=deque(maxlen=12)
        self._stopping=False

    def observe(self):
        began=time.monotonic();now=self.clock()
        with self.lock:self.attempts+=1;self.last_attempt=now.isoformat()
        receipt={'read_started_at':now.isoformat()}
        try:
            frame=self.reader(self.url)
            receipt.update(frame_id=frame.id,source_timestamp=frame.timestamp.isoformat(),
                           source_available_at=frame.available_at.isoformat(),
                           producer_health=frame.producer_health.get('status'),
                           producer_error=frame.producer_health.get('last_error'))
            # Exact existing public-frame checks, including native identity,
            # byte-universe bounds and paper-only producer semantics.
            frame=SharedFeedClient.validate(frame,self.clock())
            count=sum(assess_book(b,self.clock()).healthy for b in frame.books)
            if not count:raise ValueError('no fresh executable reference books')
            with self.lock:
                receipt.update(read_completed_at=self.clock().isoformat(),status='accepted',fresh_books=count)
                self.frame=frame;self.fresh_books=count;self.error=None;self.receipt=receipt
                self.recent_reads.append(receipt)
        except (httpx.HTTPError,ValueError,OSError) as error:
            with self.lock:
                self.frame=None;self.fresh_books=0;self.failures+=1;self.error=type(error).__name__+':'+str(error)[:120]
                receipt.update(read_completed_at=self.clock().isoformat(),status='withheld',error=self.error)
                self.receipt=None;self.recent_reads.append(receipt)
                self.last_failure={'at':receipt['read_completed_at'],'reason':self.error}
                kind=type(error).__name__
                if kind not in self.failure_types and len(self.failure_types)>=8:kind='other'
                self.failure_types[kind]=self.failure_types.get(kind,0)+1
        finally:
            with self.lock:self.latencies.append(time.monotonic()-began)

    def latest_with_receipt(self):
        with self.lock:frame,receipt=self.frame,self.receipt
        if frame is None or not 0<=(self.clock()-frame.available_at).total_seconds()<=15:
            raise ValueError('fresh shared reference observation unavailable')
        return frame,receipt

    def latest(self):
        return self.latest_with_receipt()[0]

    def status(self):
        with self.lock:
            frame=self.frame;latencies=list(self.latencies)
            result={'attempts':self.attempts,'failures':self.failures,'last_attempt':self.last_attempt,'last_error':self.error,'last_failure':self.last_failure,'failure_types':dict(self.failure_types),
                    'accepted_frame':self.receipt,'recent_reads':list(self.recent_reads),'fresh_books_at_receipt':self.fresh_books,'maximum_workers':1,'queued_requests':0,
                    'median_read_seconds':statistics.median(latencies) if latencies else None,
                    'maximum_read_seconds':max(latencies) if latencies else None,
                    'available_at':frame.available_at.isoformat() if frame else None}
        age=(self.clock()-frame.available_at).total_seconds() if frame else None
        return {**result,'age_seconds':age,'status':'fresh' if age is not None and 0<=age<=15 else 'withheld','trading_authority':False}

    async def run(self, should_exit):
        pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='reference-reader')
        try:
            while not self._stopping and not should_exit():
                start=time.monotonic()
                await _drain(asyncio.get_running_loop().run_in_executor(pool,self.observe))
                for _ in range(max(0,int((5-(time.monotonic()-start))*10))):
                    if self._stopping or should_exit():return
                    await asyncio.sleep(.1)
        finally:pool.shutdown(wait=True,cancel_futures=True)

    def stop(self):self._stopping=True


def merge_supplemental(frame, markets, books, now):
    """Pure bounded merge of owner-loop snapshots; native times never rewritten.

    This is a research frame only. Financial processing continues to consume the
    original validated reference frame. Conflicting identities lose both books.
    """
    from neraium_poly.research.phase14.relationships import digest
    from neraium_poly.research.phase26.books import _identity
    if len(markets)>32 or len(books)>32:raise ValueError('supplemental snapshot exceeds existing32token cap')
    if not 0<=(now-frame.available_at).total_seconds()<=15:raise ValueError('stale base reference cannot be renewed by merge')
    merged={m.token_id:m for m in frame.markets};observed={b.token_id:b for b in frame.books};conflicts=set()
    for market in markets:
        previous=merged.get(market.token_id)
        if previous is not None and _identity(previous)!=_identity(market):conflicts.add(market.token_id)
        elif market.token_id not in conflicts:merged[market.token_id]=market
    for token in conflicts:merged.pop(token,None);observed.pop(token,None)
    accepted=0
    for book in books:
        market=merged.get(book.token_id)
        if market is None or book.token_id in conflicts or book.market_id!=market.market_id or book.available_at>now or not assess_book(book,now,max_age_seconds=15,max_spread=.05,expected_token=book.token_id).healthy:continue
        previous=observed.get(book.token_id)
        if previous is None or (book.timestamp,book.available_at)>(previous.timestamp,previous.available_at):observed[book.token_id]=book;accepted+=1
    if len(merged)>1000:raise ValueError('combined research universe exceeds existing1000token guard')
    return frame.model_copy(update={'id':digest(['native-research-merge44',frame.id,[b.id for b in books],sorted(conflicts)]),
        'timestamp':now,'available_at':now,'source':'neraium-poly/native-research-merge/v44',
        'producer_health':{**frame.producer_health,'reference_available_at':frame.available_at.isoformat(),'supplemental_books':accepted,'supplemental_conflicts':len(conflicts)},
        'markets':tuple(merged.values()),'books':tuple(observed.values())})
