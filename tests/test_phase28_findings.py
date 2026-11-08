"""Controlled economic fixtures, never genuine market/profit evidence."""
from copy import deepcopy
from datetime import timedelta

import pytest
from neraium_poly.research.phase14.relationships import digest
from neraium_poly.research.phase28.findings import build_economic_findings
from test_phase27_findings import NOW, costs, inputs


def proof(s, f, frame, **changes):
    bundle=costs(s,f,frame,fee=0,slippage=0,latency=0,lockup=0,settlement=0)
    e=bundle[f['id']]['evidence']
    e.update(cost_model='phase28-effective-total-costs-v1',effective_entry_fee_rate=0.,settlement_cost_per_share=0.,native_fee_verified=True,
             settlement_rule_compatibility_verified=True,unconditional_contract_value_verified=True)
    e.update(changes)
    return bundle


def report(s,f,frame,**kwargs):
    return build_economic_findings([s],frame,as_of=kwargs.pop('as_of',NOW),verified_forecast_ids=[f['id']],**kwargs)


def test_small_positive_margin_is_not_rejected_by_certified_three_cent_gate():
    s,f,frame=inputs();f.update(probability=.42,lower_probability=.415,upper_probability=.425)
    old=deepcopy(s);r=report(s,f,frame,fee_quotes=proof(s,f,frame));row=r['findings'][0]
    assert row['qualified_research'] and row['shadow_eligible']
    assert row['conservative_expected_net_profit']>0
    assert 0<f['lower_probability']-frame.books[0].asks[0].price<.03
    assert row['economics']['conservative_expected_net_profit']==pytest.approx(row['economics']['quantity']*.005)
    assert r['policy']['research_minimum_per_share_edge'] is None
    assert r['policy']['certified_minimum_edge_unchanged']==.03 and not row['execution_authorized']
    assert s==old


def test_unknown_costs_keep_positive_gross_scenario_but_no_net_or_qualification():
    s,f,frame=inputs();f.update(probability=.415,lower_probability=.412,upper_probability=.418)
    r=report(s,f,frame);row=r['findings'][0]
    assert row['scenario_expected_gross_profit']>0 and r['scenario_rankings']==[row['id']]
    assert row['scenario_expected_net_profit'] is None and row['conservative_expected_net_profit'] is None
    assert row['economic_rank'] is None and not row['shadow_eligible'] and r['rankings']==[]
    assert row['break_even_entry_fee_rate_before_other_costs']>0
    assert not r['validated_profitability'] and r['realized_simulated_pnl'] is None


@pytest.mark.parametrize('fault',['no_verifier','future_cost','wrong_book','raw_fee_only','uncalibrated','conditional','no_settlement','no_interval'])
def test_provenance_calibration_semantics_and_settlement_requirements_remain(fault):
    s,f,frame=inputs();bundle=proof(s,f,frame)
    if fault=='no_verifier':bundle[f['id']].pop('verifier')
    elif fault=='future_cost':bundle[f['id']]['evidence']['available_at']=(NOW+timedelta(seconds=1)).isoformat()
    elif fault=='wrong_book':bundle[f['id']]['evidence']['book_sha256']='b'*64
    elif fault=='raw_fee_only':bundle[f['id']]['evidence'].pop('effective_entry_fee_rate')
    elif fault=='uncalibrated':bundle[f['id']]['evidence']['calibration_verified']=False
    elif fault=='conditional':f['target_conditioning']='ordinary conditional event';bundle=proof(s,f,frame)
    elif fault=='no_settlement':bundle[f['id']]['evidence']['settlement_rule_compatibility_verified']=False
    else:f.pop('lower_probability');bundle=proof(s,f,frame)
    row=report(s,f,frame,fee_quotes=bundle)['findings'][0]
    assert not row['qualified_research'] and row['conservative_expected_net_profit'] is None
    assert not row['shadow_eligible'] and row['reasons']


def test_new_book_does_not_rejuvenate_old_forecast():
    s,f,frame=inputs();later=NOW+timedelta(seconds=301)
    b=frame.books[0].model_copy(update={'timestamp':later,'available_at':later})
    current=frame.model_copy(update={'timestamp':later,'available_at':later,'books':(b,)})
    row=report(s,f,current,as_of=later)['findings'][0]
    assert row['forecast_timestamp']==NOW.isoformat() and row['book_qualified_for_current_observation']
    assert row['execution_analysis'] is None and 'forecast_outside_frozen_300_second_decision_window' in row['reasons']


@pytest.mark.parametrize('fault',['rules','identity','stale','future_receipt','duplicate_price'])
def test_native_book_and_resolution_integrity_cannot_be_bypassed(fault):
    s,f,frame=inputs();raw=frame.model_dump(mode='json')
    if fault=='rules':raw['markets'][0]['resolution_rules']+=' changed'
    elif fault=='identity':raw['books'][0]['market_id']='CONTROLLED-wrong'
    elif fault=='stale':raw['books'][0]['timestamp']=(NOW-timedelta(seconds=16)).isoformat()
    elif fault=='future_receipt':raw['books'][0]['available_at']=(NOW+timedelta(seconds=1)).isoformat()
    else:raw['books'][0]['asks'].append(deepcopy(raw['books'][0]['asks'][0]))
    row=report(s,f,raw)['findings'][0]
    assert row['execution_analysis'] is None and not row['qualified_research']


def test_duplicate_models_cannot_multiply_shared_event_or_book_portfolio_capacity():
    s,f,frame=inputs();f2=deepcopy(f);f2['id']='CONTROLLED-second-model';f2['model_id']='CONTROLLED-alternative';s['forecasts'].append(f2)
    q={**proof(s,f,frame),**proof(s,f2,frame)}
    r=build_economic_findings([s],frame,as_of=NOW,verified_forecast_ids=[f['id'],f2['id']],fee_quotes=q)
    assert len(r['rankings'])==2 and len(r['portfolio']['survey_selection'])==1
    assert len(r['portfolio']['excluded'])==1 and r['portfolio']['portfolio_expected_profit'] is None


def test_expected_payout_keeps_conditional_scenario_separate_from_binary_probabilities():
    s,f,frame=inputs();f.update(probability=.419,expected_payout=.419,probability_semantics='expected_payout',
        outcome_probabilities={'up':.41,'tie':.018,'down':.572},original_target_conditioning='strict direction only',
        original_forecast_id='CONTROLLED-origin',original_forecast_sha256='a'*64,target_conditioning='ordinary session only')
    f['contract'].update(selected_outcome='Up',settlement_payouts={'up':1.,'tie':.5,'down':0.})
    row=report(s,f,frame)['findings'][0]
    assert row['forecast_probability'] is None and row['expected_payout']==pytest.approx(.419)
    assert row['scenario_expected_gross_profit']>0 and not row['qualified_research']
    assert row['valuation_scope']=='conditional_model_scenario'


def test_usd_profit_ranking_can_prefer_more_volume_over_larger_per_share_gap():
    s,f,frame=inputs('CONTROLLED-highgap');s2,f2,frame2=inputs('CONTROLLED-highvolume')
    f.update(probability=.6,lower_probability=.55,upper_probability=.65)
    f2.update(probability=.44,lower_probability=.43,upper_probability=.45)
    m=frame2.markets[0].model_copy(update={'market_id':'CONTROLLED-volume-market','token_id':'CONTROLLED-volume-token','event_id':'CONTROLLED-volume-event'})
    b=frame2.books[0].model_copy(update={'id':'CONTROLLED-volume-book','market_id':m.market_id,'token_id':m.token_id,
        'asks':tuple(x.model_copy(update={'size':10000}) for x in frame2.books[0].asks)})
    f2.update(market_id=m.market_id,token_id=m.token_id,event_id=m.event_id,market=m.model_dump(mode='json'),book=b.model_dump(mode='json'))
    f2['book_sha256']=digest(f2['book']);combined=frame.model_copy(update={'markets':(frame.markets[0],m),'books':(frame.books[0],b)})
    q={**proof(s,f,frame),**proof(s2,f2,combined.model_copy(update={'books':(b,)}))}
    r=build_economic_findings([s,s2],combined,as_of=NOW,verified_forecast_ids=[f['id'],f2['id']],fee_quotes=q)
    assert len(r['rankings'])==2
    first=next(row for row in r['findings'] if row['id']==r['rankings'][0])
    assert first['forecast_id']==f2['id']


def test_streamed_economics_merge_preserves_rows_without_duplicate_sample_or_capacity():
    from neraium_poly.research.phase28.findings import combine_economic_reports
    s,f,frame=inputs();r=report(s,f,frame,fee_quotes=proof(s,f,frame))
    merged=combine_economic_reports([r,r],as_of=NOW)
    assert merged['counts']['findings_evaluated']==1 and len(merged['rankings'])==1
    assert len(merged['portfolio']['survey_selection'])==1
    assert merged['realized_simulated_pnl'] is None
    wrong=deepcopy(r);wrong['findings'][0]['economics']['quantity']+=1
    with pytest.raises(ValueError,match='conflicting_streamed'):combine_economic_reports([r,wrong],as_of=NOW)


def test_streamed_batches_cannot_mix_times_or_frames():
    from neraium_poly.research.phase28.findings import combine_economic_reports
    s,f,frame=inputs();r=report(s,f,frame);wrong=deepcopy(r)
    wrong['as_of']=(NOW+timedelta(seconds=1)).isoformat()
    with pytest.raises(ValueError,match='identical_research_only'):combine_economic_reports([r,wrong],as_of=NOW)
    s2,f2,frame2=inputs('CONTROLLED-other');r2=report(s2,f2,frame2);r2['findings'][0]['frame_sha256']='CONTROLLED-different'
    with pytest.raises(ValueError,match='identical_economic_decision_frame'):combine_economic_reports([r,r2],as_of=NOW)


def test_high_conviction_requires_independent_support_not_only_narrow_model_interval():
    s,f,frame=inputs();f.update(probability=.42,lower_probability=.415,upper_probability=.425)
    row=report(s,f,frame,fee_quotes=proof(s,f,frame))['findings'][0]
    assert row['qualified_research'] and row['strategy_eligibility']==['small_edge']
    q=proof(s,f,frame,independent_evidence_convergence_verified=True,independent_evidence_lineages=['CONTROLLED-source-one','CONTROLLED-source-two'])
    row=report(s,f,frame,fee_quotes=q)['findings'][0]
    assert row['strategy_eligibility']==['small_edge','high_conviction']
    assert not row['execution_authorized']


def test_replayed_cost_evidence_preserved_without_callback_or_original_mutation():
    s,f,frame=inputs();q=proof(s,f,frame);old=deepcopy(q[f['id']]['evidence'])
    row=report(s,f,frame,fee_quotes=q)['findings'][0]
    assert row['cost_evidence']==old and row['fee_and_cost_evidence_sha256']==digest(old)
    assert q[f['id']]['evidence']==old and 'verifier' not in row['cost_evidence']
    q[f['id']]['evidence']['calibration_artifact_sha256']='x'*64
    assert not report(s,f,frame,fee_quotes=q)['findings'][0]['qualified_research']
