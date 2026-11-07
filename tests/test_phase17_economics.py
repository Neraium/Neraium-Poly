"""Controlled fixtures; no synthetic economics are authentic research evidence."""

from copy import deepcopy
from datetime import datetime, timedelta

import pytest
from neraium_poly.research.phase14.relationships import digest
from neraium_poly.research.phase16.history import CausalHistory
from neraium_poly.research.phase17.diagnostics import summarize_rejections
from neraium_poly.research.phase17.economics import evaluate_roundtrip
from test_phase16_history import frame


def points(*, entry=.5, exit_=.5, lag=80):
    h = CausalHistory()
    f, at = frame(left=entry)
    f['markets'][0]['tick_size'] = .001
    decision = h.observe(f, now=at)['accepted'][0]
    f, at = frame(1, step=lag, left=exit_)
    f['markets'][0]['tick_size'] = .001
    label = h.observe(f, now=at)['accepted'][0]
    assert label['token_id'] == decision['token_id']
    return decision, label


def test_unchanged_midpoint_loses_spread_fees_and_slippage_without_fill_claim():
    d, label = points()
    result = evaluate_roundtrip(d, label)
    assert result['depth_supported'] and result['full_quantity_supported']
    assert result['entry_price'] == pytest.approx(.502)
    assert result['exit_price'] == pytest.approx(.498)
    assert result['gross_per_share'] == pytest.approx(-.004)
    assert result['fees_per_share'] == pytest.approx(.05)
    assert result['net_per_share'] == pytest.approx(-.074)
    assert result['net_total'] == pytest.approx(-.37)
    assert result['standard_notional_eligible']
    assert not result['execution_certified'] and not result['actual_fill'] and result['account_pnl'] is None
    assert not result['entry_post_latency_verified'] and not result['trading_authority']


def test_observed_positive_quote_change_is_still_hypothetical_not_edge_proof():
    d, label = points(exit_=.7)
    result = evaluate_roundtrip(d, label)
    assert result['net_per_share'] > 0
    assert not result['execution_certified'] and not result['certification_authority']
    assert result['provenance']['decision_point_sha256'] == digest(d)


@pytest.mark.parametrize('change,reason', [
    ({'token_id':'other'},'decision_label_identity_mismatch'),
    ({'rules_sha256':'b'*64},'decision_label_identity_mismatch'),
    ({'execution_evidence_complete':False},'qualified_source_depth_context_required'),
    ({'fee_rate':None},'fee_source_rate_or_cutoff_invalid'),
    ({'fee_evidence_sha256':'0'*64},'qualified_fee_provenance_required'),
    ({'source_frame_id':None},'point_identity_required'),
    ({'source':'https://fixture.invalid'},'qualified_source_depth_context_required'),
    ({'min_order_size':6},'causal_time_or_minimum_lot_invalid'),
    ({'asks':[]},'bounded_top3_levels_required'),
])
def test_missing_or_mismatched_evidence_withholds_economics(change, reason):
    d, label = points()
    label.update(change)
    result = evaluate_roundtrip(d, label)
    assert result['status']=='unexecutable' and result['net_per_share'] is None
    assert reason in result['reasons'][0]


def test_source_receipt_and_horizon_latency_are_not_interchangeable():
    d, label = points(lag=60)
    result = evaluate_roundtrip(d,label)
    assert 'post_latency' in result['reasons'][0]
    assert evaluate_roundtrip(d,label,latency_seconds=0)['depth_supported']
    d, label = points(lag=91)
    assert not evaluate_roundtrip(d,label)['depth_supported']
    d, label = points()
    label['available_at']=(datetime.fromisoformat(label['observed_at'])+timedelta(seconds=1)).isoformat()
    assert 'source_receipt_cutoff' in evaluate_roundtrip(d,label)['reasons'][0]
    d, label = points()
    label['source_at']=(datetime.fromisoformat(label['source_at'])-timedelta(seconds=16)).isoformat()
    assert 'stale' in evaluate_roundtrip(d,label)['reasons'][0]


def test_insufficient_depth_reports_partial_support_without_full_fill_or_net():
    d, label=points()
    label['bids'][0]['size']=10
    result=evaluate_roundtrip(d,label)
    assert result['exit_depth']['supported_quantity']==2.5
    assert result['exit_depth']['unsupported_quantity']==2.5
    assert result['net_per_share'] is None and not result['full_quantity_supported']


def test_deeper_sweep_does_not_claim_best_limit_fill_and_quantity_honors_minimum():
    d,label=points()
    d['asks']=[{'price':.502,'size':4},{'price':.51,'size':20}]
    result=evaluate_roundtrip(d,label)
    assert result['depth_supported'] and not result['best_limit_full_quantity_supported']
    assert result['entry_price'] > d['ask']
    assert result['entry_depth']['supported_quantity']==5
    d['min_order_size']=6
    assert not evaluate_roundtrip(d,label)['depth_supported']


@pytest.mark.parametrize('kwargs',[{'quantity':float('nan')},{'quantity':True},{'quantity':-1},
                                    {'fee_multiplier':float('inf')},{'slippage_per_leg':-.1},
                                    {'latency_seconds':float('nan')}])
def test_nonfinite_assumptions_never_become_zero_costs(kwargs):
    d,label=points()
    assert evaluate_roundtrip(d,label,**kwargs)['net_per_share'] is None


def test_duplicate_unsorted_and_mutated_fee_evidence_rejects():
    d,label=points()
    label['book_id']=d['book_id']
    assert 'duplicate' in evaluate_roundtrip(d,label)['reasons'][0]
    d,label=points();d['asks'].append(dict(d['asks'][0]))
    assert 'duplicate_depth' in evaluate_roundtrip(d,label)['reasons'][0]
    d,label=points();label['fee_observation']['fee_rate']=0
    assert 'fee_provenance' in evaluate_roundtrip(d,label)['reasons'][0]


def rejection_row():
    d,label=points();costs=evaluate_roundtrip(d,label)
    return {'id':'controlled-rejection','decision_at':costs['provenance']['decision_at'],
            'event_id':d['event_id'],'reasons':['conservative_roundtrip_edge_insufficient'],
            'costs':costs}


def test_rejection_counterfactual_default_deny_and_explicit_raw_replay():
    row=rejection_row();result=summarize_rejections([row])
    reason=result['reasons']['conservative_roundtrip_edge_insufficient']
    assert result['matched_modeled_cases']==0 and reason['mean_net_mark_per_share'] is None
    verified=summarize_rejections([row],verify_row=lambda _r:True)
    assert verified['negative_matched_modeled_cases']==1
    assert verified['reasons']['conservative_roundtrip_edge_insufficient']['mean_net_mark_per_share']==pytest.approx(-.074)
    assert verified['orders_proven_prevented_loss'] is None and not verified['threshold_change_authority']
    row['event_id']='wrong'
    assert summarize_rejections([row],verify_row=lambda _r:True)['matched_modeled_cases']==0


def test_diagnostics_counts_unique_ids_and_quarantines_conflicts():
    row=rejection_row();result=summarize_rejections([row,deepcopy(row)])
    assert result['exact_duplicate_rows']==1
    assert result['reasons'][row['reasons'][0]]['count']==1
    changed=deepcopy(row);changed['reasons'].append('kill_switch')
    result=summarize_rejections([row,changed],verify_row=lambda _r:True)
    assert result['ambiguous_ids_quarantined']==1 and result['matched_modeled_cases']==0
    assert not result['reasons']
    assert summarize_rejections([{'id':'invalid','reasons':[]}])['exact_duplicate_rows']==0


def test_verifier_failure_and_row_limit_fail_closed():
    def fail(_row):raise OSError('controlled unavailable raw archive')
    result=summarize_rejections([rejection_row()],verify_row=fail)
    assert result['counterfactual_unavailable']['source_replay_failed']==1
    with pytest.raises(ValueError,match='limit'):
        summarize_rejections([{}]*10001)


def test_future_fee_available_time_zero_minimum_and_off_tick_prices_reject():
    d,label=points()
    label['fee_observation']['available_at']=(datetime.fromisoformat(label['observed_at'])+timedelta(seconds=1)).isoformat()
    label['fee_evidence_sha256']=digest(label['fee_observation'])
    assert 'future_fee_availability' in evaluate_roundtrip(d,label)['reasons'][0]
    d,label=points();d['min_order_size']=0
    assert 'minimum_lot' in evaluate_roundtrip(d,label)['reasons'][0]
    d,label=points();d['asks'][0]['price']=d['ask']=.5025
    assert 'off_tick' in evaluate_roundtrip(d,label)['reasons'][0]
