"""Explicit sensitivity assumptions never become qualified paper opportunities."""
from copy import deepcopy
from datetime import timedelta

from neraium_poly.research.phase28.findings import build_economic_findings
from neraium_poly.research.phase30.sensitivity import cost_sensitivity
from test_phase27_findings import NOW, inputs


def test_depth_cost_capital_stress_has_explicit_unknowns_and_no_authority():
    _s,_f,frame=inputs();book=frame.books[0]
    r=cost_sensitivity(book,as_of=NOW,probability=.6,lower=0.,upper=1.)
    assert not r['all_in_costs_verified'] and not r['execution_authorized']
    assert len(r['cases'])==3
    for case in r['cases']:
        assert not case['protocol_curve_source_verified'] and case['unverified_rounding_fragmentation']
        assert not case['all_in_costs_verified'] and not case['qualified_opportunity']
        assert [x['hypothetical_bankroll'] for x in case['hypothetical_capital_scenarios']]==[500,1000,10000,100000,1000000]
        assert case['maximum_lower_bound_estimate']['quantity']==0
        assert case['maximum_point_estimate']['quantity']<=sum(l.size*.1 for l in book.asks)+1e-9
        assert all(x['accounts_created']==0 for x in case['hypothetical_capital_scenarios'])
    assert r['cases'][0]['maximum_point_estimate']['expected_net_profit']>=r['cases'][-1]['maximum_point_estimate']['expected_net_profit']


def test_verified_native_curve_is_distinct_from_assumed_extra_costs():
    _s,f,frame=inputs();proof={'status':'verified_current_protocol_curve','rate':.04,'token_id':f['token_id']}
    r=cost_sensitivity(frame.books[0],as_of=NOW,probability=.6,lower=.55,upper=.65,native_fee=proof)
    assert all(c['protocol_curve_source_verified'] and c['effective_fee_surcharge_bound']==.04 for c in r['cases'])
    assert all(not c['all_in_costs_verified'] for c in r['cases'])
    wrong={**proof,'token_id':'CONTROLLED-WRONG'}
    assert not cost_sensitivity(frame.books[0],as_of=NOW,probability=.6,native_fee=wrong)['cases'][0]['protocol_curve_source_verified']


def test_only_current_hypotheses_receive_sensitivity_never_admission():
    s,f,frame=inputs();original=deepcopy(s)
    r=build_economic_findings([s],frame,as_of=NOW,verified_forecast_ids=[f['id']])['findings'][0]
    assert r['pipeline']['cost_sensitivity']['cases']
    assert not r['qualified_research'] and not r['shadow_eligible'] and r['scenario_expected_net_profit'] is None
    later=NOW+timedelta(seconds=301);b=frame.books[0].model_copy(update={'timestamp':later,'available_at':later})
    current=frame.model_copy(update={'timestamp':later,'available_at':later,'books':(b,)})
    old=build_economic_findings([s],current,as_of=later,verified_forecast_ids=[f['id']])['findings'][0]
    assert old['pipeline']['cost_sensitivity'] is None and not old['qualified_research']
    assert s==original
