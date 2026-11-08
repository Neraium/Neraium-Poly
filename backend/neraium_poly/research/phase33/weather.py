"""Causal weather cohort learning and station-day coverage, never authority.

Replays original model inputs plus saved official reference bytes. Native payout
and unconditional market comparison remain separate, unsatisfied requirements.
"""
from collections import Counter, defaultdict
from itertools import combinations

from neraium_poly.contracts import MarketSnapshot, OrderBookSnapshot
from neraium_poly.data import assess_book
from neraium_poly.experimental.account import PUBLIC_BOOK_SOURCES
from neraium_poly.research.phase14.relationships import digest
from neraium_poly.research.phase25 import weather as model
from neraium_poly.research.phase25.dependencies import at
from neraium_poly.research.phase31.scoring import evaluate_domains
from neraium_poly.research.phase32.weather import _mapping, replay_weather_event


def station_day(contract):
    return (contract['station'],contract['day'])


def prioritize_weather(markets,books,entries,*,as_of,maximum=32):
    """Rank unrepresented exact station-days before repeated forecasts.

    Metadata-only candidates may guide existing bounded book subscriptions;
    they are explicitly not eligible forecasts. No new subscription is opened.
    Existing rule interpretation, source timestamps and 5c spread are unchanged.
    """
    now=at(as_of)
    if type(maximum) is not int or not 1<=maximum<=64 or len(markets)>4096 or len(books)>4096 or len(entries)>8192:
        raise ValueError('bounded_weather_coverage_inputs_required')
    represented=set();reasons=Counter();bytoken={};conflicts=set()
    for row in entries:
        if row.get('type')!='forecast' or row['forecast'].get('domain')!='weather' or not row.get('replay_verified'):continue
        if max(at(row['forecast']['timestamp']),at(row['available_at']))>now:continue
        d=(row.get('review') or {}).get('descriptor') or {}
        if d.get('station') and d.get('day'):represented.add((d['station'],d['day']))
    for value in books:
        b=value if isinstance(value,OrderBookSnapshot) else OrderBookSnapshot.model_validate(value)
        if b.token_id in bytoken:
            if digest(bytoken[b.token_id].model_dump(mode='json'))!=digest(b.model_dump(mode='json')):conflicts.add(b.token_id)
        else:bytoken[b.token_id]=b
    candidates=[];market_tokens={};market_conflicts=set()
    for value in markets:
        m=value if isinstance(value,MarketSnapshot) else MarketSnapshot.model_validate(value)
        if m.token_id in market_tokens and digest(market_tokens[m.token_id].model_dump(mode='json'))!=digest(m.model_dump(mode='json')):market_conflicts.add(m.token_id)
        else:market_tokens[m.token_id]=m
    reasons['conflicting_market_tokens_quarantined']=len(market_conflicts)
    for token in market_conflicts:market_tokens.pop(token,None)
    for m in market_tokens.values():
        mapped=model.supports(m,cutoff=now)
        if not mapped['supported']:reasons.update(mapped['reasons']);continue
        c=mapped['contract'];group=station_day(c);b=bytoken.get(m.token_id);fail=[]
        if m.token_id in conflicts:fail.append('conflicting_book_identity')
        elif b is None:fail.append('current_book_missing')
        elif b.market_id!=m.market_id or b.source not in PUBLIC_BOOK_SOURCES or b.exchange!=m.exchange:fail.append('native_book_identity_or_source_mismatch')
        elif not 0<=(now-b.available_at).total_seconds()<=15:fail.append('book_receipt_stale_or_future')
        else:fail.extend(assess_book(b,now,max_spread=.05,expected_token=m.token_id).reasons)
        healthy=not fail
        candidates.append({'market_id':m.market_id,'event_id':m.event_id,'token_id':m.token_id,'station':group[0],'station_local_day':group[1],
            'station_day_id':digest(['weather-station-day',*group]),'station_day_already_forecast':group in represented,
            'period_end':c['period_end'],'resolution_source':m.resolution_source,'rules_sha256':c['rules_sha256'],
            'book_eligible_at_evaluation':healthy,'book_id':b.id if b else None,'book_timestamp':b.timestamp.isoformat() if b else None,
            'book_available_at':b.available_at.isoformat() if b else None,'book_sha256':digest(b.model_dump(mode='json')) if b else None,
            'best_ask':b.asks[0].price if healthy else None,'best_bid':b.bids[0].price if healthy else None,
            'displayed_ask_shares':sum(p.size for p in b.asks) if healthy else None,
            'metadata_market_probability':m.probability,'book_acquisition_priority_distance_to_half':abs(m.probability-.5),
            'blockers':sorted(set(fail))+['independent_AWC_evidence_and_model_generation_still_required','calibration_native_payout_and_risk_approval_not_established'],
            'forecast_created':False,'research_only':True,'trading_authority':False})
    candidates.sort(key=lambda r:(r['station_day_already_forecast'],not r['book_eligible_at_evaluation'],at(r['period_end']),r['station'],r['book_acquisition_priority_distance_to_half'],r['market_id'],r['token_id']))
    queues=defaultdict(list)
    for row in candidates:queues[(row['station'],row['station_local_day'])].append(row)
    ordered=[]
    while queues and len(ordered)<maximum:
        for key in list(queues):
            ordered.append(queues[key].pop(0))
            if not queues[key]:del queues[key]
            if len(ordered)==maximum:break
    return {'schema_version':'phase33-weather-coverage-v1','as_of':now.isoformat(),'candidates':ordered,
        'supported_outcome_tokens':len(candidates),'supported_station_days':len({(r['station'],r['station_local_day']) for r in candidates}),
        'new_station_days_with_eligible_books':len({(r['station'],r['station_local_day']) for r in candidates if r['book_eligible_at_evaluation'] and not r['station_day_already_forecast']}),
        'rejections':dict(reasons),'selection_scope':'bounded metadata/book scheduling only; Gamma price distance to0.5 is a book-acquisition heuristic, never an independent forecast or evidence source',
        'research_only':True,'trading_authority':False,'certification_authority':False}


def prior_weather_groups(scored,row):
    """Available same-model labels from strictly earlier, different station-days."""
    return {r['station_day_id'] for r in scored if r['model_id']==row['model_id'] and r['station_day_id']!=row['station_day_id']
        and at(r['label_available_at'])<=at(row['evidence_cutoff']) and at(r['end'])<at(row['evidence_cutoff'])}


def weather_cohort(records,*,evidence_root,as_of):
    """Replay trusted raw sources; expose when labels really became learnable.

    Multiple forecasts/tokens at one station-day never increase event-group n.
    Availability is verification receipt time, never retroactively the day end.
    No calibrator is fitted to this small cohort or used for earlier forecasts.
    """
    now=at(as_of)
    if not isinstance(records,(list,tuple)) or len(records)>256:raise ValueError('bounded_weather_cohort_required')
    originals={};conflicts=set();rejected=Counter();labels=[];observations=[]
    for row in records:
        f=row['forecast'];identity=f['id'];sha=digest(f)
        if identity in originals:
            if (digest(originals[identity]['forecast'])!=sha or digest(originals[identity]['study'])!=digest(row['study']) or digest(originals[identity].get('result'))!=digest(row.get('result'))):conflicts.add(identity)
        else:originals[identity]=row
    for identity,row in originals.items():
        if identity in conflicts:rejected['conflicting_original_forecast_id']+=1;continue
        f=row['forecast'];s=row['study'];r=row.get('result')
        try:
            module,c,end,_source_end,_url=_mapping(f)
            if not at(f['timestamp'])<=at(s['available_at'])<=now:raise ValueError('original_publication_not_available')
            if sum(x.get('id')==identity and digest(x)==digest(f) for x in s.get('forecasts',[]))!=1:raise ValueError('original_study_membership_required')
            if module.replay(f,s['evidence'],as_of=now).get('verified') is not True:raise ValueError('original_model_replay_required')
            item={'forecast_id':identity,'model_id':f['model_id'],'market_id':f['market_id'],'token_id':f['token_id'],
                'station':c['station'],'station_local_day':c['day'],'station_day_id':digest(['AWC-station-local-day',c['station'],c['day']]),
                'forecast_timestamp':f['timestamp'],'evidence_cutoff':f['evidence_cutoff'],'forecast_available_at':s['available_at'],
                'end':end.isoformat(),'probability':f['probability'],'market_midpoint_observation':f.get('market_expected_payout'),
                'market_comparison_status':'withheld_conditional_reference_target_not_native_payout','status':'pending_reference_result','label_available_at':None,
                'native_payout_verified':False,'forecast_sha256':digest(f),'study_sha256':digest(s)}
            if r and r.get('event_result_verified') is True:
                if at(r['available_at'])>now:
                    item['status']='pending_outcome_availability';observations.append(item);rejected['future_verified_result_withheld']+=1;continue
                p=replay_weather_event(r,s,f,evidence_root=evidence_root,as_of=now)
                labels.append({'label_id':digest(r),'forecast':f,'forecast_available_at':s['available_at'],'proof':p})
                item.update(status='official_reference_scored',label_available_at=r['available_at'],outcome=p['outcome'],
                    brier=p['brier'],log_loss=p['log_loss'],official_evidence_sha256=p['official_evidence_sha256'])
            observations.append(item)
        except (ValueError,TypeError,KeyError,OSError) as error:rejected[str(error)[:160]]+=1
    scored=[r for r in observations if r['status']=='official_reference_scored']
    for row in observations:
        prior=prior_weather_groups(scored,row)
        row['point_in_time_prior_qualified_station_days']=len(prior)
    evaluation=evaluate_domains(labels);pairwise=[];model_targets={}
    for m in evaluation['models']:
        targets={}
        for r in m['event_scores']:
            f=originals[r['forecast_id']]['forecast'];key=(r['event_group_id'],f['market_id'],f['token_id'],f['rules_sha256'])
            targets[key]=r['brier']
        model_targets[m['model_id']]=targets
    for a,b in combinations(sorted(model_targets),2):
        common=set(model_targets[a])&set(model_targets[b]);bygroup=defaultdict(list)
        for key in common:bygroup[key[0]].append(model_targets[a][key]-model_targets[b][key])
        deltas=[sum(v)/len(v) for v in bygroup.values()]
        pairwise.append({'model_a':a,'model_b':b,'same_station_day_groups':len(bygroup),'same_exact_targets':len(common),
            'descriptive_brier_a_minus_b':sum(deltas)/len(deltas) if deltas else None,
            'confidence_interval':None,'superiority_established':False,'scope':'same exact official targets; equal target weights within each station-day, then equal station-day weights; exploratory only'})
    return {'schema_version':'phase33-causal-weather-cohort-v1','as_of':now.isoformat(),'forecasts_replayed':len(observations),
        'official_reference_forecasts_scored':len(scored),'distinct_scored_station_days':len({r['station_day_id'] for r in scored}),
        'forecasts_with_any_prior_qualified_station_day':sum(r['point_in_time_prior_qualified_station_days']>0 for r in observations),
        'pending_forecasts':len(observations)-len(scored),'observations':observations,'models':evaluation['models'],'paired_model_comparisons':pairwise,
        'rejections':dict(rejected),'calibration_status':'not_fitted; distinct event groups and verified availability must mature causally',
        'market_superiority_established':False,'market_baseline_metrics':None,'native_payouts_verified':0,'certified_training_events':0,'certified_heldout_events':0,
        'effective_independent_sample_size':None,'statistical_independence_established':False,
        'research_only':True,'trading_authority':False,'certification_authority':False}
