"""Exact native-fee headroom for paired depth; never an all-in profit proof."""
import json
import math
from collections import Counter
from pathlib import Path

from neraium_poly.contracts import MarketSnapshot, OrderBookSnapshot
from neraium_poly.research.phase14.relationships import digest
from neraium_poly.research.phase25.dependencies import at
from neraium_poly.research.phase29.costs import replay_fee
from neraium_poly.research.phase32.pairs import CAPITALS, pair_frontier

MISSING=('fill_fragmentation_rounding','additional_slippage','latency_adverse_selection',
    'capital_lockup_cost','settlement_redemption_cost','atomic_two_leg_execution','native_complete_set_payout_proof')


def _sweep(levels,capital,minimum):
    quantity=principal=fee=gross=0.
    for level in levels:
        cost=level['price']+level['fee']
        if cost>=1-1e-12:break
        take=min(level['quantity'],max(0.,capital-principal-fee)/cost)
        quantity+=take;principal+=take*level['price'];fee+=take*level['fee'];gross+=take*(1-level['price'])
    return {'paired_quantity':quantity,'principal':principal,'formula_fee':fee,
        'formula_acquisition_capital':principal+fee,'conditional_gross_profit':gross,
        'remaining_cost_budget_before_break_even':gross-fee,'native_minimum_quantity_met':quantity+1e-9>=minimum,
        'conservative_expected_net_profit':None,'return_on_capital':None,'actual_fill':False}


def _frontier(books,proofs,participation,minimum):
    levels=[[[p.price,p.size*participation] for p in b.asks] for b in books];i=j=0;matched=[]
    while i<len(levels[0]) and j<len(levels[1]):
        y,n=levels[0][i],levels[1][j];price=y[0]+n[0]
        if price>=1-1e-12:break
        q=min(y[1],n[1]);fee=math.fsum(p['rate']*x*(1-x) for p,x in zip(proofs,[y[0],n[0]],strict=True))
        matched.append({'price':price,'fee':fee,'quantity':q})
        y[1]-=q;n[1]-=q
        if y[1]<=1e-10:i+=1
        if n[1]<=1e-10:j+=1
    principal=math.fsum(r['price']*r['quantity'] for r in matched)
    gross=math.fsum((1-r['price'])*r['quantity'] for r in matched)
    fees=math.fsum(r['fee']*r['quantity'] for r in matched)
    return {'matched_depth_segments':len(matched),'gross_frontier':{'paired_quantity':math.fsum(r['quantity'] for r in matched),
        'principal':principal,'conditional_gross_profit':gross,'formula_fee':fees,'formula_fee_headroom':gross-fees,
        'conservative_expected_net_profit':None},'maximum_formula_headroom':_sweep(matched,float('inf'),minimum),
        'capital_scenarios':[{'hypothetical_bankroll':c,'capital_ceiling':c*.2,**_sweep(matched,c*.2,minimum)} for c in CAPITALS]}


def annotate_pair_fees(pair_report,frame,observations,store,*,as_of):
    """Revalidate full books and immutable fee responses at the original decision.

    ``observations`` is token -> observed_fee result or FeeObservation id. The
    getter replays official token/condition membership, curve and receipt TTL.
    Only recorded paired findings (at most24) are evaluated. No raw-history scan,
    network call, account access or journal write occurs. Source depth is taken
    from the exact frame, never the phase32 report's truncated display levels.

    Headroom subtracts the verified *unrounded formula*, not unknowable realized
    fees. Fragmentation can change rounding; positive/negative formula headroom
    is sensitivity evidence only. All-in conservative profit remains null.
    """
    now=at(as_of);raw=frame.model_dump(mode='json') if hasattr(frame,'model_dump') else frame
    out={'schema_version':'phase33-pair-fee-headroom-v1','implementation_sha256':digest(Path(__file__).read_text()),
        'as_of':now.isoformat(),'source_pair_report_sha256':digest(pair_report),'findings':[],
        'verified_fee_pairs':0,'positive_formula_headroom_pairs':0,'qualified_opportunities':0,
        'aggregate_deployable_capital':None,'aggregate_net_profit':None,'correlation_aggregation':'not summed across parent events',
        'all_in_costs_verified':False,'missing_all_in_evidence':list(MISSING),'conservative_expected_net_profit':None,'research_only':True,
        'trading_authority':False,'certification_authority':False,'actual_fill':False,'realized_pnl':None}
    try:
        rows=pair_report.get('findings',[])
        if (pair_report.get('research_only') is not True or pair_report.get('trading_authority') is not False
            or at(pair_report['as_of'])!=now or pair_report['frame_sha256']!=digest(raw)
            or raw.get('mode')!='real_market_data' or not at(raw['timestamp'])<=at(raw['available_at'])<=now
            or len(raw['books'])>4096 or len(raw['markets'])>4096 or not isinstance(rows,list) or len(rows)>24):
            raise ValueError('exact_bounded_decision_frame_and_nontrading_pair_report_required')
        books={b['token_id']:b for b in raw['books']}
        markets={m['token_id']:MarketSnapshot.model_validate(m) for m in raw['markets']}
        if len(books)!=len(raw['books']) or len(markets)!=len(raw['markets']):raise ValueError('unique_frame_book_and_market_tokens_required')
        reasons=Counter();used=set()
        for row in rows:
            result={k:row.get(k) for k in ('market_id','event_id','token_ids','rules_sha256','end_time','settlement_reference')}
            result.update(status='fee_evidence_missing',conservative_expected_net_profit=None,missing_cost_evidence=list(MISSING))
            try:
                tokens=row['token_ids']
                if len(tokens)!=2 or len(set(tokens))!=2:raise ValueError('distinct_pair_tokens_required')
                if used.intersection(tokens):raise ValueError('pair_liquidity_already_enrolled_in_report')
                source=[OrderBookSnapshot.model_validate(books[t]) for t in tokens]
                if ([digest(b.model_dump(mode='json')) for b in source]!=row['book_sha256']
                    or any(b.market_id!=row['market_id'] for b in source)):
                    raise ValueError('paired_native_book_provenance_mismatch')
                metadata=[markets[t] for t in tokens]
                if (any(m.market_id!=row['market_id'] or m.event_id!=row['event_id'] or m.exchange!='polymarket'
                    or m.source!='https://gamma-api.polymarket.com' or not m.timestamp<=m.available_at<=now
                    or m.status!='active' or m.end_time is None or m.end_time<=now for m in metadata)
                    or [m.outcome.casefold() for m in metadata]!=['yes','no']
                    or any(digest(m.resolution_rules)!=row['rules_sha256'] or m.resolution_source!=row['settlement_reference']
                        or at(row['end_time'])!=m.end_time for m in metadata)
                    or metadata[0].question!=metadata[1].question):raise ValueError('exact_pair_event_and_settlement_metadata_required')
                used.update(tokens)
                participation=row['participation_assumption'];minimum=row['minimum_paired_quantity']
                pair_frontier(*source,as_of=now,minimum_quantity=minimum,participation=participation)
                proofs=[]
                for token in tokens:
                    observation=observations.get(token)
                    proof=replay_fee(observation,store,token_id=token,as_of=now)
                    if proof['status']!='verified_current_protocol_curve':raise ValueError(proof.get('reason','fee_proof_unavailable'))
                    proofs.append(proof)
                if proofs[0]['condition_id']!=proofs[1]['condition_id']:raise ValueError('native_pair_condition_ids_mismatch')
                if abs(proofs[0]['rate']-proofs[1]['rate'])>1e-12:raise ValueError('native_shared_condition_fee_curve_disagreement')
                frontier=_frontier(source,proofs,participation,minimum)
                result.update(status='conditional_verified_fee_formula',condition_id=proofs[0]['condition_id'],
                    native_fee_proofs=proofs,**frontier,all_in_costs_verified=False,
                    fee_scope='exact fd.r*p*(1-p) before per-fill rounding; not guaranteed charged fees',
                    profitability_scope='conditional payoff assumption; no native settlement/atomic execution proof')
                out['verified_fee_pairs']+=1
                out['positive_formula_headroom_pairs']+=frontier['maximum_formula_headroom']['remaining_cost_budget_before_break_even']>0
            except (ValueError,TypeError,KeyError,IndexError,OverflowError,OSError) as error:
                result['reason']=str(error)[:160];reasons[result['reason']]+=1
            out['findings'].append(result)
        out.update(status='research_fee_headroom',rejections=dict(reasons),findings_evaluated=len(rows))
        if len(json.dumps(out,allow_nan=False).encode())>512*1024:raise ValueError('bounded_native_fee_headroom_report_required')
    except (ValueError,TypeError,KeyError,OverflowError,OSError) as error:
        out.update(status='withheld',reason=str(error)[:160],findings=[],verified_fee_pairs=0,positive_formula_headroom_pairs=0)
    return out
