"""Native settlement inventory for pricing hypotheses without fake forecasts."""
import copy
import hashlib

from neraium_poly.research.phase14.relationships import digest
from neraium_poly.research.phase24.continuous import at
from neraium_poly.research.phase43 import economics


def capture(state,events):
    contracts=state.setdefault('pricing_contracts45',{})
    for e in events:
        if e.get('type')!='shadow_intent' or (e['candidate'].get('forecast') and not e['candidate'].get('derived_complement')):continue
        c=e['candidate'];m=c['market'];rules=hashlib.sha256(m['resolution_rules'].encode()).hexdigest()
        key=digest(['pricing-contract45',m['market_id'],m['event_id'],m['token_id'],rules])
        if key in contracts:continue
        if len(contracts)>=256:raise ValueError('bounded pricing contract settlement inventory exhausted')
        contracts[key]={'id':key,'market_id':m['market_id'],'event_id':m['event_id'],'token_id':m['token_id'],'rules_sha256':rules,'market':m,
            'timestamp':c['created_at'],'evidence_cutoff':c['created_at'],'event_end_time':m['end_time'],
            'source_forecast_id':c.get('source_forecast',{}).get('id'),'kind':'native_contract_identity_only_not_probability_forecast','probability':None,'research_only':True,'trading_authority':False}


def due(engine,now):
    rows=engine.state.get('pricing_contracts45',{});labels=engine.state.get('pricing_labels45',{})
    return {k:{'forecast':c,'study_id':engine.last['id'],'study_sha256':digest(engine.last)} for k,c in rows.items() if k not in labels and at(c['event_end_time'])<=now}


def settle(engine,proofs):
    state=copy.deepcopy(engine.state);events=[];now=at(engine.clock());labels=state.setdefault('pricing_labels45',{})
    for key,proof in proofs.items():
        c=state.get('pricing_contracts45',{}).get(key)
        if c is None or key in labels:continue
        if (proof.get('forecast_id')!=key or proof.get('native_payout_verified') is not True or proof.get('verified') is not True
            or type(proof.get('payout')) not in (int,float) or proof.get('payout') not in (0,1) or any(proof.get(k)!=c[k] for k in ('market_id','event_id','token_id','rules_sha256'))
            or not at(c['timestamp'])<at(proof['resolved_at'])<=at(proof['available_at'])<=now):raise ValueError('exact prospective pricing-contract native proof required')
        labels[key]=proof;events.append({'type':'verified_native_pricing_contract','contract_id':key,'proof':proof,'probability_forecast':False})
        for name,s in state['profiles'].items():
            for oid,p in list(s['positions'].items()):
                if any(p[k]!=c[k] for k in ('market_id','event_id','token_id')) or any(p['market'][k]!=c['market'][k] for k in ('outcome','question','resolution_rules','resolution_source','end_time')) or not at(p['last_fill_at'])<at(proof['resolved_at']):continue
                value=p['quantity']*proof['payout'];s['cash']+=value
                closed={'strategy':p['strategy'],'event_id':p['event_id'],'forecast_id':None,'pnl':value-p['cost'],'cost':p['cost'],'kind':'native_verified_settlement','native_settled':True,'at':now.isoformat()}
                s['closed'].append(closed);s['day_loss']+=closed['pnl'];del s['positions'][oid];s['orders'].pop(oid,None);s['unrealized']=None if s['positions'] else 0.
                if s['day_loss']<=-500*engine.risk['daily_loss_fraction']:s['suspended']=True
                events.append({'type':'native_settlement','profile':name,'order_id':oid,'quantity':p['quantity'],'entry_forecast_id':p.get('forecast_id'),'proof':proof,**closed})
    if events:
        state['loss_ledger']=economics.ledger(events,state.get('loss_ledger'))
        return engine._commit(state,events,{'operation':'native pricing-contract settlement; not probability scoring'})
    return False
