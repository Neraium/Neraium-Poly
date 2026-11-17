"""Durable, small trader-facing decision cards; original evidence remains authority."""
from neraium_poly.contracts import Record
from neraium_poly.research.phase14.relationships import digest
from neraium_poly.research.phase16.checkpoints import unpack_checkpoint


class ShadowDecisionCard(Record):
    cycle_id:str
    payload:dict


def publish(store,engine,report,now,*,cohort='legacy'):
    row=engine.last
    if row:
        batch=row['events'][0];decisions=unpack_checkpoint(batch['payload'])['decisions']
        if digest(decisions)!=batch['sha256']:raise ValueError('decision batch integrity failure')
        for i,event in enumerate(decisions):
            if event['type'] not in ('shadow_intent','modeled_fill','modeled_exit','native_settlement'):continue
            c=event.get('candidate',{});m=c.get('market',{})
            card={'cohort':cohort,'type':event['type'],'profile':event['profile'],'strategy':c.get('strategy',event.get('strategy')),'order_id':event.get('order_id'),
                'market_id':m.get('market_id',event.get('book',{}).get('market_id')),'question':m.get('question'),'token_id':c.get('token_id'),
                'quantity':event.get('quantity'),'capital':event.get('capital',event.get('cost')),'estimated_net_value':event.get('estimated_net_value'),
                'net_modeled_pnl':event.get('pnl'),'model_probability':c.get('probability'),'pricing_target':c.get('target'),
                'uncertainty':c.get('uncertainty'),'forecast_at':c.get('forecast',{}).get('timestamp'),'entry_limit':c.get('limit',c.get('book',{}).get('asks',[{}])[0].get('price')),'fee_verified':event.get('fee_verified'),'evidence_kind':c.get('evidence_kind'),
                'native_settled':event.get('native_settled',False),'actual_fill':False,'original_cycle_id':row['id'],'original_cycle_sha256':digest(row)}
            identity=digest(['shadow-card42',row['id'],i])
            if store.get(identity) is None:store.append(ShadowDecisionCard(id=identity,timestamp=now,available_at=now,source='neraium-poly/trader-desk/v42',cycle_id=row['id'],payload=card))
    positions=[]
    pending=[]
    for profile,s in engine.state['profiles'].items():
        for p in s['positions'].values():positions.append({'cohort':cohort,'profile':profile,'strategy':p['strategy'],'question':p['market']['question'],'market_id':p['market_id'],'token_id':p['token_id'],
            'quantity':p['quantity'],'capital':p['cost'],'marked_net_pnl':p.get('marked_pnl') if report.get('profiles',{}).get(profile,{}).get('unrealized_net_pnl') is not None else None,'entry_at':p['entered_at'],'forecast_id':p.get('forecast_id')})
        for o in s['orders'].values():pending.append({'cohort':cohort,'profile':profile,'strategy':o['strategy'],'question':o['market']['question'],'limit':o['limit'],'unfilled_quantity':o['remaining'],'reserved_capital':o['reserved'],'expires':o['expires']})
    return {**report,'recent_decisions':[{'at':r['available_at'],**r['payload']} for r in store.latest('ShadowDecisionCard',20)],'positions':positions,'unfilled_orders':pending}
