"""Causal operational relationships, not automated probability or trade authority.

The projection is compact enough to checkpoint a bounded source-time history.
Persistent findings compare a prior joint relationship to a later window; an
imbalance excursion alone is not a structural finding or a profitable signal.
"""
from collections import Counter, defaultdict
from datetime import UTC, datetime
from hashlib import sha256
from math import sqrt
from statistics import mean

from neraium_poly.contracts import MarketSnapshot, OrderBookSnapshot
from neraium_poly.data import assess_book
from neraium_poly.experimental.account import PUBLIC_BOOK_SOURCES
from neraium_poly.research.phase14.relationships import digest

VERSION='phase23-causal-operational-relationships-v1'
AUTHORITY={'research_only':True,'trading_authority':False,'certification_authority':False,
           'causality_verified':False,'forecast_improvement_verified':False,'executable_opportunity':False}


def _at(value):
    value=value if isinstance(value,datetime) else datetime.fromisoformat(value)
    if value.tzinfo is None or value.utcoffset() is None:raise ValueError('aware_relationship_cutoff_required')
    return value.astimezone(UTC)


def project_frame(frame, *, cutoff, max_tokens=256):
    """Retain authentic top-three operational features and exact source identities.

    The caller archives the source frame/book and this content-bound projection.
    It is a derived research artifact, never a substitute historical full book.
    """
    now=_at(cutoff)
    if type(max_tokens) is not int or not 1<=max_tokens<=512:
        raise ValueError('bounded_projection_tokens_required')
    if not isinstance(frame,dict) or len(frame.get('markets',[]))>4000 or len(frame.get('books',[]))>4000:
        raise ValueError('bounded_source_frame_required')
    markets={}
    ambiguous=set()
    for raw in frame.get('markets',[]):
        try:
            m=MarketSnapshot.model_validate(raw)
            if m.token_id in markets and markets[m.token_id]!=m:ambiguous.add(m.token_id)
            markets[m.token_id]=m
        except (ValueError,TypeError):continue
    rows=[]; rejected=Counter();seen=set()
    for raw in frame.get('books',[]):
        try:
            b=OrderBookSnapshot.model_validate(raw);m=markets.get(b.token_id)
            if b.token_id in seen or b.token_id in ambiguous:
                rejected['duplicate_or_ambiguous_token']+=1
                rows=[r for r in rows if r['token_id']!=b.token_id]
                continue
            seen.add(b.token_id)
            if (m is None or b.market_id!=m.market_id or b.exchange!=m.exchange
                or b.source not in PUBLIC_BOOK_SOURCES or m.source!='https://gamma-api.polymarket.com'
                or not m.timestamp<=m.available_at<=now or m.status!='active'
                or not m.end_time or m.end_time<=now):
                rejected['native_active_causal_identity_required']+=1;continue
            health=assess_book(b,now,max_spread=.05,expected_token=m.token_id)
            if not health.healthy:rejected.update(health.reasons);continue
            bid_shares=sum(p.size for p in b.bids[:3]);ask_shares=sum(p.size for p in b.asks[:3])
            mid=(b.bids[0].price+b.asks[0].price)/2
            rows.append({'market_id':m.market_id,'token_id':m.token_id,'event_id':m.event_id,'outcome':m.outcome,
                'question_sha256':sha256(m.question.encode()).hexdigest(),
                'rules_sha256':sha256(m.resolution_rules.encode()).hexdigest(),
                'resolution_source':m.resolution_source,'settlement_at':m.end_time.isoformat(),
                'market_id_record':m.id,'book_id':b.id,'book_sha256':digest(b.model_dump(mode='json')),
                'source':b.source,'source_timestamp':b.timestamp.isoformat(),'available_at':b.available_at.isoformat(),
                'midpoint':mid,'bid':b.bids[0].price,'ask':b.asks[0].price,'spread':health.spread,
                'imbalance':(bid_shares-ask_shares)/(bid_shares+ask_shares),
                'top3_bid_notional':sum(p.size*p.price for p in b.bids[:3]),
                'top3_ask_notional':sum(p.size*p.price for p in b.asks[:3]),
                'source_rules_present':bool(m.resolution_rules and m.resolution_source)})
        except (ValueError,TypeError,KeyError):rejected['malformed_observation']+=1
    # Stable identity selection avoids ex-post return selection and bounds journals.
    rows=sorted(rows,key=lambda r:(r['event_id'],r['market_id'],r['token_id']))[:max_tokens]
    result={'schema_version':VERSION,'cutoff':now.isoformat(),'source_frame_id':frame.get('id'),
        'observations':rows,'rejections':dict(rejected),'max_tokens':max_tokens,
        'projection_scope':'Observed top-three depth only; full native book hashes retained',**AUTHORITY}
    return {**result,'projection_sha256':digest(result)}


def _validated_projection(raw, cutoff):
    if not isinstance(raw,dict):raise TypeError('structured_historical_projection_required')
    value=dict(raw);claimed=value.pop('projection_sha256',None)
    if value.get('schema_version')!=VERSION or digest(value)!=claimed:
        raise ValueError('historical_projection_hash_required')
    at=_at(value['cutoff'])
    if at>cutoff:raise ValueError('future_relationship_history')
    for row in value['observations']:
        if not _at(row['source_timestamp'])<=_at(row['available_at'])<=at:
            raise ValueError('causal_projection_source_required')
    return value


def _fit(rows):
    xs=[r['imbalance'] for r in rows];ys=[r['midpoint'] for r in rows]
    mx,my=mean(xs),mean(ys);xx=sum((x-mx)**2 for x in xs)
    if xx<=1e-10:return None
    slope=sum((x-mx)*(y-my) for x,y in zip(xs,ys,strict=True))/xx
    residuals=[y-(my+slope*(x-mx)) for x,y in zip(xs,ys,strict=True)]
    return {'slope':slope,'x_mean':mx,'y_mean':my,'residual_rms':sqrt(mean(x*x for x in residuals))}


def evaluate_relationships(frame, history, *, cutoff):
    """Evaluate bounded source-time histories and preserve descriptive claim levels.

    Same-parent grouping alone never creates a logical constraint. The only logical
    candidate here is both Yes/No tokens of the SAME exact binary market, whose
    payoff/settlement conventions still require review before executable claims.
    """
    now=_at(cutoff)
    if not isinstance(history,(tuple,list)) or len(history)>64:
        raise ValueError('bounded_causal_relationship_history_required')
    current=project_frame(frame,cutoff=now)
    past=[]; rejected=Counter(current['rejections']);seen=set()
    for raw in history:
        try:
            p=_validated_projection(raw,now)
            if _at(p['cutoff'])>=_at(current['cutoff']):raise ValueError('strictly_prior_history_required')
            if _at(p['cutoff']) in seen:raise ValueError('duplicate_projection_time')
            seen.add(_at(p['cutoff']));past.append(p)
        except (ValueError,KeyError,TypeError) as error:
            rejected[str(error)[:100] if isinstance(error,ValueError) else 'invalid_projection']+=1
    past.sort(key=lambda p:_at(p['cutoff']))
    by_token=defaultdict(list)
    for p in past+[current]:
        for row in p['observations']:by_token[row['token_id']].append({**row,'observed_at':p['cutoff']})
    findings=[]
    for row in current['observations']:
        observations=by_token[row['token_id']]
        # Repeated HTTP receipt of the same source quote is not temporal evidence.
        distinct={r['book_id']:r for r in observations}
        observations=sorted(distinct.values(),key=lambda r:_at(r['observed_at']))
        if len(observations)<13:
            rejected['prior10_and_current3_distinct_observations_required']+=1;continue
        baseline,current_window=observations[-13:-3],observations[-3:]
        identities={(r['market_id'],r['event_id'],r['rules_sha256'],r['question_sha256'],r['settlement_at']) for r in observations[-13:]}
        if len(identities)!=1:
            rejected['unchanged_market_rule_identity_required']+=1;continue
        if (_at(current_window[-1]['source_timestamp'])-_at(current_window[0]['source_timestamp'])).total_seconds()<60:
            rejected['source_time_persistence60seconds_required']+=1;continue
        fit=_fit(baseline)
        if fit is None:rejected['nondegenerate_prior_joint_relationship_required']+=1;continue
        residuals=[r['midpoint']-(fit['y_mean']+fit['slope']*(r['imbalance']-fit['x_mean'])) for r in current_window]
        uncertainty=max(.005,3*fit['residual_rms'],max(r['spread']/2 for r in observations[-13:]))
        same_direction=all(x>uncertainty for x in residuals) or all(x<-uncertainty for x in residuals)
        if not same_direction:
            rejected['persistent_change_exceeds_spread_and_baseline_uncertainty_required']+=1;continue
        findings.append({'classification':'persistent_statistical_relationship_change_candidate',
            'relationship':'native_orderbook_imbalance_vs_midpoint','token_id':row['token_id'],'market_id':row['market_id'],
            'event_id':row['event_id'],'baseline':fit,'baseline_count':10,'persistence_count':3,
            'persistence_since':current_window[0]['source_timestamp'],'evaluated_at':now.isoformat(),
            'mean_current_residual':mean(residuals),'uncertainty':{'absolute_error_bound':uncertainty,
            'meaning':'Spread/measurement floor and three prior residual RMS; not a forecast confidence interval'},
            'evidence_sha256':[r['book_sha256'] for r in observations[-13:]],
            'rules_sha256':row['rules_sha256'],'qualification':'context_and_chronological_predictive_validation_required',**AUTHORITY})
    markets=defaultdict(list)
    for row in current['observations']:markets[row['market_id']].append(row)
    logical=[]
    for market_id,rows in markets.items():
        sides={r['outcome'].lower():r for r in rows}
        if len(rows)!=2 or set(sides)!={'yes','no'}:continue
        identities={(r['event_id'],r['rules_sha256'],r['question_sha256'],r['settlement_at'],r['resolution_source']) for r in rows}
        if len(identities)!=1 or not all(r['source_rules_present'] for r in rows):
            rejected['exact_binary_rule_identity_required']+=1;continue
        if abs((_at(rows[0]['source_timestamp'])-_at(rows[1]['source_timestamp'])).total_seconds())>5:
            rejected['synchronized_binary_quotes_required']+=1;continue
        logical.append({'classification':'same_contract_binary_consistency_observation','market_id':market_id,
            'event_id':rows[0]['event_id'],'tokens':[r['token_id'] for r in rows],
            'buy_both_observed_ask_sum':sum(r['ask'] for r in rows),'sell_both_observed_bid_sum':sum(r['bid'] for r in rows),
            'midpoint_sum':sum(r['midpoint'] for r in rows),'rules_sha256':rows[0]['rules_sha256'],
            'evidence_sha256':[r['book_sha256'] for r in rows],
            'logical_scope_reviewed':False,'after_cost_edge':None,
            'qualification':'payoff_scope_fees_depth_latency_and_all_leg_execution_review_required',**AUTHORITY})
    return {'schema_version':VERSION,'evaluated_at':now.isoformat(),'projection':current,
        'microstructure_observations':current['observations'],'persistent_relationship_findings':findings,
        'binary_consistency_observations':logical,'history_frames_used':len(past),
        'rejections':dict(rejected),'sii_trading_authority':False,
        'forecast_probabilities_created':0,'limitations':['Imbalance and midpoint share market data; neither is independent external evidence',
        'Persistent joint residual changes are research candidates, not causal or predictive proof',
        'Anonymous displayed depth cannot prove fills, queue position or profitable capacity'],**AUTHORITY}
