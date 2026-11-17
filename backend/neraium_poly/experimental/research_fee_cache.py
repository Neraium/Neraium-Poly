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
    async def refresh(self, frame, *, forecast_tokens,priority_tokens=()):
        now=at(self.clock());tokens=set(forecast_tokens);held=set(priority_tokens);markets={m.token_id:m for m in frame.markets}
        # Forecasts, complementary partners and deep quoted markets compete in
        # one bounded cache. Rotate unselected names; no subscription expansion.
        by_token={b.token_id:b for b in frame.books}
        all_fresh=[]
        for token,m in markets.items():
            b=by_token.get(token)
            if b is not None and m.status=='active' and m.end_time is not None and m.end_time>now and b.market_id==m.market_id and b.bids and b.asks and 0<=(now-b.timestamp).total_seconds()<=15 and 0<=(now-b.available_at).total_seconds()<=15:all_fresh.append(token)
        all_fresh=sorted(set(all_fresh)|held|{t for t in tokens if t in markets and markets[t].status=='active' and markets[t].end_time and markets[t].end_time>now})
        ranked=sorted(all_fresh,key=lambda t:(t not in held,t not in tokens,(-sum(v.size*v.price for v in by_token[t].bids[:3])+sum(v.size*v.price for v in by_token[t].asks[:3])*.001) if t in by_token else 0,t))
        focus=[]
        for token in ranked:
            if token in focus:continue
            group=[t for t in ranked if t in markets and markets[t].market_id==markets[token].market_id] if token in markets else [token]
            for t in group[:2]:
                if t not in focus and len(focus)<16:focus.append(t)
            if len(focus)>=16:break
        remaining=[t for t in ranked if t not in focus]
        shift=(int(now.timestamp())//240*16)%len(remaining) if remaining else 0
        keep=set(focus+(remaining[shift:]+remaining[:shift])[:16])
        self.observations={t:v for t,v in self.observations.items() if t in keep}
        self.attempts={t:v for t,v in self.attempts.items() if t in keep};self.errors={t:v for t,v in self.errors.items() if t in keep}
        due=[t for t in keep if (self.attempts.get(t) is None or now-self.attempts[t]>=timedelta(seconds=60)) and (t not in self.observations or now-at(self.observations[t]['observed_at'])>=timedelta(seconds=240))]
        for token in sorted(due,key=lambda t:(self.attempts.get(t,now-timedelta(days=1)),t))[:2]:
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

    def proofs(self,*,as_of):
        import json
        proofs=super().proofs(as_of=as_of)
        for proof in proofs.values():
            if proof.get('status')!='verified_current_protocol_curve':continue
            original=self.store.get(proof['raw_response_ids'][0])
            if original is None:continue
            parent=json.loads(original[1])['payload']
            proof['condition_tokens']=[str(parent['primary_token_id']),str(parent['secondary_token_id'])]
        return proofs

    def status(self):
        return {**super().status(),'budget_scheduling':'due entries selected before2-token batch; cache32, native calls unchanged; forecast/depth/rotating coverage'}
