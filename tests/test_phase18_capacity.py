"""Controlled fixtures only: no fixture probabilities, results or depth are live evidence."""

from copy import deepcopy
from datetime import timedelta
from hashlib import sha256

import pytest
from neraium_poly.contracts import PriceLevel
from neraium_poly.research.phase14.relationships import digest
from neraium_poly.research.phase18.capacity import capacity_scenarios
from neraium_poly.research.phase18.convergence import qualify_convergence


def controlled(market, book, now):
    m = market.model_copy(update={'source':'https://gamma-api.polymarket.com',
        'end_time':now+timedelta(days=1), 'min_order_size':5, 'resolution_rules':'CONTROLLED exact settlement rules',
        'resolution_source':'https://official.example.invalid/result'})
    b = book.model_copy(update={'source':'https://clob.polymarket.com',
        'bids':(PriceLevel(price=.39,size=10000),),'asks':(PriceLevel(price=.4,size=10000),)})
    evidence=[]
    for i in range(2):
        payload={'supported_event_id':m.event_id,'independence':{'source_group':f'CONTROLLED-{i}',
            'upstream_groups':[f'CONTROLLED-upstream-{i}'],'reviewed':True,'proof_sha256':'b'*64}}
        evidence.append({'id':f'CONTROLLED-evidence-{i}','timestamp':now.isoformat(),'available_at':now.isoformat(),
            'retrieved_at':now.isoformat(),'source_timestamp':now.isoformat(),
            'source':f'https://controlled-provider-{i}.example.invalid','provider':f'CONTROLLED-{i}',
            'source_id':f'CONTROLLED-source-{i}','domain':'crypto',
            'payload':payload,'content_sha256':digest(payload),'qualification':'qualified_research',
            'independent_of_polymarket':True})
    f={'id':'CONTROLLED-forecast','event_id':m.event_id,'market_id':m.market_id,'token_id':m.token_id,
       'rules_sha256':sha256(m.resolution_rules.encode()).hexdigest(),'probability_semantics':'binary_event_probability',
       'model_version':'CONTROLLED-v1','feature_version':'CONTROLLED-features-v1',
       'model_sha256':'c'*64,'dataset_sha256':'d'*64,'probability':.8,'uncertainty':{'lower_probability':.75,'upper_probability':.85},
       'timestamp':now.isoformat(),'available_at':now.isoformat(),'evidence_cutoff':now.isoformat(),
       'evidence_ids':[e['id'] for e in evidence],'calibration_status':'independently_validated',
       'independent_of_polymarket':True,'research_only':True}
    ctx={'fee_observation':{'fee_rate':.05,'observed_at':now.isoformat(),'source':'https://clob.polymarket.com',
                          'reference':'CONTROLLED reference'},
         'paper_trading':True,'live_trading_enabled':False,'emergency_stop':False,
         'experimental_admission_authorized':True,'terminal_execution_authorized':True,'risk_approved':True,
         'approved_notional':15.75,'remaining_aggregate_notional':100,'remaining_market_notional':25,'remaining_event_notional':50,'remaining_correlation_notional':50,
         'cash':500,'initial_bankroll':500,'aggregate_exposure_fraction':.2}
    for key in ['verify_evidence','verify_forecast','verify_rules','verify_fee','verify_risk','verify_admission','verify_independence','verify_proposal']:
        ctx[key]=lambda *_args:True  # CONTROLLED fixture callbacks; never authentic source proof.
    return f,m,b,evidence,ctx


def test_default_context_cannot_admit_or_fabricate_qualified_edge(market,book,now):
    f,m,b,e,_ctx=controlled(market,book,now)
    r=qualify_convergence(f,m,b,e,now=now)
    assert not r['research_qualified'] and not r['eligible'] and not r['trading_authority']
    assert r['estimated_net_edge'] is None and r['qualified_net_edge'] is None
    assert r['approaches']['high_throughput']['proposed_notional'] is None
    assert 'explicit_existing_risk_approval_required' in r['reasons']
    assert 'independent_dependency_review_required' in r['reasons']


def test_complete_controlled_prerequisites_only_propose_bounded_research(market,book,now):
    f,m,b,e,ctx=controlled(market,book,now)
    r=qualify_convergence(f,m,b,e,now=now,risk_context=ctx)
    assert r['research_qualified'] and r['qualified_net_edge']==pytest.approx(.2725)
    assert r['approaches']['high_throughput']['proposed_notional']==2
    assert r['approaches']['high_conviction']['proposed_notional']==5
    assert r['approaches']['high_conviction']['tier']=='high'
    assert not r['eligible'] and not r['trading_authority'] and not r['certification_authority']
    assert not r['order_attempted'] and r['account_pnl'] is None


@pytest.mark.parametrize('kind',['same_group','shared_upstream','duplicate_evidence','unreviewed','wrong_event'])
def test_provider_diversity_does_not_establish_independence(market,book,now,kind):
    f,m,b,e,ctx=controlled(market,book,now)
    if kind=='same_group':e[1]['payload']['independence']['source_group']=e[0]['payload']['independence']['source_group']
    elif kind=='shared_upstream':e[1]['payload']['independence']['upstream_groups']=e[0]['payload']['independence']['upstream_groups']
    elif kind=='duplicate_evidence':e[1]['id']=e[0]['id']
    elif kind=='unreviewed':e[1]['payload']['independence']['reviewed']=False
    else:e[1]['payload']['supported_event_id']='different-event'
    for row in e:row['content_sha256']=digest(row['payload'])
    r=qualify_convergence(f,m,b,e,now=now,risk_context=ctx)
    assert not r['research_qualified'] and r['qualified_net_edge'] is None


@pytest.mark.parametrize('kind',['unqualified','future','corrupt','price_only','rules','stale','no_fee_proof','risk','stop','cash','uncertainty'])
def test_integrity_and_operational_checks_fail_closed(market,book,now,kind):
    f,m,b,e,ctx=controlled(market,book,now)
    if kind=='unqualified':f['calibration_status']='uncalibrated_research'
    elif kind=='future':e[0]['available_at']=(now+timedelta(seconds=1)).isoformat()
    elif kind=='corrupt':e[0]['content_sha256']='0'*64
    elif kind=='price_only':f['independent_of_polymarket']=False
    elif kind=='rules':f['rules_sha256']='0'*64
    elif kind=='stale':b=b.model_copy(update={'timestamp':now-timedelta(seconds=16)})
    elif kind=='no_fee_proof':ctx.pop('verify_fee')
    elif kind=='risk':ctx['risk_approved']=False
    elif kind=='stop':ctx['emergency_stop']=True
    elif kind=='cash':ctx['remaining_correlation_notional']=1
    else:f['uncertainty']['upper_probability']=1;f['uncertainty']['lower_probability']=.1
    r=qualify_convergence(f,m,b,e,now=now,risk_context=ctx)
    assert not r['research_qualified'] and not r['eligible'] and r['qualified_net_edge'] is None


def test_missing_or_bad_inputs_have_rejected_decisions_for_both_approaches(market,book,now):
    for f in [{},{'uncertainty':'bad','timestamp':'invalid'}]:
        r=qualify_convergence(f,market,book,[],now=now)
        assert set(r['approaches'])=={'high_throughput','high_conviction'}
        assert all(not x['research_qualified'] for x in r['approaches'].values())


def test_capacity_is_finite_nonlinear_and_has_no_account_performance(market,book,now):
    f,m,b,e,ctx=controlled(market,book,now)
    b=b.model_copy(update={'asks':(PriceLevel(price=.4,size=1000),PriceLevel(price=.7,size=1000))})
    op=qualify_convergence(f,m,b,e,now=now,risk_context=ctx)
    r=capacity_scenarios(op,b)
    assert r['status']=='qualified_research_capacity' and len(r['scenarios'])==5
    assert r['edge_disappearance_observed'] is True
    assert r['edge_supported_shares']==100
    assert all(row['supported_shares']<=100 for row in r['scenarios'])
    assert r['scenarios'][-1]['partial_depth'] and r['scenarios'][-1]['unsupported_shares']>100000
    assert r['approved_tier_notional_caps']=={'standard':5,'high':15,'exceptional':25}
    assert r['net_pnl'] is None and r['net_return'] is None and r['drawdown'] is None
    assert not r['actual_fill'] and r['accounts_created']==0 and not r['entry_after_latency_verified']


def test_unqualified_forecast_still_has_honest_liquidity_only_profile(market,book,now):
    f,m,b,e,_ctx=controlled(market,book,now);op=qualify_convergence(f,m,b,e,now=now)
    r=capacity_scenarios(op,b)
    assert r['status']=='liquidity_only_unqualified'
    assert r['edge_supported_notional'] is None and r['edge_supported_shares'] is None
    assert all(x['conditional_expected_net_value'] is None for x in r['scenarios'])
    assert all(x['modeled_entry_notional']<=x['hypothetical_bankroll']*.1+1e-8 for x in r['scenarios'])


def test_exact_book_binding_stale_data_and_crowding(market,book,now):
    f,m,b,e,ctx=controlled(market,book,now);op=qualify_convergence(f,m,b,e,now=now,risk_context=ctx)
    changed=b.model_copy(update={'id':'different-source-book'})
    assert capacity_scenarios(op,changed)['status']=='withheld'
    stale=deepcopy(op);stale['evaluated_at']=(now+timedelta(seconds=16)).isoformat()
    assert capacity_scenarios(stale,b)['status']=='withheld'
    crowded=deepcopy(op);crowded['already_committed_shares']=999
    r=capacity_scenarios(crowded,b)
    assert r['total_observed_ask_participating_shares']==1
    assert not r['scenarios'][0]['minimum_lot_supported']
    assert r['scenarios'][0]['conditional_expected_net_value'] is None


@pytest.mark.parametrize('bankrolls',[(True,),(500,500),(float('inf'),),(),(0,)])
def test_invalid_capital_scenarios_cannot_create_orders(market,book,now,bankrolls):
    f,m,b,e,ctx=controlled(market,book,now);op=qualify_convergence(f,m,b,e,now=now,risk_context=ctx)
    r=capacity_scenarios(op,b,bankrolls=bankrolls)
    assert r['status']=='withheld' and r['scenarios']==[] and not r['trading_authority']


def test_current_capital_and_exact_proposal_approval_are_not_scaled(market,book,now):
    f,m,b,e,ctx=controlled(market,book,now)
    ctx['approved_notional']=2.1
    r=qualify_convergence(f,m,b,e,now=now,risk_context=ctx)
    assert r['approaches']['high_throughput']['research_qualified']
    assert not r['approaches']['high_conviction']['research_qualified']
    ctx['initial_bankroll']=1000000
    assert not qualify_convergence(f,m,b,e,now=now,risk_context=ctx)['research_qualified']
    ctx['initial_bankroll']=500;ctx['remaining_market_notional']=1
    assert not qualify_convergence(f,m,b,e,now=now,risk_context=ctx)['research_qualified']


def test_missing_model_version_or_calibration_verifier_cannot_qualify(market,book,now):
    f,m,b,e,ctx=controlled(market,book,now)
    f.pop('model_sha256')
    assert not qualify_convergence(f,m,b,e,now=now,risk_context=ctx)['research_qualified']


def test_duplicate_depth_is_not_double_counted_as_capacity(market,book,now):
    f,m,b,e,ctx=controlled(market,book,now)
    bad=b.model_copy(update={'asks':(b.asks[0],b.asks[0])})
    r=qualify_convergence(f,m,bad,e,now=now,risk_context=ctx)
    assert not r['research_qualified'] and 'bounded_unique_order_book_levels_required' in r['reasons']
    assert capacity_scenarios(r,bad)['status']=='withheld'
