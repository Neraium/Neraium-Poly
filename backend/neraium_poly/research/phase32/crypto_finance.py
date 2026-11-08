"""Exact crypto/finance reference readiness, not an event or payout label.

This guard runs before provider access: a license cannot repair contradictory
settlement rules. Original forecasts remain immutable, including failed ones.
"""
import hashlib
import json
from collections import Counter, defaultdict

from neraium_poly.research.phase14.relationships import digest
from neraium_poly.research.phase25.dependencies import at
from neraium_poly.research.phase25.finance import supports as spx_supports
from neraium_poly.research.phase31.crypto import TERMS, _contract, _require_reference

AUTHORITY={'research_only':True,'trading_authority':False,'certification_authority':False,
    'event_result_verified':False,'native_payout_verified':False,'outcome':None}


def qualify_reference(forecast,*,as_of):
    """Source-specific rule guard; never guesses an alternative reference venue."""
    f=forecast;now=at(as_of);m=f['market']
    if f.get('domain') not in {'crypto','finance'}:raise ValueError('crypto_or_finance_forecast_required')
    if (any(f[k]!=m[k] for k in ('market_id','event_id','token_id'))
        or hashlib.sha256(m['resolution_rules'].encode()).hexdigest()!=f['rules_sha256']):
        raise ValueError('original_exact_market_token_rule_binding_required')
    cutoff,created,end=at(f['evidence_cutoff']),at(f['timestamp']),at(f['event_end_time'])
    if not cutoff<=created<=now or created>=end:raise ValueError('prospective_forecast_cutoff_required')
    maturity='mature_boundary' if end<=now else 'future_boundary'
    if f['domain']=='crypto':
        c,start,boundary=_contract(f)
        reasons=[]
        try:_require_reference(f)
        except ValueError as error:reasons.append(str(error))
        ambiguous=bool(reasons)
        return {'domain':'crypto','market_id':f['market_id'],'token_id':f['token_id'],'event_id':f['event_id'],
            'rules_sha256':f['rules_sha256'],'reference_source':c.parameters['reference_source'],
            'symbol':c.parameters['symbol'],'period_start_utc':start.isoformat(),'period_end_utc':boundary.isoformat(),
            'maturity':maturity,'category':'RESOLUTION_REFERENCE_AMBIGUOUS' if ambiguous else 'NOT_YET_MATURE' if boundary>now else 'LICENSED_EXACT_OUTCOME_SOURCE_REQUIRED',
            'source_contract_qualified':not ambiguous,'forecast_reference_admissible':not ambiguous,
            'data_license_status':'authorization_unconfirmed_default_closed','data_license_terms':TERMS,
            'reasons':reasons+['official_archive_eligible_use_authorization_required'],
            'market_baseline_comparison':None,**AUTHORITY}
    rebound=spx_supports(m,cutoff=cutoff)
    if not rebound['supported'] or digest(rebound['contract'])!=digest(f['contract']):
        raise ValueError('exact_original_SPX_reference_and_contract_required')
    c=rebound['contract']
    return {'domain':'finance','market_id':f['market_id'],'token_id':f['token_id'],'event_id':f['event_id'],
        'rules_sha256':f['rules_sha256'],'reference_source':c['reference_source'],'symbol':'SPX',
        'period_start_utc':c['period_start'],'period_end_utc':c['period_end'],'maturity':maturity,
        'category':'NOT_YET_MATURE' if end>now else 'OFFICIAL_REFERENCE_RESULT_REQUIRED',
        'source_contract_qualified':True,'forecast_reference_admissible':True,
        'target_conditioning':c['conditioning'],'market_baseline_comparison':None,
        'reasons':['exact_WSJ_history_close_and_prior_actual_trading_session_required',
            'ties_no_trade_and_fallback_are_not_binary_labels','conditional_forecast_not_native_payout_probability'],**AUTHORITY}


def audit_crypto_finance(entries,*,source_loader,as_of):
    """Stream source groups once; quarantine conflicts, never create outcomes.

    source_loader(id) must return the original study dictionary. The bound index
    supplies source replay status; this audit independently checks its content
    hashes and exact preserved contract. It does not reclassify historical source
    availability or claim a provider restriction has changed.
    """
    now=at(as_of)
    if not isinstance(entries,(tuple,list)) or len(entries)>4096:raise ValueError('bounded_crypto_finance_inventory_required')
    refs={};conflicts=set()
    for ref in entries:
        if ref.get('type')!='forecast' or ref['forecast'].get('domain') not in {'crypto','finance'}:continue
        fid=ref['forecast_id']
        if fid in refs and digest(refs[fid])!=digest(ref):conflicts.add(fid)
        else:refs[fid]=ref
    groups=defaultdict(list);rows=[];decoded=0
    for fid,ref in refs.items():
        if fid not in conflicts:groups[ref['source_id']].append(ref)
    for source_id,source_refs in groups.items():
        try:
            study=source_loader(source_id)
            size=len(json.dumps(study,allow_nan=False,separators=(',',':')).encode());decoded+=size
            if size>32*1024**2 or decoded>128*1024**2:raise ValueError('bounded_original_source_decode_budget')
            if not isinstance(study,dict):raise TypeError('original_study_dictionary_required')
            sha=digest(study)
            for ref in source_refs:
                f=ref['forecast'];fid=ref['forecast_id']
                base={'forecast_id':fid,'source_id':source_id,'original_study_sha256':sha,
                    'domain':f['domain'],'event_id':f['event_id'],'market_id':f['market_id'],
                    'forecast_timestamp':f['timestamp'],'available_at':ref['available_at'],
                    'canonical_group_id':(ref.get('review') or {}).get('canonical_group_id'),**AUTHORITY}
                try:
                    originals=[x for x in study.get('forecasts',[]) if x.get('id')==fid]
                    if (study.get('id')!=source_id or sha!=ref['source_study_sha256'] or len(originals)!=1
                        or digest(originals[0])!=ref['forecast_sha256'] or ref.get('replay_verified') is not True
                        or f.get('id')!=fid or any(originals[0].get(k)!=v for k,v in f.items())):
                        raise ValueError('exact_original_source_replay_binding_required')
                    original=originals[0]
                    if not at(original['timestamp'])<=at(study['available_at'])==at(ref['available_at'])<=now:
                        raise ValueError('original_availability_cutoff_required')
                    if at(study['available_at'])>=at(original['event_end_time']):raise ValueError('original_publication_precedes_event_required')
                    row={**base,**qualify_reference(original,as_of=now),'source_binding_verified':True}
                except (ValueError,TypeError,KeyError) as error:
                    row={**base,'category':'ORIGINAL_SOURCE_OR_CONTRACT_UNQUALIFIED','source_binding_verified':False,
                        'source_contract_qualified':False,'forecast_reference_admissible':False,'reasons':[str(error)[:180]]}
                rows.append(row)
        except (ValueError,TypeError,KeyError,OSError) as error:
            for ref in source_refs:
                f=ref['forecast'];rows.append({'forecast_id':ref['forecast_id'],'source_id':source_id,'domain':f['domain'],
                    'event_id':f['event_id'],'market_id':f['market_id'],'category':'ORIGINAL_SOURCE_UNAVAILABLE',
                    'source_binding_verified':False,'source_contract_qualified':False,'forecast_reference_admissible':False,
                    'reasons':[str(error)[:180]],**AUTHORITY})
    for fid in sorted(conflicts):
        rows.append({'forecast_id':fid,'domain':refs[fid]['forecast']['domain'],'category':'CONFLICTING_FORECAST_IDENTITY',
            'source_binding_verified':False,'source_contract_qualified':False,'forecast_reference_admissible':False,**AUTHORITY})
    return {'schema_version':'phase32-exact-crypto-finance-readiness-v1','as_of':now.isoformat(),
        'forecasts':len(rows),'categories':dict(Counter(r['category'] for r in rows)),
        'maturity':dict(Counter(r.get('maturity','unqualified') for r in rows)),
        'source_contract_quarantined':sum(r['forecast_reference_admissible'] is False for r in rows),
        'event_groups_with_verified_outcomes':0,'effective_independent_sample_size':None,
        'source_groups_read':len(groups),'rows':rows,
        'scope':'preserved source/contract readiness; no provider requests, no labels, no original forecast mutation',**AUTHORITY}
