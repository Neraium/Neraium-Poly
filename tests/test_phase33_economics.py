"""Controlled fee/depth engineering cases; never actual profitable observations."""
from copy import deepcopy
from datetime import timedelta

import pytest
from neraium_poly.research.phase14.relationships import digest
from neraium_poly.research.phase32.pairs import scan_pairs
from neraium_poly.research.phase33.economics import annotate_pair_fees
from test_phase24_integration import NOW, inputs
from test_phase29_economics import Store


def sample(rate=.04):
    m,b,_e,_f,frame=inputs();yes=m.model_copy(update={'outcome':'YES','token_id':'Y','min_order_size':5})
    no=m.model_copy(update={'outcome':'NO','token_id':'N','min_order_size':5})
    y={**b.model_dump(),'token_id':'Y','bids':({'price':.39,'size':100},),'asks':({'price':.4,'size':100},{'price':.44,'size':100},{'price':.6,'size':100})}
    n={**b.model_dump(),'token_id':'N','bids':({'price':.49,'size':100},),'asks':({'price':.5,'size':50},{'price':.55,'size':200})}
    # Validate controlled level dictionaries rather than bypassing typed contracts.
    from neraium_poly.contracts import OrderBookSnapshot
    y=OrderBookSnapshot.model_validate(y);n=OrderBookSnapshot.model_validate(n)
    f=frame.model_copy(update={'markets':(yes,no),'books':(y,n)})
    records={};observations={};origin='https://clob.polymarket.com';stamp=NOW.isoformat()
    for token in ('Y','N'):
        parent={'condition_id':'C','primary_token_id':'Y','secondary_token_id':'N'}
        details={'c':'C','t':[{'t':'Y'},{'t':'N'}],'fd':{'r':rate,'e':1,'to':True}}
        refs=[]
        for i,(payload,path) in enumerate([(parent,'/markets-by-token/'+token),(details,'/clob-markets/C')]):
            key=token+str(i);refs.append(key)
            records[key]={'id':key,'source':origin,'timestamp':stamp,'available_at':stamp,'url':origin+path,'content_sha256':digest(payload),'payload':payload}
        oid=token+'-obs';records[oid]={'id':oid,'source':origin,'timestamp':stamp,'available_at':stamp,'token_id':token,'fee_rate':rate,'raw_response_ids':refs}
        observations[token]={'evidence_id':oid}
    return f,scan_pairs(f,as_of=NOW),observations,Store(records)


def run(f,report,observations,store,as_of=NOW):
    return annotate_pair_fees(report,f,observations,store,as_of=as_of)


def test_verified_fee_curve_reduces_economic_quantity_without_inventing_all_in_costs():
    f,r,o,s=sample();v=run(f,r,o,s);assert v['verified_fee_pairs']==1
    row=v['findings'][0];gross=row['gross_frontier'];best=row['maximum_formula_headroom']
    assert gross['paired_quantity']==20 and gross['conditional_gross_profit']==pytest.approx(.85)
    assert gross['formula_fee']==pytest.approx(.39306)
    assert best['paired_quantity']==10 and best['remaining_cost_budget_before_break_even']==pytest.approx(.5545)
    assert len(row['capital_scenarios'])==5 and len({x['paired_quantity'] for x in row['capital_scenarios']})==1
    assert row['conservative_expected_net_profit'] is None and not row['all_in_costs_verified']
    assert v['aggregate_net_profit'] is None and not v['trading_authority'] and not v['actual_fill']


def test_zero_verified_fees_preserve_small_edge_but_not_claim_zero_other_costs():
    f,r,o,s=sample(rate=0);v=run(f,r,o,s);best=v['findings'][0]['maximum_formula_headroom']
    assert best['paired_quantity']==20 and best['remaining_cost_budget_before_break_even']==pytest.approx(.85)
    assert best['conservative_expected_net_profit'] is None


@pytest.mark.parametrize('fault',['missing','wrong_token','future','stale','hash','condition'])
def test_fee_identity_time_integrity_and_same_native_condition_fail_closed(fault):
    f,r,o,s=sample()
    if fault=='missing':o.pop('N')
    elif fault=='wrong_token':s.records['N-obs']['token_id']='OTHER'
    elif fault=='future':s.records['N-obs']['timestamp']=s.records['N-obs']['available_at']=(NOW+timedelta(seconds=1)).isoformat()
    elif fault=='stale':s.records['N-obs']['timestamp']=s.records['N-obs']['available_at']=(NOW-timedelta(seconds=301)).isoformat()
    elif fault=='hash':s.records['N1']['content_sha256']='0'*64
    else:
        s.records['N0']['payload']['condition_id']='OTHER';s.records['N1']['payload']['c']='OTHER';s.records['N1']['url']='https://clob.polymarket.com/clob-markets/OTHER'
        for key in ('N0','N1'):s.records[key]['content_sha256']=digest(s.records[key]['payload'])
    v=run(f,r,o,s);assert v['verified_fee_pairs']==0 and v['findings'][0]['reason']
    assert v['positive_formula_headroom_pairs']==0 and v['conservative_expected_net_profit'] is None


@pytest.mark.parametrize('fault',['frame','decision','row_book'])
def test_costs_cannot_join_different_frame_or_future_cutoff(fault):
    f,r,o,s=sample()
    if fault=='frame':r['frame_sha256']='WRONG'
    elif fault=='row_book':r['findings'][0]['book_sha256'][0]='WRONG'
    v=run(f,r,o,s,as_of=NOW+timedelta(seconds=1) if fault=='decision' else NOW)
    assert not v['verified_fee_pairs'] and not v['trading_authority']


def test_duplicate_findings_cannot_consume_same_observed_liquidity_twice():
    f,r,o,s=sample();r['findings']+=deepcopy(r['findings'])
    v=run(f,r,o,s);assert v['verified_fee_pairs']==1 and v['findings'][1]['reason']=='pair_liquidity_already_enrolled_in_report'


def test_both_verified_fee_curves_can_eliminate_formula_headroom():
    f,r,o,s=sample(rate=1);v=run(f,r,o,s);best=v['findings'][0]['maximum_formula_headroom']
    assert best['paired_quantity']==0 and not v['positive_formula_headroom_pairs']
    assert v['findings'][0]['gross_frontier']['conditional_gross_profit']>0


@pytest.mark.parametrize('field,value',[('event_id','OTHER'),('rules_sha256','WRONG'),('settlement_reference','https://other.example/'),('end_time','2026-11-30T00:00:00Z')])
def test_pair_cost_cannot_relabel_the_exact_native_event_and_settlement(field,value):
    f,r,o,s=sample();r['findings'][0][field]=value
    v=run(f,r,o,s);assert v['verified_fee_pairs']==0
    assert v['findings'][0]['reason']=='exact_pair_event_and_settlement_metadata_required'


def test_conflicting_observations_for_same_native_condition_are_not_combined():
    f,r,o,s=sample();s.records['N1']['payload']['fd']['r']=.05;s.records['N1']['content_sha256']=digest(s.records['N1']['payload']);s.records['N-obs']['fee_rate']=.05
    v=run(f,r,o,s);assert v['verified_fee_pairs']==0
    assert v['findings'][0]['reason']=='native_shared_condition_fee_curve_disagreement'
