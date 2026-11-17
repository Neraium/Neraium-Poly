"""Frozen exploratory hypotheses; no broker access, account resets or promotion."""
import hashlib
from pathlib import Path
from typing import ClassVar

from neraium_poly.research.phase14.relationships import digest
from neraium_poly.research.phase24.continuous import at
from neraium_poly.research.phase42.engine import StrategyCycle, StrategyEngine
from neraium_poly.research.phase42.strategies import propose
from neraium_poly.research.phase44.cohort import opportunities as bid_opportunities
from neraium_poly.research.phase45 import native_positions
from neraium_poly.research.phase45.complements import derive
from neraium_poly.research.phase45.diagnostics import breakdown
from neraium_poly.research.phase45.economics import evaluate

DEFINITIONS={
 'independent':{'thesis':'External source-replayed probability versus executable cost, settlement-aligned inside separate20USD principal budget; no forced bid liquidation.','exit':'verified native payout only; principal at risk bounded at entry','horizon':86400,'scored_probability':True},
 'consistency':{'thesis':'Exact shared binary condition complementary payout identity; independently verified token membership, no guaranteed atomic fill.','exit':'native payout only','horizon':86400,'scored_probability':False},
 'event_repricing':{'thesis':'New external evidence probability revision exceeds intervening market repricing and round-trip friction.','exit':'executable convergence,180s timeout or risk stop','horizon':180,'scored_probability':True},
 'momentum':{'thesis':'Observed executable BID persistence with positive depth imbalance, narrow spread and round-trip costs. Not a fair-outcome probability.','exit':'executable target,60s timeout or risk stop','horizon':60,'scored_probability':False}}


def opportunities(markets,books,forecasts,history,prior,fees,now):
    candidates,rejected=propose(markets,books,forecasts,history,prior,fees,now)
    candidates=[c for c in candidates if c['strategy'] in ('independent','event_repricing')]
    rejected=[r for r in rejected if r['strategy'] in ('independent','event_repricing')]
    out=[]
    for c in candidates:
        if c['strategy']=='event_repricing':
            old=c['revision_from'];f=c['forecast']
            if old.get('market_probability') is None or f.get('market_probability') is None:
                rejected.append({'strategy':'event_repricing','token_id':c['token_id'],'reason':'prior_contemporaneous_market_probability_missing'});continue
            residual=(f['probability']-old['probability'])-(f['market_probability']-old['market_probability'])
            if residual<=0:
                rejected.append({'strategy':'event_repricing','token_id':c['token_id'],'reason':'external_revision_already_reflected_in_market'});continue
            c={**c,'target':min(c['target'],c['book']['bids'][0]['price']+residual),'residual_external_revision':residual,'probability':None,'evidence_kind':'external revision minus original contemporaneous market revision; pricing hypothesis, not independent fair probability'}
        out.append(c)
    bids,ignored=bid_opportunities(markets,books,{},history,{},fees,now)
    for r in ignored:
        if r['strategy']!='momentum':continue
        token=r['token_id'];b=books.get(token)
        if b is None:r={**r,'reason':'fresh_executable_book_unavailable'}
        elif fees.get(token,{}).get('status')!='verified_current_protocol_curve':r={**r,'reason':'native_fee_unavailable'}
        elif len([v for v in history.get(token,[]) if 'bid' in v and 30<=(now-at(v['at'])).total_seconds()<=120])<3:r={**r,'reason':'three_causal_bid_history_observations_required'}
        rejected.append(r)
    for c in bids:
        if c['strategy']!='momentum':continue
        b=books[c['token_id']];bid=sum(v.size for v in b.bids[:3]);ask=sum(v.size for v in b.asks[:3])
        if b.asks[0].price-b.bids[0].price>.03 or bid<=ask:
            rejected.append({'strategy':'momentum','token_id':c['token_id'],'reason':'tight_spread_and_positive_depth_imbalance_required'});continue
        out.append(c)
    # Reuse the established same-condition comparison only after authoritative
    # fee evidence proves the exact token set. Names alone never prove a pair.
    groups={}
    for t,m in markets.items():groups.setdefault(m.market_id,[]).append(t)
    for tokens in groups.values():
        if len(tokens)!=2:
            for t in tokens:rejected.append({'strategy':'consistency','token_id':t,'reason':'exact_two_token_condition_unavailable'})
            continue
        if any(books.get(t) is None for t in tokens):reason='fresh_executable_book_unavailable'
        elif any(fees.get(t,{}).get('status')!='verified_current_protocol_curve' or not 0<=(now-at(fees[t]['as_of'])).total_seconds()<=300 for t in tokens):reason='native_fee_unavailable'
        elif any(set(fees[t].get('condition_tokens',[]))!=set(tokens) for t in tokens):reason='authoritative_condition_token_membership_missing'
        else:reason=None
        if reason:
            rejected.append({'strategy':'consistency','token_id':tokens[0],'reason':reason});continue
        a,z=[markets[t] for t in tokens]
        if any(getattr(a,k)!=getattr(z,k) for k in ('event_id','question','resolution_rules','resolution_source','end_time')) or fees[tokens[0]].get('condition_id')!=fees[tokens[1]].get('condition_id'):
            rejected.append({'strategy':'consistency','token_id':tokens[0],'reason':'contract_identity_or_condition_mismatch'});continue
        total=sum(books[t].asks[0].price for t in tokens)
        if total>=1:
            rejected.append({'strategy':'consistency','token_id':tokens[0],'reason':'combined_executable_asks_not_below_unit_payout'});continue
        pair=digest([a.market_id,*[books[t].id for t in tokens]])
        units={t:books[t].asks[0].price+fees[t]['rate']*books[t].asks[0].price*(1-books[t].asks[0].price)+.002 for t in tokens}
        matched_quantity=min(*[books[t].asks[0].size*.1 for t in tokens],5/sum(units.values()))
        for t in tokens:
            m,b=markets[t],books[t]
            out.append({'strategy':'consistency','key':pair+':'+t,'bundle':pair,'token_id':t,'market':m.model_dump(mode='json'),
                'book':b.model_dump(mode='json'),'created_at':now.isoformat(),'domain':'complementary_condition','target':b.asks[0].price+(1-total)/2,
                'paired_leg_budget':matched_quantity*units[t],'matched_pair_quantity':matched_quantity,'probability':None,'uncertainty':{'legging_risk':'partial unequal legs remain directional; not atomic arbitrage','payout_assumption':'exact native binary condition; final payout proof still required'},
                'evidence_kind':'authoritative exact two-token native condition; labels not used to infer equivalence'})
    complements,missing=derive(markets,books,forecasts,fees,now)
    mapped={c['token_id'] for c in complements}
    rejected=[r for r in rejected if not(r['strategy']=='independent' and r['token_id'] in mapped and r['reason']=='independent_source_forecast_unavailable')]
    return [{**c,'decision_fee':fees.get(c['token_id'],{})} for c in out+complements],rejected+missing


class StrategyCycle45(StrategyCycle):
    pass


class Explorer(StrategyEngine):
    native_hold_research=True
    record_type=StrategyCycle45
    identity_prefix='strategy45'
    source_name='neraium-poly/exploratory-competition/v45'
    definitions=DEFINITIONS
    profile_configs:ClassVar[dict]={
        'aggressive':{'size':5.,'edge':0.,'spread':.15,'haircut':0.,'unknown_fee':.10},
        'balanced':{'size':5.,'edge':0.,'spread':.08,'haircut':.25,'unknown_fee':None},
        'conservative':{'size':5.,'edge':.01,'spread':.05,'haircut':1.,'unknown_fee':None}}
    def proposer(self,markets,books,forecasts,history,prior,fees,now):
        candidates,rejected=opportunities(markets,books,forecasts,history,prior,fees,now)
        self.economic_candidates=evaluate(candidates,self.profile_configs,now)
        return candidates,rejected
    def _commit(self,state,events,observations):
        native_positions.capture(state,events)
        if 'frame_id' in observations:
            observations={**observations,'economic_candidates':getattr(self,'economic_candidates',[])}
        return super()._commit(state,events,observations)
    def extra_policy(self):
        return {**super().extra_policy(),'cohort':'phase45-exploration-v1','source_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'report_sources_sha256':{n:hashlib.sha256(Path(__file__).with_name(n).read_bytes()).hexdigest() for n in ('economics.py','diagnostics.py','panel.py','native_positions.py','complements.py')},
                'native_hold_research':True,'principal_budget_usd':20,'market_budget_usd':5,'event_and_domain_budget_usd':10,
                'uncertainty':'unvalidated external models; aggressive fees sensitivity0.10 if unavailable; no qualified profit claim',
                'checkpoint':'first100 independent native event groups; no calibration fitting or automatic promotion'}
    def budget(self,s,c,size):
        return max(0.,min(super().budget(s,c,size),c.get('paired_leg_budget',size),20-self.exposure(s),5-self.exposure(s,'market_id',c['market']['market_id']),10-self.exposure(s,'event_id',c['market']['event_id']),10-self.exposure(s,'domain',c['domain'])))
    def settle(self,proofs):
        original=super().settle(proofs)
        return native_positions.settle(self,proofs) or original
    def report(self):
        r=super().report()
        r['native_pricing_contracts']={'registered':len(self.state.get('pricing_contracts45',{})),'verified':len(self.state.get('pricing_labels45',{})),'probability_forecasts':False}
        r['strategy_changes']={'independent':'Phase45-only native hold; maximum principal20USD total,5USD per native market,10USD per event/domain; prior portfolios and exits untouched','other':'bid-exit and native-condition strategies retain declared rules; no certification or account authority'}
        r['rejection_breakdown']={name:breakdown(p['rejections']) for name,p in r['profiles'].items()}
        r['economic_candidates']=self.last.get('observations',{}).get('economic_candidates',[]) if self.last else []
        r['evidence_stages']=['exploratory hypothesis','native fee curve verified; other execution costs modeled','modeled later-book fill','native verified settlement with modeled execution','independent validation still required']
        return r
