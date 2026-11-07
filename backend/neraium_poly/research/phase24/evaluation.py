"""Official NFL result replay and descriptive, never self-certifying, scoring."""

import asyncio
import hashlib
import json
import math
import re
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
from neraium_poly.contracts import MarketSnapshot
from neraium_poly.research.phase12.contracts import SettlementProofReference, VerifiedEventOutcome
from neraium_poly.research.phase12.outcome_collector import acquire_verified_outcome, verify_collected_outcome
from neraium_poly.research.phase14.relationships import digest

MAX_BYTES=4*1024**2
TEAM_ALIASES={'LA':'LAR','LAR':'LAR','JAC':'JAX','JAX':'JAX','WSH':'WAS','WAS':'WAS','OAK':'LV','SD':'LAC','STL':'LAR'}
AUTHORITY={'research_only':True,'trading_authority':False,'certification_authority':False,'experimental_admission_authority':False}


def _at(value):
    value=value if isinstance(value,datetime) else datetime.fromisoformat(value)
    if value.tzinfo is None or value.utcoffset() is None:raise ValueError('aware_outcome_time_required')
    return value.astimezone(UTC)


def _team(value):
    if not isinstance(value,str) or not re.fullmatch(r'[A-Z]{2,3}',value):raise ValueError('exact_official_team_code_required')
    return TEAM_ALIASES.get(value,value)


def _flight(raw):
    """Decode embedded structured JSON only; never evaluate JavaScript/HTML."""
    if not isinstance(raw,bytes) or not 1<=len(raw)<=MAX_BYTES:raise ValueError('bounded_official_scoreboard_required')
    source=raw.decode('utf-8');decoder=json.JSONDecoder();parts=[]
    for match in re.finditer(r'self\.__next_f\.push\(',source):
        if len(parts)>=2000:raise ValueError('official_structured_chunk_limit')
        try:value,consumed=decoder.raw_decode(source,match.end())
        except ValueError:continue
        if not source.startswith(')',consumed):continue
        if isinstance(value,list) and len(value)==2 and value[0]==1 and isinstance(value[1],str):parts.append(value[1])
    nodes={}
    for line in ''.join(parts).splitlines():
        try:
            key,value=line.split(':',1)
            if re.fullmatch(r'[0-9a-f]+',key):nodes[key]=json.loads(value)
        except ValueError:continue
    if not nodes:raise ValueError('official_structured_scoreboard_schema_unavailable')
    def resolve(value):
        seen=set()
        while isinstance(value,str) and re.fullmatch(r'\$[0-9a-f]+(?::[^\s]+)*',value):
            if value in seen or len(seen)>32:raise ValueError('cyclic_official_source_reference')
            seen.add(value);key,*path=value[1:].split(':');value=nodes.get(key)
            for component in path:
                try:value=value[int(component)] if isinstance(value,list) else value[component]
                except (KeyError,IndexError,ValueError,TypeError):return None
        return value
    stack=list(nodes.values());games=[];visited=0
    while stack:
        value=stack.pop();visited+=1
        if visited>300000:raise ValueError('official_source_node_budget')
        if isinstance(value,dict):
            if all(k in value for k in ('homeTeam','awayTeam','gameTime','gameId','gameSummary')):games.append(value)
            stack.extend(value.values())
        elif isinstance(value,list):stack.extend(value)
    return games,resolve


def parse_official_nfl(raw,mapping,*,available_at):
    """Exact scheduled identities, final phase, full scores incl. overtime required."""
    now=_at(available_at);start=_at(mapping['event_start'])
    if mapping.get('league')!='NFL':raise ValueError('exact_nfl_mapping_required')
    expected={_team(mapping['selected_team_id']),_team(mapping['opponent_team_id'])}
    games,resolve=_flight(raw);matches=[]
    for game in games:
        try:
            home,away=resolve(game['homeTeam']),resolve(game['awayTeam'])
            if {_team(home['abbreviation']),_team(away['abbreviation'])}!=expected:continue
            if _at(game['gameTime'])!=start:continue
            summary=resolve(game['gameSummary'])
            state=game.get('analyticsProperties',{}).get('gameState')
            if not isinstance(summary,dict) or summary.get('phase')!='FINAL' or state!='FINAL':
                matches.append({'status':'pending','official_game_id':game['gameId'],'event_start':start.isoformat()});continue
            if summary.get('quarter') not in {'END_OF_GAME','OVERTIME','FINAL'}:raise ValueError('official_final_period_required')
            hs=resolve(summary.get('homeTeam')) or resolve(home.get('summary'))
            aws=resolve(summary.get('awayTeam')) or resolve(away.get('summary'))
            scores=[hs['score']['total'],aws['score']['total']]
            if any(type(x) is not int or not 0<=x<=200 for x in scores):raise ValueError('official_final_integer_scores_required')
            if now<=start:raise ValueError('future_official_final_result')
            selected_home=_team(home['abbreviation'])==_team(mapping['selected_team_id'])
            selected,opponent=scores if selected_home else reversed(scores)
            actual='win' if selected>opponent else 'loss' if selected<opponent else 'tie'
            matches.append({'status':'final','official_game_id':game['gameId'],'event_start':start.isoformat(),
                'home_id':_team(home['abbreviation']),'away_id':_team(away['abbreviation']),
                'home_score':scores[0],'away_score':scores[1],'actual':actual,
                'expected_contract_payout':1. if actual=='win' else 0. if actual=='loss' else .5,
                'includes_overtime':True,'observed_final_at':now.isoformat(),'completion_timestamp':None,
                'completion_time_bound':[start.isoformat(),now.isoformat()],
                'provider':'NFL.com official scoreboard','official_league_source':True})
        except (KeyError,TypeError):continue
    if not matches:raise ValueError('official_event_identity_or_schedule_not_found')
    unique={digest(m):m for m in matches}
    if len(unique)!=1:raise ValueError('ambiguous_or_corrected_official_result')
    return next(iter(unique.values()))


def score_ternary(forecast,actual):
    probs=forecast.get('outcome_probabilities',forecast.get('prediction',{}).get('uncertainty',{}).get('outcome_probabilities',{}))
    if (set(probs)!={'win','tie','loss'} or actual not in probs
        or any(type(x) not in (int,float) or not math.isfinite(x) or not 0<=x<=1 for x in probs.values())
        or abs(sum(probs.values())-1)>1e-10):raise ValueError('normalized_ternary_forecast_required')
    expected=probs['win']+.5*probs['tie'];payout={'win':1.,'tie':.5,'loss':0.}[actual]
    baseline=forecast.get('market_expected_payout',forecast.get('market_expected_payout_baseline'))
    if type(baseline) not in (int,float) or not math.isfinite(baseline) or not 0<baseline<1:raise ValueError('original_expected_payout_quote_required')
    likelihood=probs[actual]
    return {'actual':actual,'ternary_brier':sum((p-int(k==actual))**2 for k,p in probs.items()),
        'log_loss':-math.log(likelihood) if likelihood>0 else None,'log_loss_status':'finite' if likelihood>0 else 'positive_infinity',
        'expected_payout':expected,'observed_payout':payout,'expected_payout_mse':(expected-payout)**2,
        'market_expected_payout_mse':(baseline-payout)**2,'market_binary_brier':None,
        'market_ternary_baseline':None,'comparison_scope':'expected payout squared loss is not binary Brier or trading profit'}


def _original(study,forecast,*,as_of):
    from neraium_poly.research.phase13.mapping import map_market
    from neraium_poly.research.phase13.sources import load_sports
    from neraium_poly.research.phase23.models import forecast_nfl
    now=_at(as_of)
    if study.get('trading_authority') or study.get('certification_authority'):raise ValueError('research_only_original_required')
    matches=[f for f in study.get('forecasts',[]) if f.get('id')==forecast['id']]
    if len(matches)!=1 or digest(matches[0])!=digest(forecast):raise ValueError('immutable_forecast_membership_required')
    cutoff=_at(forecast['evidence_cutoff']);created=_at(forecast['timestamp'])
    if not cutoff<=created<=_at(study['available_at'])<=now:raise ValueError('original_forecast_chronology_required')
    if forecast.get('domain')!='sports' or forecast.get('probability_semantics')!='outcome_distribution':raise ValueError('nfl_ternary_target_required')
    data=load_sports(Path(forecast['source_reference']['snapshot']))
    if data['manifest_sha256']!=forecast['source_reference']['manifest_sha256']:raise ValueError('original_nfl_source_integrity_failure')
    result=next(x for x in forecast_nfl(forecast['market'],data,cutoff=cutoff) if x['model_id']==forecast['model_id'])
    if any(forecast.get(k)!=v for k,v in result.items()):raise ValueError('original_nfl_model_replay_failure')
    market=MarketSnapshot.model_validate(forecast['market']);mapping=map_market(market,data['games'],now=cutoff)
    if mapping.model_dump(mode='json')!=forecast['sports_mapping'] or created>=mapping.event_start:raise ValueError('exact_original_nfl_mapping_required')
    reference=SettlementProofReference(id=forecast['id'],event_id=market.event_id,market_id=market.market_id,token_id=market.token_id,
        timestamp=created,evidence_cutoff=cutoff,resolution_rules_sha256=mapping.rules_sha256,original_record_sha256=digest(forecast))
    return market,mapping.model_dump(mode='json'),reference


def _url(mapping):
    matched=re.fullmatch(r'(20\d{2})_(\d{2})_[A-Z]{2,3}_[A-Z]{2,3}',mapping['game_id'])
    if not matched or not 1<=int(matched[2])<=22:raise ValueError('reviewed_nfl_week_identity_required')
    return f'https://www.nfl.com/scores/{matched[1]}/week-{int(matched[2])}'


def replay_nfl_outcome(row,study,forecast,*,evidence_root,as_of):
    now=_at(as_of);result=row.get('result',row)
    if result.get('status')!='verified' or result.get('forecast_id')!=forecast['id']:raise ValueError('original_bound_verified_envelope_required')
    market,mapping,reference=_original(study,forecast,as_of=now)
    evidence=result['official_evidence'];available=_at(evidence['available_at'])
    if not _at(evidence['retrieved_at'])<=available<=_at(result['available_at'])<=now:raise ValueError('causal_official_evidence_receipt_required')
    if evidence['source_url']!=_url(mapping):raise ValueError('official_resolution_reference_mismatch')
    original_root=Path(evidence_root).absolute()
    if original_root.is_symlink() or any(p.is_symlink() for p in original_root.parents):raise ValueError('official_source_root_alias')
    root=original_root.resolve();path=root/evidence['raw_file']
    if path.is_symlink() or not path.resolve().is_relative_to(root):raise ValueError('official_source_path_escape')
    raw=path.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=evidence['content_sha256']:raise ValueError('official_raw_evidence_hash_mismatch')
    official=parse_official_nfl(raw,mapping,available_at=available)
    if official['status']!='final' or official!=result['official_result']:raise ValueError('official_pending_changed_or_disputed_result')
    if official['actual']=='tie':raise ValueError('native_half_payout_proof_not_supported')
    outcome=VerifiedEventOutcome.model_validate(result['native_outcome'])
    if not verify_collected_outcome(outcome,market,reference,root):raise ValueError('native_finalized_settlement_replay_failed')
    if not _at(forecast['timestamp'])<mapping_time(mapping)<outcome.settled_at<=_at(result['available_at']):raise ValueError('native_settlement_temporal_mismatch')
    if outcome.payout!=official['expected_contract_payout']:raise ValueError('official_nfl_and_native_payout_disagree')
    return {'verified':True,'forecast_id':forecast['id'],'event_id':forecast['event_id'],'market_id':forecast['market_id'],
        'token_id':forecast['token_id'],'rules_sha256':forecast['rules_sha256'],'resolved_at':outcome.settled_at.isoformat(),
        'available_at':result['available_at'],'scores':score_ternary(forecast,official['actual']),
        'official_result':official,'evidence_sha256':digest([evidence,result['native_outcome']]),'reviewed_dependency_group':None,**AUTHORITY}


def mapping_time(mapping):return _at(mapping['event_start'])


async def acquire_nfl_outcome(study,forecast,*,directory,clock=None,client=None):
    clock=clock or (lambda:datetime.now(UTC));now=_at(clock())
    market,mapping,reference=await asyncio.to_thread(_original,study,forecast,as_of=now)
    if now<mapping_time(mapping)+timedelta(hours=4):return {'status':'pending','reason':'scheduled_result_check_not_due','forecast_id':forecast['id'],**AUTHORITY}
    url=_url(mapping);owned=client is None;client=client or httpx.AsyncClient(timeout=12,follow_redirects=False)
    try:
        async with client.stream('GET',url) as response:
            response.raise_for_status();body=bytearray()
            if int(response.headers.get('content-length','0'))>MAX_BYTES:raise ValueError('official_response_budget')
            async for chunk in response.aiter_bytes():
                body.extend(chunk)
                if len(body)>MAX_BYTES:raise ValueError('official_response_budget')
    finally:
        if owned:await client.aclose()
    received=_at(clock());raw=bytes(body);official=parse_official_nfl(raw,mapping,available_at=received)
    if official['status']!='final':return {'status':'pending','reason':'official_game_not_final','forecast_id':forecast['id'],**AUTHORITY}
    if official['actual']=='tie':return {'status':'withheld','reason':'native_half_payout_proof_not_supported','official_result':official,'forecast_id':forecast['id'],**AUTHORITY}
    directory=Path(directory)
    if directory.is_symlink() or any(p.is_symlink() for p in directory.parents):raise ValueError('outcome_directory_symlink')
    directory.mkdir(parents=True,exist_ok=True)
    sha=hashlib.sha256(raw).hexdigest();name='nfl-'+received.strftime('%Y%m%dT%H%M%S%fZ')+'-'+sha[:12]+'.html'
    with (directory/name).open('xb') as handle:handle.write(raw)
    evidence={'provider':'NFL.com official scoreboard','source_url':url,'source_timestamp':None,'retrieved_at':received.isoformat(),
        'available_at':received.isoformat(),'availability_basis':'first_observed_retrieval','raw_file':name,'content_sha256':sha,'official_league_source':True}
    native=await acquire_verified_outcome(reference,market,directory/(received.strftime('%Y%m%dT%H%M%S%fZ')+'-native'),clock=clock)
    if native is None:return {'status':'withheld','reason':'native_finalized_settlement_unavailable','forecast_id':forecast['id'],'official_evidence':evidence,'official_result':official,**AUTHORITY}
    result={'status':'verified','forecast_id':forecast['id'],'available_at':_at(clock()).isoformat(),'official_evidence':evidence,
        'official_result':official,'native_outcome':native.model_dump(mode='json'),**AUTHORITY}
    replay=await asyncio.to_thread(replay_nfl_outcome,result,study,forecast,evidence_root=directory,as_of=_at(clock()))
    return {**result,'scores':replay['scores']}


def evaluate(studies,outcomes=(),*,as_of,outcome_verifier=None):
    """Scores require independent replay callbacks; pending models stay unranked."""
    now=_at(as_of)
    if not isinstance(studies,(tuple,list)) or len(studies)>2000 or len(outcomes)>2000:raise ValueError('bounded_evaluation_inputs_required')
    forecasts={};rejected=Counter();scores=[]
    for study in studies:
        for f in study.get('forecasts',[]):
            if _at(f['timestamp'])>now or _at(f['evidence_cutoff'])>_at(f['timestamp']):raise ValueError('noncausal_evaluation_forecast')
            if f['id'] in forecasts and digest(forecasts[f['id']])!=digest(f):raise ValueError('conflicting_evaluation_forecast')
            forecasts[f['id']]=f
    seen={};conflicts=set()
    for row in outcomes:
        try:
            result=row.get('result',row);f=forecasts.get(result.get('forecast_id'))
            if f is None or not callable(outcome_verifier):raise ValueError('independent_terminal_replay_required')
            verified=outcome_verifier(row,f)
            if (not isinstance(verified,dict) or verified.get('verified') is not True or any(verified.get(k)!=f[k] for k in ('forecast_id','event_id','market_id','token_id','rules_sha256') if k!='forecast_id')
                or verified.get('forecast_id')!=f['id'] or not _at(f['timestamp'])<_at(verified['resolved_at'])<=_at(verified['available_at'])<=now):
                raise ValueError('exact_verified_forecast_target_required')
            if f['id'] in conflicts:raise ValueError('conflicting_verified_result')
            if f['id'] in seen and digest(seen[f['id']])!=digest(verified):
                seen.pop(f['id'],None);conflicts.add(f['id']);raise ValueError('conflicting_verified_result')
            seen[f['id']]=verified
        except (ValueError,KeyError,TypeError,OSError,StopIteration) as error:rejected[str(error)[:160]]+=1
    scores=[{'model_id':forecasts[fid].get('model_id',forecasts[fid].get('model_version')),'event_id':forecasts[fid]['event_id'],**score} for fid,score in seen.items()]
    grouped=defaultdict(list)
    for f in forecasts.values():grouped[f.get('model_id',f.get('model_version'))].append(f)
    rows=[]
    for model,fs in sorted(grouped.items()):
        ms=[x for x in scores if x['model_id']==model]
        rows.append({'model_id':model,'forecasts':len(fs),'verified_forecast_outcomes':len(ms),'native_parent_ids':len({f['event_id'] for f in fs}),
            'pending_forecasts':len(fs)-len(ms),'descriptive_verified_scores':ms,'calibration':None,'independent_event_count':0,
            'metrics':None,'confidence_intervals':None,'profitability_rank':None,'net_executable_edge':None,'simulated_pnl':None,
            'reason':'reviewed event-disjoint cohorts and homogeneous chronological splits required',**AUTHORITY})
    return {'schema_version':'phase24-verified-evaluation-v1','as_of':now.isoformat(),'leaderboard':rows,'rejections':dict(rejected),
        'counts':{'forecasts':len(forecasts),'individually_verified_forecasts':len(seen),'pending_forecasts':len(forecasts)-len(seen),'reviewed_independent_groups':0},
        'sii_incremental_value':None,'ensemble_weights':None,'certification_requirements':{'training_independent_events':100,'heldout_independent_events':100},**AUTHORITY}
