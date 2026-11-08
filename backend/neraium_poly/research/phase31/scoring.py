"""Domain-routed official targets, not native token payouts or trading authority."""
import math
from collections import Counter, defaultdict
from pathlib import Path

from neraium_poly.research.phase14.relationships import digest
from neraium_poly.research.phase25.dependencies import at
from neraium_poly.research.phase30.scoring import OfficialEventScoring


async def verify_event(f,*,directory,clock):
    if f.get('domain')=='crypto':
        from .crypto import verify_crypto_event
        # Provider license/access remains CLOSED; callers cannot self-authorize.
        return await verify_crypto_event(f,directory=directory,clock=clock)
    from neraium_poly.research.phase30.outcomes import verify_official_event
    return await verify_official_event(f,directory=directory,clock=clock)


def replay_event(result,study,f,*,evidence_root,as_of):
    if f.get('domain')=='crypto':
        from .crypto import replay_crypto_event
        return replay_crypto_event(result,study,f,evidence_root=evidence_root,as_of=as_of)
    from neraium_poly.research.phase30.outcomes import replay_official_event
    return replay_official_event(result,study,f,evidence_root=evidence_root,as_of=as_of)


def evaluate_domains(labels):
    targets={};errors=Counter();valid=set()
    for item in labels:
        try:
            f,p=item['forecast'],item['proof'];domain=f['domain'];publication=at(item['forecast_available_at'])
            if (p.get('event_result_verified') is not True or p.get('native_payout_verified') is not False
                or p.get('trading_authority') is not False or p.get('certification_authority') is not False
                or any(p.get(k)!=f[k] for k in ['market_id','token_id']) or p.get('forecast_id')!=f['id']):
                raise ValueError('exact_nontrading_event_proof_required')
            boundary=at(f['event_end_time']) if domain=='sports' else at(p['event_end_lower'])
            if not at(f['timestamp'])<=publication<boundary:raise ValueError('forecast_publication_must_precede_known_event_result')
            prob=f['probability'];y=p['outcome']
            if type(prob) not in (float,int) or not math.isfinite(prob) or not 0<=prob<=1 or type(y) not in (float,int) or y not in (0,1):raise ValueError('finite_binary_target_required')
            key=(domain,f['model_id'],p['event_group_id'],f['market_id'],f['token_id'],f['rules_sha256'])
            valid.add((item['label_id'],f['id']))
            if key not in targets or (at(f['timestamp']),f['id'])<(at(targets[key]['forecast']['timestamp']),targets[key]['forecast']['id']):targets[key]=item
        except (ValueError,KeyError,TypeError) as e:errors[str(e)[:160]]+=1
    clusters=defaultdict(list);domains=defaultdict(set)
    for key,item in targets.items():
        domain,model,group=key[:3];f,p=item['forecast'],item['proof'];prob=f['probability'];y=p['outcome']
        ll=-(math.log(prob) if y else math.log1p(-prob)) if 0<prob<1 else 0. if prob==y else None
        comparable=p.get('market_baseline_comparable') is True
        clusters[(domain,model,group)].append({'forecast_id':f['id'],'label_id':item['label_id'],'event_group_id':group,
            'brier':(prob-y)**2,'log_loss':ll,'market_brier':p.get('market_brier') if comparable else None,
            'market_log_loss':p.get('market_log_loss') if comparable else None,'neutral_brier':.25,'outcome':y,
            'forecast_probability':prob,'official_evidence_sha256':p.get('official_evidence_sha256')})
        domains[domain].add(group)
    grouped=defaultdict(list)
    def mean(rows,key):return sum(r[key] for r in rows)/len(rows) if rows and all(type(r.get(key)) in (float,int) and math.isfinite(r[key]) for r in rows) else None
    for (domain,model,group),rows in clusters.items():
        grouped[(domain,model)].append({'event_group_id':group,'targets':len(rows),'brier':mean(rows,'brier'),
            'log_loss':mean(rows,'log_loss'),'market_brier':mean(rows,'market_brier'),'market_log_loss':mean(rows,'market_log_loss'),
            'forecasts':rows})
    models=[]
    for (domain,model),events in sorted(grouped.items()):
        event_scores=[row for e in events for row in e['forecasts']]
        models.append({'domain':domain,'model_id':model,'event_disjoint_groups':len(events),'event_disjoint_official_games':len(events) if domain=='sports' else None,
            'descriptive_brier':mean(events,'brier'),'descriptive_log_loss':mean(events,'log_loss'),'log_loss_status':'positive_infinity' if any(e['log_loss'] is None for e in events) else 'finite','neutral_brier':.25,
            'market_baseline_comparison':{'brier':mean(events,'market_brier'),'log_loss':mean(events,'market_log_loss')} if mean(events,'market_brier') is not None else None,
            'aggregation':'earliest forecast per exact target, equal target weights within each event, equal event weights across events',
            'calibration':None,'confidence_intervals':None,'superiority_established':False,'event_scores':event_scores,
            'scope':'official event research, not verified native settlement or economically executable superiority',
            'research_only':True,'trading_authority':False,'certification_authority':False})
    return {'status':'official_event_research','schema_version':'phase31-domain-event-scores-v1','verified_forecast_labels':len(valid),
        'scored_forecast_event_model_pairs':len(targets),'distinct_official_event_groups':sum(len(v) for v in domains.values()),
        'distinct_official_games':len(domains.get('sports',set())),'event_groups_by_domain':{d:len(v) for d,v in domains.items()},
        'statistical_independence_verified':False,'effective_independent_sample_size':None,'models':models,'rejections':dict(errors),
        'native_verified_outcomes':0,'certified_training_events':0,'certified_heldout_events':0,'sii_paired_events':0,
        'sii_incremental_value':None,'realized_simulated_pnl':None,'native_payout_verified':False,'research_only':True,
        'trading_authority':False,'certification_authority':False}


class MultiDomainEventScoring(OfficialEventScoring):
    def __init__(self,*args,**kwargs):
        root=Path(__file__).parent
        extension={'version':'phase31-domain-event-routing-v1','code_sha256':digest([(root/n).read_text() for n in ['scoring.py','crypto.py']]),
            'crypto_provider_access':'closed pending eligible licensed-use authorization','additional_domains_without_exact_proof':'withheld'}
        super().__init__(*args,verify=verify_event,replay=replay_event,policy_extension=extension,**kwargs)

    def supports(self,ref):
        return ref['forecast'].get('domain')=='crypto' or super().supports(ref)

    def evaluate_labels(self,labels):
        return evaluate_domains(labels)
