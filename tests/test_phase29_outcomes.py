"""Isolated outcome-diagnostic fixtures, never authentic settled event evidence."""
from copy import deepcopy
from datetime import timedelta
from types import SimpleNamespace

import pytest
from neraium_poly.data import EventStore
from neraium_poly.research.phase24.continuous import DomainResearch
from neraium_poly.research.phase24.outcomes import DomainOutcomes
from neraium_poly.research.phase29.outcomes import (
    maturity_report,
    native_resolution_diagnostics,
    outcome_reasons,
)
from test_phase24_integration import NOW, adapter, inputs


def entry(*, identity='controlled', domain='crypto', end=None):
    end = end or NOW + timedelta(hours=2)
    return {'type': 'forecast', 'replay_verified': True, 'available_at': NOW.isoformat(),
            'forecast': {'id': identity, 'domain': domain, 'event_id': 'controlled-parent',
                'timestamp': NOW.isoformat(), 'evidence_cutoff': NOW.isoformat(), 'event_end_time': end.isoformat()}}


def test_nominal_maturity_does_not_infer_outcome_or_event_independence():
    rows = [entry(), entry(identity='second-model'), entry(identity='sports', domain='sports')]
    r = maturity_report(rows, as_of=NOW + timedelta(hours=2, minutes=30))
    assert r['counts']['forecasts'] == 3 and r['counts']['nominal_event_boundary_passed'] == 3
    assert r['counts']['verification_due_forecasts'] == 2  # sports delay does not establish a final result
    assert r['native_parent_groups'] == 2 and r['verification_due_native_parent_groups'] == 1
    assert r['independently_verified_outcomes'] is None and r['certified_independent_events'] is None
    assert not r['trading_authority'] and not r['certification_authority']


@pytest.mark.parametrize('fault', ['future_receipt', 'naive_clock', 'post_event_forecast', 'unverified_source'])
def test_temporally_unqualified_forecasts_do_not_enter_readiness_counts(fault):
    row = entry()
    if fault == 'future_receipt':
        row['available_at'] = (NOW + timedelta(days=5)).isoformat()
    elif fault == 'naive_clock':
        row['forecast']['timestamp'] = '2026-11-07T23:00:00'
    elif fault == 'post_event_forecast':
        row['forecast']['event_end_time'] = (NOW - timedelta(seconds=1)).isoformat()
    else:
        row['replay_verified'] = False
    r = maturity_report([row], as_of=NOW + timedelta(days=1))
    assert r['counts']['forecasts'] == 0 and r['rejections']['original_prospective_metadata_unqualified'] == 1


def test_duplicate_forecasts_cannot_inflate_sample_size_and_conflicts_quarantine():
    one = entry(); two = deepcopy(one)
    r = maturity_report([one, two], as_of=NOW + timedelta(days=1))
    assert r['counts']['forecasts'] == 1
    two['forecast']['event_id'] = 'different-parent'
    r = maturity_report([one, two], as_of=NOW + timedelta(days=1))
    assert r['counts']['forecasts'] == 0 and r['rejections']['conflicting_original_forecast_identity'] == 1


def test_inventory_bounds_are_enforced():
    with pytest.raises(ValueError, match='bounded_outcome_readiness'):
        maturity_report([entry()] * 10001, as_of=NOW + timedelta(days=1))


def test_list_style_adapter_reasons_are_preserved_bounded_and_deduplicated():
    assert outcome_reasons({'status': 'withheld', 'reasons': ['official_NBA_required', '', 'official_NBA_required']}) == ['official_NBA_required']
    assert len(outcome_reasons({'reasons': ['x' * 300 + str(i) for i in range(20)]})) <= 8
    assert outcome_reasons({'status': 'pending'}) == ['pending']


def resolution():
    return {'data': [{'condition_id': '0x' + '1' * 64, 'status': 'resolved', 'extended_review': False,
            'was_disputed': False, 'new_version_q': False, 'payouts': [1000000, 0], 'resolved_at': NOW.isoformat(),
            'reporter': 'UMA_OO', 'market_type': 'BINARY', 'resolution_source': 'reported',
            'transaction_hash': '0x' + '2' * 64, 'last_update_timestamp': '1794100000'}]}


def test_complete_schema_never_becomes_an_independently_verified_outcome():
    r = native_resolution_diagnostics(resolution(), condition_id='0x' + '1' * 64)
    assert r['status'] == 'structural_candidate_requires_independent_chain_replay'
    assert r['verified'] is False and r['outcome'] is None and not r['trading_authority']


def test_unsupported_native_version_and_missing_finality_remain_withheld():
    raw = resolution(); row = raw['data'][0]; row['new_version_q'] = True
    for key in ['payouts', 'resolved_at', 'market_type', 'reporter', 'resolution_source']:
        row.pop(key)
    r = native_resolution_diagnostics(raw, condition_id='0x' + '1' * 64)
    assert r['status'] == 'withheld' and r['verified'] is False and r['outcome'] is None
    assert 'unsupported_native_new_version_question_requires_verified_protocol' in r['reasons']
    assert set(r['missing_fields']) == {'payouts', 'resolved_at', 'market_type', 'reporter', 'resolution_source'}


@pytest.mark.parametrize('fault', ['foreign_condition', 'duplicate_condition', 'null_payouts', 'flag_only'])
def test_missing_or_mismatched_native_payloads_cannot_create_labels(fault):
    raw = resolution()
    if fault == 'foreign_condition':
        raw['data'][0]['condition_id'] = '0x' + '3' * 64
    elif fault == 'duplicate_condition':
        raw['data'] *= 2
    elif fault == 'null_payouts':
        raw['data'][0]['payouts'] = None
    else:
        raw = {'verified': True, 'data': []}
    r = native_resolution_diagnostics(raw, condition_id='0x' + '1' * 64)
    assert r['status'] == 'withheld' and r.get('verified') is not True and r.get('outcome') is None


async def test_scheduler_preserves_reason_list_after_restart_without_labeling(tmp_path):
    store = EventStore(tmp_path / 'controlled.sqlite'); _m, _b, ev, f, frame = inputs(); clock = [NOW]
    try:
        research = DomainResearch(store, clock=lambda: clock[0], adapters={'weather': adapter(ev, f)})
        await research.step(frame); clock[0] += timedelta(days=2)
        async def verify(_forecast, **kwargs):
            return {'status': 'withheld', 'reasons': ['official_station_source_unavailable', 'native_finality_unverified']}
        scheduler = DomainOutcomes(store, tmp_path / 'proofs', clock=lambda: clock[0])
        scheduler._module = lambda _adapter: SimpleNamespace(verify_outcome=verify)
        assert await scheduler.step()
        row = store.latest('DomainOutcomeStudy', 1)[0]
        assert row['result']['diagnostic_reasons'] == ['official_station_source_unavailable', 'native_finality_unverified']
        assert scheduler.status()['last_reasons']['weather'] == 'official_station_source_unavailable'
        assert scheduler.status()['rejection_reasons']['weather:native_finality_unverified'] == 1
        assert scheduler.status()['readiness']['verification_due_forecasts'] == 1
        recovered = DomainOutcomes(store, tmp_path / 'proofs', clock=lambda: clock[0])
        assert recovered.state == scheduler.state and not recovered.state['verified']
    finally:
        store.close()


def test_empty_transaction_reference_is_missing_finality_not_a_verified_resolution():
    raw = resolution(); raw['data'][0]['transaction_hash'] = ''
    r = native_resolution_diagnostics(raw, condition_id='0x' + '1' * 64)
    assert 'transaction_hash' in r['missing_fields'] and not r['verified'] and r['outcome'] is None
