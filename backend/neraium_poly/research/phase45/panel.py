"""Predeclared probability comparisons on identical prospective decision cutoffs.

No fitting, no certification, no independent-information claim for market blends.
One immutable panel per original source model / contract / parent, bounded512.
"""
import math

from neraium_poly.contracts import Record
from neraium_poly.data import assess_book
from neraium_poly.experimental.account import PUBLIC_BOOK_SOURCES
from neraium_poly.research.phase14.relationships import digest
from neraium_poly.research.phase24.continuous import at


class ProbabilityPanel45(Record):
    forecast_id:str
    event_id:str
    market_id:str
    token_id:str
    source_forecast:dict
    executable_book:dict
    original_book_sha256:str
    probabilities:dict
    policy:str='frozen external weights1,.5,.25; same decision book; no fitting or automatic promotion'


class Panel:
    def __init__(self,store,clock,can_write):
        self.store,self.clock,self.can_write=store,clock,can_write
        self.rows={r['id']:r for r in store.latest('ProbabilityPanel45',512)}
    def register(self,forecasts,frame):
        now=at(self.clock());markets={m.token_id:m for m in frame.markets};books={b.token_id:b for b in frame.books}
        for f in sorted(forecasts.values(),key=lambda v:v['timestamp']):
            key=digest(['probability-panel45',f['model_id'],f['event_id'],f['market_id'],f['token_id']])
            if key in self.rows or len(self.rows)>=512:continue
            m=markets.get(f['token_id']);b=books.get(f['token_id'])
            if m is None or b is None or not b.bids or not b.asks:continue
            if m.status!='active' or b.source not in PUBLIC_BOOK_SOURCES or not assess_book(b,now,max_spread=.25,expected_token=m.token_id).healthy:continue
            if any(abs(v.price/m.tick_size-round(v.price/m.tick_size))>=1e-7 for v in (*b.bids,*b.asks)):continue
            if not (at(f['evidence_cutoff'])<=at(f['timestamp'])<=now<at(f['event_end_time']) and 0<=(now-at(f['timestamp'])).total_seconds()<=300):continue
            if not 0<=(now-b.timestamp).total_seconds()<=15 or not b.timestamp<=b.available_at<=now:continue
            if any(f['market'].get(k)!=getattr(m,k) for k in ('market_id','event_id','token_id','outcome','question','resolution_rules','resolution_source')) or b.market_id!=m.market_id:continue
            p=f['probability'];market=(b.bids[0].price+b.asks[0].price)/2
            probabilities={'external':p,'market':market,'neutral':.5,'blend_external50':.5*p+.5*market,'blend_external25':.25*p+.75*market}
            if any(not math.isfinite(v) or not 0<=v<=1 for v in probabilities.values()):continue
            row=ProbabilityPanel45(id=key,timestamp=now,available_at=now,source='neraium-poly/prospective-probability-panel/v45',forecast_id=f['id'],event_id=f['event_id'],market_id=m.market_id,token_id=m.token_id,source_forecast=f,executable_book=b.model_copy(update={'bids':b.bids[:8],'asks':b.asks[:8]}).model_dump(mode='json'),original_book_sha256=digest(b.model_dump(mode='json')),probabilities=probabilities)
            if not self.can_write():raise ValueError('prospective panel storage admission withheld')
            self.store.append(row);self.rows[key]=row.model_dump(mode='json')
    def report(self,labels):
        eligible=[]
        for r in self.rows.values():
            # Exact original forecast ID and contract, never nearest outcome.
            p=labels.get(r['forecast_id'])
            if not p or p.get('native_payout_verified') is not True or p.get('payout') not in (0,1):continue
            if any(p.get(k)!=r[k] for k in ('market_id','token_id','event_id')) or not at(r['timestamp'])<at(p['resolved_at']):continue
            eligible.append((r,p['payout']))
        # Equal parent-event weighting prevents many correlated thresholds from
        # dominating means. Dependency review remains separate and unqualified.
        groups={}
        for r,y in eligible:
            group=groups.setdefault(r['event_id'],[]);group.append((r,y))
        scores={}
        if groups:
            for name in next(iter(self.rows.values()))['probabilities']:
                brier=[];loss=[]
                for rows in groups.values():
                    ps=[min(1-1e-12,max(1e-12,r['probabilities'][name])) for r,_ in rows];ys=[y for _,y in rows]
                    brier.append(sum((p-y)**2 for p,y in zip(ps,ys,strict=True))/len(rows))
                    loss.append(-sum(y*math.log(p)+(1-y)*math.log(1-p) for p,y in zip(ps,ys,strict=True))/len(rows))
                scores[name]={'brier':sum(brier)/len(brier),'log_loss':sum(loss)/len(loss)}
        return {'prospective_panels':len(self.rows),'native_labeled_panels':len(eligible),'native_parent_groups':len(groups),'scores_equal_parent_weight':scores,
            'confidence_interval':None,'calibration_fit':False,'reviewed_independent_events':0,'limitation':'frozen prospective comparison, no trained calibration; insufficient reviewed independent outcomes; blends share market information, not independent corroboration'}
