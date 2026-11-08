"""Controlled economic math fixtures; never genuine market opportunities."""
from datetime import UTC, datetime, timedelta

import pytest
from neraium_poly.contracts import OrderBookSnapshot
from neraium_poly.research.phase28.execution import analyze_depth

NOW = datetime(2026, 11, 8, 12, tzinfo=UTC)


def book(asks=((.5, 100), (.51, 100), (.7, 100)), **changes):
    raw={'id':'CONTROLLED-book','timestamp':NOW,'available_at':NOW,'source':'https://clob.polymarket.com',
         'market_id':'CONTROLLED-market','token_id':'CONTROLLED-token','bids':[{'price':.49,'size':200}],
         'asks':[{'price':p,'size':q} for p,q in asks]}
    raw.update(changes)
    return OrderBookSnapshot.model_validate(raw)


def analyze(b=None, **changes):
    values={'as_of':NOW,'expected_payout':.52,'lower_payout':.515,'upper_payout':.525,
            'fee_rate':0.,'settlement_cost_per_share':0.,'latency_liquidity_fraction':1.}
    values.update(changes)
    return analyze_depth(book() if b is None else b,**values)


def test_small_edges_walk_multiple_levels_and_optimize_dollars_without_three_cent_gate():
    r=analyze()
    assert r['status']=='conditional_assumption_scenarios'
    assert r['maximum_point_profit']['quantity']==200
    assert r['maximum_point_profit']['expected_net_profit']==pytest.approx(3)
    assert r['maximum_conservative_profit']['quantity']==200
    assert r['maximum_conservative_profit']['lower_net_profit']==pytest.approx(2)
    assert r['maximum_supported_quantity']==300
    assert r['per_level'][-1]['cumulative']['expected_net_profit']==pytest.approx(-15)
    assert not r['actual_fill'] and not r['trading_authority']


def test_subcent_edge_supported_at_realistic_volume_is_not_filtered():
    r=analyze(book(((.5, 10000),)),expected_payout=.5005,lower_payout=.5001,upper_payout=.501)
    assert r['maximum_point_profit']['quantity']==10000
    assert r['maximum_point_profit']['expected_net_profit']==pytest.approx(5)
    assert r['maximum_conservative_positive_net_profit']==pytest.approx(1)
    assert r['maximum_conservative_profit']['quantity']==10000


def test_positive_edge_below_numeric_dollar_tolerance_not_per_share_filtered():
    r=analyze(book(((.5, 10000),)),expected_payout=.5000000001,lower_payout=.5000000001)
    assert r['maximum_point_profit']['quantity']==10000
    assert r['maximum_point_profit']['expected_net_profit']>0


def test_quantity_is_partially_supported_by_capital_including_fees_and_reserves():
    r=analyze(book(((.5, 100),)),expected_payout=.8,lower_payout=.75,upper_payout=.9,
              fee_rate=.1,slippage_per_share=.01,settlement_cost_per_share=.04,max_capital=30)
    p=r['maximum_point_profit']
    assert p['quantity']==pytest.approx(50)
    assert p['principal']==pytest.approx(25)
    assert p['entry_fees']==pytest.approx(2.5)
    assert p['slippage_cost']==pytest.approx(.5)
    assert p['settlement_cost']==pytest.approx(2)
    assert p['capital_required']==pytest.approx(30)
    assert p['expected_gross_profit']==pytest.approx(15)
    assert p['expected_net_profit']==pytest.approx(10)
    assert p['lower_net_profit']==pytest.approx(7.5)
    assert p['upper_net_profit']==pytest.approx(15)
    assert p['return_on_capital']==pytest.approx(1/3)
    assert p['stopping_reason']=='capital_budget_exhausted'


def test_spread_is_not_deducted_twice_and_sweep_impact_is_reported():
    r=analyze(expected_payout=.8,lower_payout=.8,upper_payout=.8)
    p=r['maximum_point_profit']
    assert p['expected_net_profit']==pytest.approx(69)
    assert r['spread']==pytest.approx(.01)
    assert p['entry_vwap']==pytest.approx(171/300)
    assert p['sweep_impact_per_share']==pytest.approx(171/300-.5)


def test_known_fee_can_eliminate_all_point_profit_and_cash_is_preferred():
    r=analyze(book(((.5, 1000),)),expected_payout=.501,lower_payout=.5005,fee_rate=.01)
    assert r['maximum_point_profit']['quantity']==0
    assert r['maximum_point_profit']['expected_net_profit']==0
    assert r['maximum_conservative_positive_net_profit']==0


@pytest.mark.parametrize('missing',['fee_rate','settlement_cost_per_share'])
def test_missing_cost_is_unknown_not_free(missing):
    r=analyze(**{missing:None})
    assert r['maximum_supported']['expected_net_profit'] is None
    assert r['maximum_supported']['return_on_capital'] is None
    assert r['maximum_point_profit'] is None
    assert r['maximum_conservative_profit'] is None
    assert r['maximum_gross_profit']['expected_gross_profit']==pytest.approx(3)
    assert r['maximum_supported']['capital_required'] is None


def test_absolute_entry_fee_alternative_and_uncertainty_bounds():
    r=analyze(book(((.5, 100),)),expected_payout=.52,lower_payout=.51,upper_payout=.53,
              fee_rate=None,fee_per_share=.005)
    assert r['maximum_point_profit']['expected_net_profit']==pytest.approx(1.5)
    assert r['maximum_conservative_profit']['lower_net_profit']==pytest.approx(.5)
    assert r['maximum_point_profit']['net_profit_interval']==pytest.approx([.5,2.5])


def test_no_lower_bound_cannot_claim_conservative_net_profit():
    r=analyze(lower_payout=None)
    assert r['maximum_point_profit']['expected_net_profit']==pytest.approx(3)
    assert r['maximum_conservative_profit'] is None
    assert r['maximum_conservative_positive_net_profit'] is None


def test_liquidity_haircut_is_explicit_and_not_new_liquidity():
    r=analyze(latency_liquidity_fraction=.1)
    assert r['displayed_ask_quantity']==300
    assert r['participating_ask_quantity']==30
    assert r['maximum_point_profit']['quantity']==20
    assert r['maximum_point_profit']['expected_net_profit']==pytest.approx(.3)
    assert r['assumptions']['latency_liquidity_fraction']==.1


def test_capital_scenarios_do_not_scale_profit_beyond_depth():
    r=analyze(book(((.5, 2000),)),expected_payout=.6,lower_payout=.6,upper_payout=.7)
    rows=r['scenarios']
    assert [x['hypothetical_bankroll'] for x in rows]==[500,1000,10000,100000,1000000]
    assert [x['maximum_point_profit']['quantity'] for x in rows]==[1000,2000,2000,2000,2000]
    assert [x['maximum_point_profit']['expected_net_profit'] for x in rows]==pytest.approx([100,200,200,200,200])
    assert rows[-1]['capital_utilization']==pytest.approx(.001)
    assert rows[-1]['partial_capacity']


def test_empty_surviving_liquidity_is_not_a_position():
    r=analyze(latency_liquidity_fraction=0)
    assert r['maximum_supported_quantity']==0
    assert r['maximum_point_profit']['quantity']==0
    assert r['maximum_point_profit']['expected_net_profit']==0


@pytest.mark.parametrize('change',[
    {'expected_payout':float('nan')},{'expected_payout':True},{'lower_payout':.6},
    {'upper_payout':.4},{'fee_rate':-.01},{'fee_rate':float('inf')},
    {'fee_rate':.01,'fee_per_share':.001},{'settlement_cost_per_share':-.1},
    {'slippage_per_share':-.1},{'latency_liquidity_fraction':1.1},
    {'capitals':(500,500)},{'max_capital':0},
])
def test_invalid_assumptions_fail_closed(change):
    r=analyze(**change)
    assert r['status']=='withheld' and r['reasons'] and not r['scenarios']


@pytest.mark.parametrize('change',[
    {'timestamp':NOW-timedelta(seconds=16)},
    {'timestamp':NOW+timedelta(seconds=1),'available_at':NOW+timedelta(seconds=1)},
    {'complete':False},{'source':'CONTROLLED-untrusted'},
])
def test_non_executable_books_are_not_valued(change):
    r=analyze(book(**change))
    assert r['status']=='withheld' and r['maximum_supported'] is None


def test_duplicate_or_oversize_depth_cannot_double_count_capacity():
    assert analyze(book(((.5,100),(.5,100))))['status']=='withheld'
    raw=book().model_dump(mode='json');raw['asks']*=2000
    assert analyze(raw)['status']=='withheld'
    assert analyze(book(((.5,1e308),)))['status']=='withheld'


def test_wide_spread_is_economic_input_not_research_admission_threshold():
    r=analyze(book(((.7,100),)),expected_payout=.8,lower_payout=.79,upper_payout=.9)
    assert r['status']=='conditional_assumption_scenarios'
    assert r['maximum_conservative_profit']['lower_net_profit']==pytest.approx(9)


@pytest.mark.parametrize('field', ['id', 'market_id', 'token_id'])
def test_empty_native_identity_cannot_produce_research_valuation(field):
    r=analyze(book(**{field:''}))
    assert r['status']=='withheld' and r['maximum_supported'] is None
