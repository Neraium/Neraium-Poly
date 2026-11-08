"""Controlled binary books, never authentic opportunity evidence."""
from datetime import timedelta

import pytest
from neraium_poly.research.phase32.pairs import pair_frontier, scan_pairs
from test_phase24_integration import NOW, inputs
from test_phase28_execution import book


def paired():
    y=book(((.40,100),(.44,100),(.60,100)),bids=[{'price':.39,'size':100}],token_id='YES')
    n=book(((.50,50),(.55,200)),bids=[{'price':.49,'size':100}],token_id='NO')
    # Helper book has its own test clock.
    return y,n,y.timestamp


def test_multilevel_pairs_consume_each_level_once_and_do_not_call_unknown_costs_zero():
    y,n,now=paired();r=pair_frontier(y,n,as_of=now,minimum_quantity=5)
    #5@.9,5@.95,10@.99; remaining asks fail paired grossbreak-even.
    assert r['maximum']['paired_shares']==pytest.approx(20)
    assert r['maximum']['conditional_gross_profit']==pytest.approx(.85)
    assert r['maximum']['acquisition_principal']==pytest.approx(19.15)
    assert r['maximum']['conservative_net_profit'] is None and not r['qualified']
    assert not r['trading_authority']


def test_subcent_gross_scenario_is_not_filtered_by_certified_threshold():
    y,n,now=paired();y=y.model_copy(update={'asks':(y.asks[0].model_copy(update={'price':.4995,'size':10000}),)})
    r=pair_frontier(y,n,as_of=now);assert r['maximum']['conditional_gross_profit']>0
    assert r['maximum']['conservative_net_profit'] is None


@pytest.mark.parametrize('fault',['stale','same_token','different_market','source','skew'])
def test_identity_freshness_and_simultaneity_fail_closed(fault):
    y,n,now=paired()
    changes={'stale':{'timestamp':now-timedelta(seconds=16),'available_at':now-timedelta(seconds=16)},
        'same_token':{'token_id':y.token_id},'different_market':{'market_id':'other'},'source':{'source':'CONTROLLED-untrusted'},
        'skew':{'timestamp':now-timedelta(seconds=3)}}
    with pytest.raises(ValueError):pair_frontier(y,n.model_copy(update=changes[fault]),as_of=now)


def test_capital_capacity_is_depth_limited_not_proportional_to_bankroll():
    y,n,now=paired();r=pair_frontier(y,n,as_of=now)
    assert len(r['capital_scenarios'])==5
    assert len({s['paired_shares'] for s in r['capital_scenarios']})==1
    assert r['capital_scenarios'][-1]['paired_shares']==r['maximum']['paired_shares']


def test_scan_quarantines_rule_mismatch_and_future_receipts():
    m,b,_e,_f,frame=inputs();yes=m.model_copy(update={'outcome':'YES'});no=m.model_copy(update={'outcome':'NO','token_id':'NO'})
    yn=b.model_copy(update={'token_id':'NO'});raw=frame.model_copy(update={'markets':(yes,no),'books':(b,yn)})
    r=scan_pairs(raw,as_of=NOW);assert r['paired_books_evaluated']==1
    no=no.model_copy(update={'resolution_rules':'OTHER'});r=scan_pairs(raw.model_copy(update={'markets':(yes,no)}),as_of=NOW)
    assert r['paired_books_evaluated']==0 and r['rejections']
    with pytest.raises(ValueError):scan_pairs(raw,as_of=NOW-timedelta(seconds=1))


@pytest.mark.parametrize("fault",["market","source"])
def test_both_books_wrong_market_or_nonofficial_metadata_cannot_be_joined(fault):
    m,b,_e,_f,frame=inputs()
    yes=m.model_copy(update={"outcome":"YES"});no=m.model_copy(update={"outcome":"NO","token_id":"NO"})
    other=b.model_copy(update={"token_id":"NO"})
    if fault=="market":b=b.model_copy(update={"market_id":"OTHER"});other=other.model_copy(update={"market_id":"OTHER"})
    else:yes=yes.model_copy(update={"source":"UNVERIFIED"});no=no.model_copy(update={"source":"UNVERIFIED"})
    r=scan_pairs(frame.model_copy(update={"markets":(yes,no),"books":(b,other)}),as_of=NOW)
    assert r["paired_books_evaluated"]==0 and r["rejections"]
