"""Controlled model/causality fixtures, never genuine research observations."""
from copy import deepcopy
from datetime import UTC, datetime, timedelta

import pytest
from neraium_poly.research.phase25 import finance
from neraium_poly.research.phase27.forecasting import (
    derive_spx_payout,
    evaluate_payout_challenger,
    fit_payout_posterior,
    spx_observations,
)
from test_phase25_finance_economics import NOW, book, evidence, market


def records(n=252, *, observed_now=False):
    start = datetime(2025, 1, 1, 21, tzinfo=UTC); result = []; i = 0
    while len(result) < n:
        t = start+timedelta(days=i); i += 1
        if t.weekday() >= 5:
            continue
        result.append({'event_id': 'SPX:'+t.date().isoformat(), 'event_time': t.isoformat(),
                       'available_at': NOW.isoformat() if observed_now else (t+timedelta(minutes=10)).isoformat(),
                       'outcome': ('up', 'tie', 'down')[len(result)%3], 'source_sha256': 'a'*64})
    return result


def test_posterior_preserves_ties_and_is_reproducible_without_market_features():
    rows = records(); a = fit_payout_posterior(rows, cutoff=NOW)
    b = fit_payout_posterior([{**r, 'market_probability': .99} for r in rows], cutoff=NOW)
    assert a == b and a['expected_up_payout'] == pytest.approx(.5)
    assert sum(a['outcome_probabilities'].values()) == pytest.approx(1)
    assert a['outcome_probabilities']['tie'] > 0 and a['calibration_status'] == 'unvalidated_research'
    assert not a['trading_authority'] and not a['certification_authority']


@pytest.mark.parametrize('fault', ['future', 'duplicate', 'forged_parent', 'unordered', 'source_hash'])
def test_training_integrity_failures_reject(fault):
    rows = records()
    if fault == 'future': rows[-1]['available_at'] = (NOW+timedelta(seconds=1)).isoformat()
    elif fault == 'duplicate': rows[-1] = rows[0]
    elif fault == 'forged_parent': rows[-1]['event_id'] = 'SPX:fake'
    elif fault == 'unordered': rows[0], rows[1] = rows[1], rows[0]
    else: rows[-1]['source_sha256'] = 'not-a-source-hash'
    with pytest.raises(ValueError): fit_payout_posterior(rows, cutoff=NOW)


def test_reconstructed_availability_never_silently_becomes_point_in_time():
    rows = records(observed_now=True)
    with pytest.raises(ValueError, match='availability'): evaluate_payout_challenger(rows)
    result = evaluate_payout_challenger(rows, reconstructed=True)
    assert result['historical_reconstruction'] and not result['point_in_time_historical_availability_verified']
    assert result['qualified_certification_training_events'] == result['qualified_certification_heldout_events'] == 0
    assert result['global_frequency_baseline']['binary_brier_score'] is None
    assert result['market_baseline'] is None and result['net_trading_performance'] is None


def test_heldout_labels_do_not_select_calibration_or_training_parameters():
    rows = records(); first = evaluate_payout_challenger(rows); changed = deepcopy(rows)
    for row in changed[189:]: row['outcome'] = 'up'
    second = evaluate_payout_challenger(changed)
    assert first['calibration_weight'] == second['calibration_weight']
    assert first['training_interval'] == second['training_interval']
    ids = first['event_ids']
    assert not set(ids['training']) & set(ids['calibration'])
    assert not set(ids['heldout']) & (set(ids['training']) | set(ids['calibration']))
    assert first['split'] == {'training': 126, 'calibration': 63, 'heldout': 63}
    assert not first['statistically_supported_advantage']


async def original(monkeypatch, outcome='Up'):
    m = market(outcome=outcome); e = evidence(); b = book(m)
    async def collect(**kw): return (e,)
    monkeypatch.setattr(finance, 'collect', collect)
    r = await finance.forecast(m, b, clock=lambda: NOW)
    f = {**r['forecasts'][0], 'adapter': 'finance', 'id': 'controlled-original'}
    return m, b, e, f, {'id': 'controlled-study', 'timestamp': NOW.isoformat(), 'available_at': NOW.isoformat(), 'forecasts': [f], 'evidence': r['evidence']}


async def test_new_payout_forecast_uses_fresh_book_and_never_revises_original(monkeypatch):
    m, b, _e, f, study = await original(monkeypatch); before = deepcopy(study); later = NOW+timedelta(seconds=1)
    live = b.model_copy(update={'id': 'controlled-new-book', 'timestamp': later, 'available_at': later})
    new = derive_spx_payout(study, f, market=m, book=live, cutoff=later)
    assert study == before and new['timestamp'] == later.isoformat() and new['id'] != f['id']
    assert new['book_id'] == live.id and new['probability_semantics'] == 'expected_payout'
    assert new['probability'] == new['expected_payout']
    assert new['original_target_conditioning'] == f['target_conditioning']
    assert 'including ties' in new['target_conditioning']
    assert new['lower_probability'] == 0 and new['upper_probability'] == 1
    assert not new['unconditional_contract_probability'] and not new['trading_authority']


async def test_payout_up_down_complementary_without_assuming_probability_semantics(monkeypatch):
    values = []
    for side in ['Up', 'Down']:
        m, b, _e, f, study = await original(monkeypatch, side)
        values.append(derive_spx_payout(study, f, market=m, book=b, cutoff=NOW)['expected_payout'])
    assert sum(values) == pytest.approx(1.)


@pytest.mark.parametrize('fault', ['stale_book', 'changed_rules', 'started', 'original_tamper', 'evidence_tamper'])
async def test_new_forecast_rejects_unsupported_or_unavailable_inputs(monkeypatch, fault):
    m, b, _e, f, study = await original(monkeypatch); cutoff = NOW
    if fault == 'stale_book': b = b.model_copy(update={'timestamp': NOW-timedelta(seconds=16)})
    elif fault == 'changed_rules': m = m.model_copy(update={'resolution_rules': m.resolution_rules+' changed'})
    elif fault == 'started': cutoff = datetime(2026, 11, 9, 15, tzinfo=UTC)
    elif fault == 'original_tamper': f = {**f, 'probability': .999}
    else: study['evidence'][0]['payload']['raw_response_utf8'] += 'corrupt'
    with pytest.raises(ValueError): derive_spx_payout(study, f, market=m, book=b, cutoff=cutoff)


def test_fractional_payout_observations_retain_actual_retrieval_availability():
    e = evidence(); rows = spx_observations([e], cutoff=NOW)
    assert len(rows) >= 252 and all(r['available_at'] == e.available_at.isoformat() for r in rows)
    assert all(r['event_id'].startswith('SPX:') for r in rows)


async def test_frozen_distinct_baselines_replay_and_tampering_rejects(monkeypatch):
    from neraium_poly.research.phase27.forecasting import BASELINE_MODEL, MODEL, replay_spx_payout
    m, b, _e, f, study = await original(monkeypatch)
    baseline = derive_spx_payout(study, f, market=m, book=b, cutoff=NOW)
    challenger = derive_spx_payout(study, f, market=m, book=b, cutoff=NOW, model_id=MODEL)
    assert baseline['model_id'] == BASELINE_MODEL and challenger['model_id'] == MODEL
    assert baseline['id'] != challenger['id'] and baseline['model_sha256'] != challenger['model_sha256']
    for new in [baseline, challenger]:
        assert replay_spx_payout(new, study, f, as_of=NOW)['verified']
        assert new['contract']['conditioning'] == new['target_conditioning']
        assert new['contract']['settlement_payouts'] == {'up': 1., 'tie': .5, 'down': 0.}
        with pytest.raises(ValueError):
            replay_spx_payout({**new, 'expected_payout': .999}, study, f, as_of=NOW)


async def test_original_future_study_cannot_be_used_before_its_availability(monkeypatch):
    m, b, _e, f, study = await original(monkeypatch)
    study['available_at'] = (NOW+timedelta(seconds=1)).isoformat()
    with pytest.raises(ValueError, match='study_not_available'):
        derive_spx_payout(study, f, market=m, book=b, cutoff=NOW)


def test_neutral_payout_comparison_is_not_invented_market_probability():
    rows = records(); result = evaluate_payout_challenger(rows)
    heldout = rows[189:]; payouts = {'up': 1., 'tie': .5, 'down': 0.}
    expected = sum((.5-payouts[r['outcome']])**2 for r in heldout)/len(heldout)
    assert result['neutral_payout_baseline']['squared_payout_error'] == pytest.approx(expected)
    assert result['market_baseline'] is None
