"""Controlled findings fixtures: not genuine forecasts, prices or profit evidence."""
from copy import deepcopy
from datetime import timedelta

import pytest
from neraium_poly.contracts import MarketSnapshot
from neraium_poly.experimental.contracts import SharedMarketFrame
from neraium_poly.research.phase14.relationships import digest
from neraium_poly.research.phase27.findings import build_findings
from test_phase25_competition import END, NOW, fixture


def inputs(identity='controlled', model='baseline'):
    s, f = fixture(identity, model=model)
    f['target_conditioning'] = None
    f['lower_probability'] = .55
    f['upper_probability'] = .65
    m = MarketSnapshot(id='controlled-market', timestamp=NOW, available_at=NOW,
        source='https://gamma-api.polymarket.com', market_id=f['market_id'], event_id=f['event_id'],
        token_id=f['token_id'], question='CONTROLLED exact final game question', probability=.405,
        status='active', resolution_rules=f['market']['resolution_rules'],
        resolution_source=f['market']['resolution_source'], end_time=END, min_order_size=5)
    f['market'] = m.model_dump(mode='json')
    frame = SharedMarketFrame(id='controlled-frame', timestamp=NOW, available_at=NOW,
        source='CONTROLLED_fixture', markets=(m,), books=(f['book'],))
    return s, f, frame


def costs(s, f, frame, when=NOW, *, fee=.01, slippage=.005, latency=.005, lockup=.005, settlement=.005):
    book = frame.books[0]
    return {f['id']: {'evidence': {'forecast_id': f['id'], 'book_sha256': digest(book.model_dump(mode='json')),
        'original_forecast_sha256': digest(f), 'original_study_sha256': digest(s), 'decision_at': when.isoformat(),
        'available_at': NOW.isoformat(), 'calibration_cutoff': NOW.isoformat(),
        'calibration_artifact_sha256': 'c'*64, 'calibration_verified': True,
        'event_disjoint_calibration_verified': True, 'fee_rate': fee,
        'slippage_per_share': slippage, 'latency_adverse_selection_per_share': latency,
        'capital_lockup_cost_per_share': lockup, 'settlement_risk_cost_per_share': settlement},
        'verifier': lambda *args, **kwargs: {'verified': True}}}


def report(s, f, frame, **kwargs):
    return build_findings([s], frame, as_of=kwargs.pop('as_of', NOW),
                          verified_forecast_ids=[f['id']], **kwargs)


def test_no_cost_or_calibration_replay_never_becomes_executable_ev_or_rank():
    s, f, frame = inputs()
    row = report(s, f, frame)['findings'][0]
    assert row['gross_probability_gap_to_ask'] == pytest.approx(.19)
    assert row['estimated_after_cost_edge'] is None and row['finding_rank'] is None
    assert row['capacity']['status'] == 'liquidity_only_unqualified'
    assert row['capacity']['expected_capital_lockup_seconds'] is None
    assert 'independent_exact_calibration_and_cost_replay_required' in row['reasons']
    assert row['status'] == 'withheld' and not row['trading_authority']


def test_depth_aware_cost_adjusted_rank_is_research_only_and_originals_are_unchanged():
    s, f, frame = inputs(); before = deepcopy(s)
    r = report(s, f, frame, fee_quotes=costs(s, f, frame)); row = r['findings'][0]
    assert row['estimated_after_cost_edge'] == pytest.approx(.55*.99-.41*1.01-.02)
    probe = row['standard_probe']
    assert probe['supported_shares'] == 10 and probe['entry_principal_usd'] == pytest.approx(4.1)
    assert probe['conservative_expected_net_value_usd'] == pytest.approx(10*(.55*.99-.41*1.01-.02))
    assert probe['modeled_total_cost_usd'] <= 5 and probe['partial_budget_support']
    assert row['finding_rank'] == 1 and r['rankings'] == [row['id']]
    assert all(x['scenario_demand_is_order_authorized'] is False for x in row['capacity']['scenarios'])
    assert [x['hypothetical_bankroll'] for x in row['capacity']['scenarios']] == [500, 1000, 10000, 100000, 1000000]
    assert not row['execution_authorized'] and r['realized_simulated_pnl'] is None and r['drawdown'] is None
    assert s == before


def test_new_native_book_is_separate_decision_and_cannot_redate_old_forecast():
    s, f, frame = inputs(); later = NOW+timedelta(seconds=301)
    b = frame.books[0].model_copy(update={'id': 'controlled-new-book', 'timestamp': later, 'available_at': later})
    current = frame.model_copy(update={'timestamp': later, 'available_at': later, 'books': (b,)})
    row = report(s, f, current, as_of=later)['findings'][0]
    assert row['forecast_timestamp'] == NOW.isoformat() and row['book_id'] == b.id
    assert row['book_qualified_for_current_observation'] and row['executable_ask'] == .41
    assert row['gross_probability_gap_to_ask'] is None and row['finding_rank'] is None
    assert 'forecast_outside_frozen_300_second_decision_window' in row['reasons']


@pytest.mark.parametrize('fault', ['stale', 'future_receipt', 'wrong_token', 'wrong_market', 'changed_rules', 'book_source', 'duplicate_price'])
def test_stale_or_wrong_public_identity_is_withheld(fault):
    s, f, frame = inputs(); raw = frame.model_dump(mode='json')
    if fault == 'stale':raw['books'][0]['timestamp'] = (NOW-timedelta(seconds=16)).isoformat()
    elif fault == 'future_receipt':raw['books'][0]['available_at'] = (NOW+timedelta(seconds=1)).isoformat()
    elif fault == 'wrong_token':raw['books'][0]['token_id'] = 'other-token'
    elif fault == 'wrong_market':raw['books'][0]['market_id'] = 'other-market'
    elif fault == 'changed_rules':raw['markets'][0]['resolution_rules'] += ' changed'
    elif fault == 'book_source':raw['books'][0]['source'] = 'CONTROLLED_untrusted'
    else:raw['books'][0]['asks'].append(deepcopy(raw['books'][0]['asks'][0]))
    row = report(s, f, raw)['findings'][0]
    assert row['estimated_after_cost_edge'] is None and row['finding_rank'] is None
    assert row['executable_ask'] is None and row['reasons']


def test_recorded_verified_flags_do_not_replace_caller_original_replay():
    s, f, frame = inputs(); f['verified'] = True
    r = build_findings([s], frame, as_of=NOW)
    assert 'independent_original_source_model_replay_required' in r['findings'][0]['reasons']
    assert r['findings'][0]['gross_probability_gap_to_ask'] is None


@pytest.mark.parametrize('fault', ['no_verifier', 'recorded_flag', 'wrong_original', 'wrong_decision', 'future_cost', 'late_calibration', 'uncalibrated'])
def test_independently_replayed_exact_costs_and_calibration_are_mandatory(fault):
    s, f, frame = inputs(); native = costs(s, f, frame); bundle = native[f['id']]
    if fault == 'no_verifier':bundle.pop('verifier')
    elif fault == 'recorded_flag':bundle['verifier'] = {'verified': True}
    elif fault == 'wrong_original':bundle['evidence']['original_forecast_sha256'] = 'b'*64
    elif fault == 'wrong_decision':bundle['evidence']['decision_at'] = (NOW+timedelta(seconds=1)).isoformat()
    elif fault == 'future_cost':bundle['evidence']['available_at'] = (NOW+timedelta(seconds=1)).isoformat()
    elif fault == 'late_calibration':bundle['evidence']['calibration_cutoff'] = (NOW+timedelta(seconds=1)).isoformat()
    else:bundle['evidence']['calibration_verified'] = False
    row = report(s, f, frame, fee_quotes=native)['findings'][0]
    assert row['finding_rank'] is None and row['estimated_after_cost_edge'] is None


def test_negative_after_cost_edge_is_preserved_without_rank():
    s, f, frame = inputs(); f['lower_probability'] = .42
    row = report(s, f, frame, fee_quotes=costs(s, f, frame))['findings'][0]
    assert row['estimated_after_cost_edge'] < 0 and row['finding_rank'] is None
    assert row['standard_probe'] is None


def test_rank_uses_standard_probe_economic_value_not_probability_gap():
    a, f, frame = inputs('controlled-A', 'A'); b, g, _ = inputs('controlled-B', 'B')
    f['probability'] = .8; f['lower_probability'] = .5; f['upper_probability'] = .9
    g['probability'] = .6; g['lower_probability'] = .59; g['upper_probability'] = .7
    quotes = {**costs(a, f, frame), **costs(b, g, frame)}
    r = build_findings([a, b], frame, as_of=NOW, verified_forecast_ids=[f['id'], g['id']], fee_quotes=quotes)
    first = next(row for row in r['findings'] if row['finding_rank'] == 1)
    assert first['forecast_id'] == g['id'] and first['gross_probability_gap_to_ask'] < .39
    assert r['portfolio']['allocation'] is None
    assert r['comparisons'][0]['independent_confirmation_count'] is None


def test_current_frame_duplicates_and_future_frame_fail_closed():
    s, f, frame = inputs(); raw = frame.model_dump(mode='json'); other = deepcopy(raw['books'][0]); other['id'] = 'different'
    raw['books'].append(other)
    assert 'ambiguous_or_oversize_current_token_observation' in report(s, f, raw)['findings'][0]['reasons']
    with pytest.raises(ValueError, match='fresh_causal_market_frame'):
        report(s, f, frame, as_of=NOW-timedelta(seconds=1))


def test_same_model_event_disagreement_and_relationship_flags_never_create_authority():
    s, f, frame = inputs(); rel={'id':'r','timestamp':NOW.isoformat(),'available_at':NOW.isoformat(),
        'source':'CONTROLLED','market_ids':['market','other-market'],'kind':'mutually_exclusive','rule_verified':True}
    ev={'relationship_id':'r','timestamp':NOW.isoformat(),'available_at':NOW.isoformat(),'qualified':True,'persistence':100}
    raw=frame.model_dump(mode='json');raw['relationships']=[rel];raw['evidence']=[ev]
    r=report(s,f,raw);row=r['findings'][0]
    assert row['relationship_context'][0]['persistence']==100
    assert not row['relationship_context'][0]['independently_replayed']
    assert not r['sii']['qualified_pairs'] and r['sii']['incremental_value'] is None
    assert row['finding_rank'] is None


def test_fresh_expected_payout_is_not_a_binary_probability_or_executable_edge():
    s, f, frame = inputs(); f.update(probability_semantics='expected_payout', probability=.65,
        expected_payout=.65,outcome_probabilities={'up':.6,'tie':.1,'down':.3},
        original_forecast_id='controlled-original',original_forecast_sha256='c'*64,
        original_target_conditioning='original-completed-session',target_conditioning='ordinary-session-only',
        unconditional_contract_probability=False)
    f['contract']['selected_outcome']='Up';f['contract']['settlement_payouts']={'up':1,'tie':.5,'down':0}
    row=report(s,f,frame)['findings'][0]
    assert row['forecast_probability'] is None and row['expected_payout']==.65
    assert row['gross_modeled_payout_gap_to_ask']==pytest.approx(.24)
    assert row['gross_probability_gap_to_ask'] is None and row['estimated_after_cost_edge'] is None
    assert row['finding_rank'] is None
    assert 'native_reference_and_fallback_compatibility_not_independently_validated' in row['reasons']


def test_malformed_payout_or_missing_original_conditioning_never_displays_gap():
    s,f,frame=inputs();f.update(probability_semantics='expected_payout',probability=.9,expected_payout=.9,
        outcome_probabilities={'up':.6,'tie':.1,'down':.3},original_forecast_id='controlled-original',
        original_forecast_sha256='c'*64,target_conditioning='ordinary-session-only');f['contract']['selected_outcome']='Up';f['contract']['settlement_payouts']={'up':1,'tie':.5,'down':0}
    row=report(s,f,frame)['findings'][0]
    assert row['gross_modeled_payout_gap_to_ask'] is None


def test_report_output_budget_rejects_unbounded_metadata_without_partial_publication():
    s, f, frame = inputs()
    f['evidence_ids'] = ['CONTROLLED_oversize_evidence_'+'a'*(8*1024**2)]
    with pytest.raises(ValueError, match='bounded_findings_report_byte_budget'):
        report(s, f, frame)


def test_explicit_degraded_producer_is_not_overridden_by_fresh_book():
    s, f, frame = inputs()
    frame = frame.model_copy(update={'producer_health': {'status': 'degraded'}})
    with pytest.raises(ValueError, match='producer_health_not_qualified'):
        report(s, f, frame)


def test_malformed_expected_payout_mapping_is_suppressed():
    s, f, frame = inputs(); f['probability_semantics'] = 'expected_payout'; f['outcome_probabilities'] = None
    row = report(s, f, frame)['findings'][0]
    assert row['expected_payout'] is None and row['gross_modeled_payout_gap_to_ask'] is None


def test_utc_decision_binding_accepts_equivalent_native_z_timestamp():
    s, f, frame = inputs(); native = costs(s, f, frame)
    native[f['id']]['evidence']['decision_at'] = NOW.isoformat().replace('+00:00', 'Z')
    row = report(s, f, frame, fee_quotes=native)['findings'][0]
    assert row['status'] == 'qualified_research_diagnostic' and not row['execution_authorized']


def test_same_token_with_changed_outcome_label_is_quarantined():
    s, f, frame = inputs(); m = frame.markets[0].model_copy(update={'outcome': 'NO'})
    row = report(s, f, frame.model_copy(update={'markets': (m,)}))['findings'][0]
    assert 'current_market_or_resolution_identity_changed' in row['reasons'] and row['executable_ask'] is None


def test_empty_resolution_rules_do_not_count_as_clear_settlement():
    import hashlib
    s, f, frame = inputs(); f['market']['resolution_rules'] = ''; f['rules_sha256'] = hashlib.sha256(b'').hexdigest()
    m = frame.markets[0].model_copy(update={'resolution_rules': ''})
    row = report(s, f, frame.model_copy(update={'markets': (m,)}))['findings'][0]
    assert 'current_market_or_resolution_identity_changed' in row['reasons']
