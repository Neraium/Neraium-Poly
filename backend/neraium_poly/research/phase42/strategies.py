"""Frozen falsifiable entry/exit hypotheses; targets are NOT calibrated probabilities."""
import math
from collections import defaultdict

from neraium_poly.research.phase14.relationships import digest
from neraium_poly.research.phase24.continuous import at

DEFINITIONS={
 'independent':{'thesis':'External source-model probability exceeds all-in asks.','exit':'take executable bids on net target, five-minute timeout or stop','horizon':300,'scored_probability':True},
 'consistency':{'thesis':'Same verified binary condition: combined two-token acquisition below unit payout. Partial-leg exposure retained.','exit':'native payout; no assumption of atomic execution','horizon':86400,'scored_probability':False},
 'momentum':{'thesis':'Past-only 30–120s midpoint drift persists; pricing target, not independent event probability.','exit':'executable target, reversal/time stop at60s','horizon':60,'scored_probability':False},
 'spread_capture':{'thesis':'A resting bid can enter only when subsequent observed asks cross it; adverse selection may dominate spread.','exit':'executable bid covers round-trip costs or120s timeout','horizon':120,'scored_probability':False},
 'event_repricing':{'thesis':'New external-source probability revision precedes market adjustment.','exit':'executable target or180s timeout','horizon':180,'scored_probability':True},
}


def propose(markets,books,forecasts,history,prior_forecasts,fees,now):
    candidates=[];rejections=[]
    def reject(strategy,token,reason):rejections.append({'strategy':strategy,'token_id':token,'reason':reason})
    for token,m in markets.items():
        b=books.get(token)
        if b is None:
            for name in DEFINITIONS:reject(name,token,'fresh_executable_book_unavailable')
            continue
        mid=(b.bids[0].price+b.asks[0].price)/2
        common={'token_id':token,'market':m.model_dump(mode='json'),'book':b.model_dump(mode='json'),'created_at':now.isoformat(),'domain':'market_research'}
        fs=sorted((f for f in forecasts.values() if f['token_id']==token and all(f['market'].get(k)==getattr(m,k) for k in ('market_id','event_id','token_id','question','resolution_rules','resolution_source','outcome')) and 0<=(now-at(f['timestamp'])).total_seconds()<=300),key=lambda f:(f['timestamp'],f['id']))
        if fs:
            f=fs[-1]
            candidates.append({**common,'strategy':'independent','key':f['id'],'target':f['probability'],'probability':f['probability'],
                'uncertainty':f.get('uncertainty',{'lower':f.get('lower_probability'),'upper':f.get('upper_probability')}),'forecast':f,'domain':f['domain'],
                'evidence_kind':'source_replayed_independent_model; original conditional assumptions retained'})
            old=prior_forecasts.get(token)
            if old and old['id']!=f['id'] and at(old['evidence_cutoff'])<at(f['evidence_cutoff']) and at(old['timestamp'])<at(f['timestamp']) and abs(f['probability']-old['probability'])>=.01:
                candidates.append({**candidates[-1],'strategy':'event_repricing','key':digest([old['id'],f['id']]),'revision_from':old})
            else:reject('event_repricing',token,'new_independent_evidence_revision_unavailable')
        else:
            reject('independent',token,'independent_source_forecast_unavailable');reject('event_repricing',token,'independent_source_forecast_unavailable')
        h=history.get(token,[])
        eligible=[r for r in h if 30<=(now-at(r['at'])).total_seconds()<=120]
        if eligible:
            old=eligible[0];drift=mid-old['mid'];last=h[-1] if h else None
            if drift>0 and last and len(h)>=4:
                increments=[h[i]['mid']-h[i-1]['mid'] for i in range(1,len(h))]
                sigma=max(.005,math.sqrt(sum(v*v for v in increments)/len(increments)))
                candidates.append({**common,'strategy':'momentum','key':digest([token,old['at'],b.timestamp.isoformat()]),'target':min(.999,mid+min(.04,drift)),
                    'probability':None,'uncertainty':{'pricing_target_variation':sigma,'calibration':'unvalidated'},'history':h,
                    'evidence_kind':'past_native_book_movement; not independent event probability'})
            else:reject('momentum',token,'positive_past_momentum_not_observed')
        else:reject('momentum',token,'causal_30second_history_unavailable')
        candidates.append({**common,'strategy':'spread_capture','key':digest([token,b.timestamp.isoformat()]),'target':b.asks[0].price,'probability':None,
            'limit':b.bids[0].price,'passive':True,'uncertainty':{'adverse_selection':'unmeasured','fill_model':'later marketable asks only; no queue-priority claim'},
            'evidence_kind':'native bid/ask; pricing target only'})
    groups=defaultdict(list)
    for token,m in markets.items():groups[m.market_id].append(token)
    for tokens in groups.values():
        if len(tokens)!=2:
            for token in tokens:reject('consistency',token,'exact_two_token_condition_unavailable')
            continue
        a,z=[markets[t] for t in tokens];ba,bz=[books.get(t) for t in tokens];fa,fz=[fees.get(t,{}) for t in tokens]
        if (ba is None or bz is None or {a.outcome.lower(),z.outcome.lower()}!={'yes','no'} or a.token_id==z.token_id
            or any(getattr(a,k)!=getattr(z,k) for k in ('event_id','question','resolution_rules','resolution_source','end_time'))
            or not fa.get('condition_id') or fa.get('condition_id')!=fz.get('condition_id') or fa.get('status')!='verified_current_protocol_curve' or fz.get('status')!='verified_current_protocol_curve'):
            reject('consistency',tokens[0],'complementary_native_identity_or_fee_evidence_unverified');continue
        total=ba.asks[0].price+bz.asks[0].price
        if total>=1:reject('consistency',tokens[0],'combined_executable_asks_not_below_unit_payout');continue
        pair=digest([a.market_id,ba.timestamp.isoformat(),bz.timestamp.isoformat()])
        # Allocation of a deterministic joint-payout hypothesis, NOT two fair probabilities.
        for m,b in ((a,ba),(z,bz)):
            candidates.append({'strategy':'consistency','key':pair+':'+m.token_id,'bundle':pair,'token_id':m.token_id,'market':m.model_dump(mode='json'),
                'book':b.model_dump(mode='json'),'created_at':now.isoformat(),'domain':'complementary_condition','target':b.asks[0].price+(1-total)/2,
                'probability':None,'uncertainty':{'legging_risk':'partial legs may fill separately','payout_assumption':'verified binary condition; native proof still required'},
                'evidence_kind':'verified shared binary condition; joint payout identity, not statistical forecast'})
    return candidates,rejections
