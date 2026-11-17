"""Outcome-blind information selection for existing, unchanged forecast models."""
import hashlib
from pathlib import Path

from neraium_poly.data import assess_book
from neraium_poly.experimental.account import PUBLIC_BOOK_SOURCES
from neraium_poly.research.phase14.relationships import digest
from neraium_poly.research.phase23.continuous import ChallengerResearch
from neraium_poly.research.phase23.models import map_challenger_contract

VERSION=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def select(frame,now,*,crypto=False,models=None):
    books={b.token_id:b for b in frame.books};groups={}
    for m in frame.markets:
        b=books.get(m.token_id)
        if m.status!='active' or not m.end_time or m.end_time<=now or b is None or b.market_id!=m.market_id or b.source not in PUBLIC_BOOK_SOURCES or not assess_book(b,now,max_age_seconds=15,max_spread=.05,expected_token=m.token_id).healthy:continue
        mid=(b.bids[0].price+b.asks[0].price)/2;hours=(m.end_time-now).total_seconds()/3600;depth=min(sum(v.price*v.size for v in b.bids[:3]),sum(v.price*v.size for v in b.asks[:3]))
        if crypto:
            if m.outcome!='Yes':continue
            contract=map_challenger_contract(m,now=now)
            if not contract.compatible or contract.review_required:continue
            # Different assets on the same UTC window are one selection block.
            key=('crypto',contract.parameters['period_start_utc'],contract.parameters['period_end_utc'])
            eligible=[key]
        else:eligible=[(name,m.event_id) for name,model in models.items() if model.supports(m,cutoff=now).get('supported')]
        for key in eligible:
            rank=(abs(mid-.5),hours,-depth,m.market_id,m.token_id)
            if key not in groups or rank<groups[key][0]:groups[key]=(rank,m)
    selected=[];per_adapter={}
    for key,(_rank,m) in sorted(groups.items(),key=lambda item:(item[1][0][1]>72,item[1][0],item[0])):
        if per_adapter.get(key[0],0)>=2:continue
        selected.append(m.market_id);per_adapter[key[0]]=per_adapter.get(key[0],0)+1
    ids=set(selected[:16]);markets=tuple(m for m in frame.markets if m.market_id in ids);tokens={m.token_id for m in markets}
    return frame.model_copy(update={'id':digest(['information46',VERSION,frame.id,sorted(tokens)]),'markets':markets,'books':tuple(b for b in frame.books if b.token_id in tokens),
        'producer_health':{**frame.producer_health,'research_selection':'phase46 outcome-blind entropy/date diversity','selection_policy_sha256':VERSION,'selected_market_ids':len(ids)}})


class InformationChallenger(ChallengerResearch):
    async def step(self,frame):return await super().step(select(frame,self.clock(),crypto=True))
