"""Await budget I/O without changing frozen research economics enrollment hashes."""
import inspect
from datetime import timedelta

from neraium_poly.research.phase25.dependencies import at
from neraium_poly.research.phase29.costs import ResearchFeeCache


class AsyncBudgetResearchFeeCache(ResearchFeeCache):
    """Same bounded native-fee cache policy, with an awaited admission callback.

    The legacy module is part of immutable economic research enrollment hashes.
    Keep its byte identity and old observations while adapting only scheduling.
    AuditedFeeAdapter independently checks current capacity before durable writes.
    """
    async def refresh(self, frame, *, forecast_tokens):
        now=at(self.clock());tokens=set(forecast_tokens);markets={m.token_id:m for m in frame.markets}
        eligible=[]
        for b in frame.books:
            m=markets.get(b.token_id)
            if (b.token_id in tokens and m is not None and m.market_id==b.market_id
                and m.status=='active' and m.end_time is not None and m.end_time>now
                and 0<=(now-b.timestamp).total_seconds()<=15 and 0<=(now-b.available_at).total_seconds()<=15
                and b.bids and b.asks):eligible.append(b.token_id)
        keep=set(sorted(set(eligible))[:32])
        self.observations={t:v for t,v in self.observations.items() if t in keep}
        self.attempts={t:v for t,v in self.attempts.items() if t in keep};self.errors={t:v for t,v in self.errors.items() if t in keep}
        for token in sorted(keep,key=lambda t:self.attempts.get(t,now-timedelta(days=1)))[:2]:
            allowed=self.can_write()
            if inspect.isawaitable(allowed):allowed=await allowed
            if not allowed:return
            prior=self.attempts.get(token)
            if prior is not None and now-prior<timedelta(seconds=60):continue
            cached=self.observations.get(token)
            if cached and now-at(cached['observed_at'])<timedelta(seconds=240):continue
            self.attempts[token]=now
            try:
                raw=await self.adapter.observed_fee(token)
                if raw is not None:self.observations[token]=raw;self.errors.pop(token,None)
                else:self.errors[token]='native_curve_unavailable'
            except Exception as error:  # noqa: BLE001 - unknown native fees never become zero
                self.errors[token]=type(error).__name__

    def status(self):
        return {**super().status(),'budget_scheduling':'awaited admission; current audited write guards retained'}
