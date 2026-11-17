"""Map an external probability to its exact native complement, never a new sample."""
import hashlib
from pathlib import Path

from neraium_poly.research.phase14.relationships import digest
from neraium_poly.research.phase24.continuous import at


def derive(markets,books,forecasts,fees,now):
    candidates=[];rejected=[]
    fresh=[f for f in forecasts.values() if at(f['evidence_cutoff'])<=at(f['timestamp'])<=now<at(f['event_end_time']) and (now-at(f['timestamp'])).total_seconds()<=300]
    directly_supported={f['token_id'] for f in fresh};version=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    for token,m in markets.items():
        if token in directly_supported:continue
        matches=[f for f in fresh if f['market_id']==m.market_id and f['token_id']!=token and f['market']['outcome']!=m.outcome and all(f['market'].get(k)==getattr(m,k) for k in ('event_id','question','resolution_rules','resolution_source')) and at(f['market']['end_time'])==m.end_time]
        if not matches:continue
        f=max(matches,key=lambda v:(v['timestamp'],v['id']));source=fees.get(f['token_id'],{});other=fees.get(token,{})
        pair={f['token_id'],token}
        if any(p.get('status')!='verified_current_protocol_curve' or p.get('token_id')!=t or not 0<=(now-at(p['as_of'])).total_seconds()<=300 or set(p.get('condition_tokens',[]))!=pair for t,p in ((f['token_id'],source),(token,other))) or not source.get('condition_id') or source['condition_id']!=other.get('condition_id'):
            rejected.append({'strategy':'independent','token_id':token,'reason':'complement_probability_native_membership_and_fee_evidence_required'});continue
        b=books.get(token)
        if b is None:
            rejected.append({'strategy':'independent','token_id':token,'reason':'fresh_complement_executable_book_unavailable'});continue
        probability=1-f['probability'];lower=1-f.get('upper_probability',1);upper=1-f.get('lower_probability',0)
        # A new derived record, never alteration/reconstruction of the original.
        # It remains in the same event/evidence group and is not an extra model
        # vote. Native-position inventory handles its own outcome token.
        derived={'market_id':m.market_id,'event_id':m.event_id,'rules_sha256':hashlib.sha256(m.resolution_rules.encode()).hexdigest(),
            'event_end_time':f['event_end_time'],'evidence_cutoff':f['evidence_cutoff'],'domain':f['domain'],'source':'neraium-poly/native-binary-complement/v45.1',
            'research_only':True,'trading_authority':False,'id':digest(['complement45',f['id'],token]),'token_id':token,'market':m.model_dump(mode='json'),'book':b.model_dump(mode='json'),
            'timestamp':now.isoformat(),'available_at':now.isoformat(),'probability':probability,'lower_probability':lower,'upper_probability':upper,
            'market_probability':(b.bids[0].price+b.asks[0].price)/2,'market_expected_payout':(b.bids[0].price+b.asks[0].price)/2,'model_id':'native-complement-v45.1:'+f['model_id'],'model_sha256':digest([version,f['model_sha256']]),
            'derived_from':f['id'],'source_forecast_sha256':digest(f),'source_forecast_at':f['timestamp'],'independent_evidence_count':1,
            'uncertainty':{'lower_probability':lower,'upper_probability':upper,'type':'algebraic complement of original uncalibrated bounds; not a confidence interval'},'calibration_status':f.get('calibration_status','unvalidated')}
        candidates.append({'strategy':'independent','token_id':token,'market':derived['market'],'book':derived['book'],'created_at':now.isoformat(),'domain':f['domain'],
            'key':derived['id'],'target':probability,'probability':probability,'forecast':derived,'derived_complement':True,'source_forecast':f,
            'uncertainty':derived['uncertainty'],'native_condition_id':source['condition_id'],'evidence_kind':'one minus source-replayed external probability under exact same native binary condition; one underlying evidence group'})
    return candidates,rejected
