"""Official event-target verification, distinct from native payout certification.

A completed NHL result can score a completion-conditioned research forecast.
It does not establish the contract's on-chain payout or calibrated tradeability.
"""
import hashlib
import importlib
import math
import re
import shutil
from datetime import UTC, datetime
from pathlib import Path

import httpx
from neraium_poly.research.phase14.relationships import digest
from neraium_poly.research.phase26 import outcomes as official

PROTOCOL='official-event-target-v30'
TARGET='winner_of_officially_completed_game_including_OT_SO'
AUTHORITY={'research_only':True,'trading_authority':False,'certification_authority':False,
    'native_payout_verified':False,'market_baseline_comparable':False}


async def verify_official_event(forecast,*,directory,clock=None):
    """Acquire authoritative completed-event proof without claiming settlement.

    Only existing strictly mapped NHL contracts are supported. No publisher result
    substitutes for NHL, and canceled/postponed/disputed games remain unscored.
    Source raw bytes are append-only/content-addressed in an isolated directory.
    """
    clock=clock or (lambda:datetime.now(UTC));now=official.at(clock())
    try:
        _market,parameters,start=official._mapping(forecast)
        if now<start:return {'status':'pending','event_result_verified':False,'reason':'official_game_not_started',**AUTHORITY}
        root=official._root(directory)
        if shutil.disk_usage(root).free<100*1024**3+8*1024**2:raise ValueError('event_result_filesystem_reserve')
        namespace='official-event-'+digest(forecast['id'])[:24];sub=official._root(root/namespace)
        async with httpx.AsyncClient(timeout=10,follow_redirects=False) as client:
            game,game_ref=await official._fetch(client,official.game_url(start),clock)
            teams,team_ref=await official._fetch(client,official.ORIGIN+'team?start=0&limit=100',clock)
            candidate=official.select_game(game,teams,parameters,start)
            refs=[official._save(sub,game,game_ref,'.json'),official._save(sub,teams,team_ref,'.json')]
            if candidate['status']!='final_candidate':return {'status':'pending','event_result_verified':False,'reason':candidate['reason'],'official_evidence':refs,**AUTHORITY}
            html,html_ref=await official._fetch(client,candidate['report_url'],clock)
            refs.append(official._save(sub,html,html_ref,'.html'))
        final=official.parse_official_nhl(game,teams,html,parameters,start,available_at=max(official.at(x['retrieved_at']) for x in refs))
        if not official.at(forecast['timestamp'])<official.at(final['actual_start_lower']):raise ValueError('forecast_not_prospectively_recorded_before_actual_start')
        return {'status':'official_event_verified','event_result_verified':True,'verification_protocol':PROTOCOL,
            'forecast_id':forecast['id'],'event_id':forecast['event_id'],'market_id':forecast['market_id'],'token_id':forecast['token_id'],
            'original_forecast_sha256':digest(forecast),'rules_sha256':forecast['rules_sha256'],
            'available_at':official.at(clock()).isoformat(),'official_result':final,'official_evidence':refs,
            'evidence_directory':namespace,'event_group_id':digest(['official-NHL-game',final['official_game_id']]),
            'target':TARGET,
            'native_settlement_status':'not_verified_separate_existing_gate_required',**AUTHORITY}
    except (ValueError,TypeError,KeyError,OSError,StopIteration,httpx.HTTPError) as error:
        return {'status':'withheld','event_result_verified':False,'reason':type(error).__name__+':'+str(error)[:180],**AUTHORITY}


def replay_official_event(result,study,forecast,*,evidence_root,as_of):
    """Replay raw official evidence and original model before descriptive scoring."""
    now=official.at(as_of);_market,parameters,start=official._mapping(forecast)
    if (result.get('verification_protocol')!=PROTOCOL or result.get('status')!='official_event_verified'
        or result.get('event_result_verified') is not True or result.get('native_payout_verified') is not False
        or result.get('trading_authority') is not False or result.get('certification_authority') is not False
        or result.get('market_baseline_comparable') is not False or result.get('target')!=TARGET
        or any(result.get(k)!=forecast[k] for k in ['event_id','market_id','token_id','rules_sha256'])
        or result.get('forecast_id')!=forecast['id'] or result.get('original_forecast_sha256')!=digest(forecast)
        or sum(f.get('id')==forecast['id'] and digest(f)==digest(forecast) for f in study.get('forecasts',[]))!=1
        or not official.at(forecast['timestamp'])<=official.at(study['available_at'])<start):
        raise ValueError('original_prospective_event_target_binding_required')
    evidence=study['evidence'];byid={e['id']:e for e in evidence}
    if len(byid)!=len(evidence):raise ValueError('duplicate_original_model_evidence')
    module=importlib.import_module('neraium_poly.research.phase25.sports')
    if module.replay(forecast,[byid[e] for e in forecast['evidence_ids']],as_of=now).get('verified') is not True:
        raise ValueError('original_independent_model_source_replay_failed')
    root=Path(evidence_root).absolute();namespace='official-event-'+digest(forecast['id'])[:24]
    if result['evidence_directory']!=namespace or root.is_symlink() or any(x.is_symlink() for x in root.parents):raise ValueError('official_event_evidence_root_mismatch')
    sub=root/namespace
    if sub.is_symlink():raise ValueError('official_event_evidence_directory_alias')
    refs=result['official_evidence']
    if not isinstance(refs,list) or len(refs)!=3:raise ValueError('three_official_event_sources_required')
    raw=[]
    for index,ref in enumerate(refs):
        expected=ref['content_sha256']+('.html' if index==2 else '.json');path=sub/expected
        if (ref['raw_file']!=expected or not re.fullmatch(r'[a-f0-9]{64}\.(json|html)',expected)
            or path.is_symlink() or not path.resolve().is_relative_to(sub.resolve()) or not 0<path.stat().st_size<=official.MAX_BYTES):
            raise ValueError('official_event_source_path_or_size_invalid')
        body=path.read_bytes()
        if (len(body)!=ref['bytes'] or hashlib.sha256(body).hexdigest()!=ref['content_sha256']
            or not official.at(ref['retrieved_at'])<=official.at(result['available_at'])<=now
            or index!=1 and official.at(ref['retrieved_at'])<start):raise ValueError('official_event_source_integrity_or_availability_mismatch')
        raw.append(body)
    if refs[0]['source_url']!=official.game_url(start) or refs[1]['source_url']!=official.ORIGIN+'team?start=0&limit=100':raise ValueError('exact_official_event_requests_required')
    final=official.parse_official_nhl(*raw,parameters,start,available_at=max(official.at(r['retrieved_at']) for r in refs))
    if (final!=result['official_result'] or refs[2]['source_url']!=final['report_url']
        or result['event_group_id']!=digest(['official-NHL-game',final['official_game_id']])
        or not official.at(forecast['timestamp'])<official.at(final['actual_start_lower'])):
        raise ValueError('official_event_result_identity_or_prospectivity_mismatch')
    p=forecast['probability'];outcome=final['expected_payout'];likelihood=p if outcome else 1-p
    if type(p) not in (int,float) or not math.isfinite(p) or not 0<=p<=1:raise ValueError('finite_original_probability_required')
    return {'event_result_verified':True,'verification_protocol':PROTOCOL,'forecast_id':forecast['id'],
        'event_id':forecast['event_id'],'market_id':forecast['market_id'],'token_id':forecast['token_id'],
        'event_group_id':result['event_group_id'],'outcome':outcome,'available_at':result['available_at'],
        'event_end_lower':final['end_lower'],'event_end_upper':final['end_upper'],
        'brier':(p-outcome)**2,'log_loss':-math.log(likelihood) if likelihood>0 else None,
        'log_loss_status':'finite' if likelihood>0 else 'positive_infinity','market_brier':None,'market_log_loss':None,
        'score_scope':'completion-conditioned official event target; not verified contract payout or market superiority',
        'official_evidence_sha256':digest(refs),'proof_sha256':digest(result),**AUTHORITY}
