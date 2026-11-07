"""Controlled scheduler tests; fixtures are never installed as real evidence."""
from datetime import timedelta

import pytest
from neraium_poly.data import EventStore
from neraium_poly.research.phase18.continuous import IndependentEventResearch
from neraium_poly.research.phase21.continuous import EarlyOutcomeResearch
from test_phase18_continuous import Clock, collect, frame


async def seeded(tmp_path):
    store = EventStore(tmp_path/'controlled.sqlite')
    clock = Clock()
    engine = IndependentEventResearch(store, clock=clock, collector=collect)
    await engine.step(frame(clock))
    return store, clock, engine.state['pending']


async def test_reference_check_is_durable_not_a_settlement_and_recovers(tmp_path):
    store, clock, pending = await seeded(tmp_path)
    try:
        r = EarlyOutcomeResearch(store, tmp_path/'proofs', clock=clock, collector=collect)
        assert await r.step(pending)
        assert r.state['source_checks'] == 1 and r.state['native_attempts'] == r.state['verified'] == 0
        row = store.latest('EventResolutionStudy', 1)[0]
        assert row['evidence'] and row['checks'] and row['outcome'] is None
        assert not row['trading_authority']
        recovered = EarlyOutcomeResearch(store, tmp_path/'proofs', clock=clock, collector=collect)
        assert recovered.state == r.state and not await recovered.step(pending)
        assert store.count(kind='EventResolutionStudy') == 1
    finally:
        store.close()


async def test_reference_hit_without_native_finality_never_scores(tmp_path, monkeypatch):
    import neraium_poly.research.phase21.continuous as module
    store, clock, pending = await seeded(tmp_path)
    async def unavailable(*_a, **_kw): return None
    monkeypatch.setattr(module, 'reference_condition', lambda *_a, **_kw:
                        {'eligible_for_native_check': True, 'selected_payout': 1})
    monkeypatch.setattr(module, 'acquire_verified_outcome', unavailable)
    try:
        r = EarlyOutcomeResearch(store, tmp_path/'proofs', clock=clock, collector=collect)
        assert await r.step(pending)
        assert r.state['native_attempts'] == 1 and r.state['verified'] == 0
        row = store.latest('EventResolutionStudy', 1)[0]
        assert row['outcome'] is None and row['model_result']['status'] == 'withheld'
        assert row['model_result']['reasons'] == ['native_final_settlement_not_available']
    finally:
        store.close()


async def test_storage_backpressure_no_source_or_native_request(tmp_path):
    store, clock, pending = await seeded(tmp_path)
    calls = []
    async def counted(*a, **kw): calls.append(1); return await collect(*a, **kw)
    try:
        r = EarlyOutcomeResearch(store, tmp_path/'proofs', clock=clock, collector=counted, can_write=lambda: False)
        assert not await r.step(pending) and not calls and store.count(kind='EventResolutionStudy') == 0
    finally:
        store.close()


async def test_lost_commit_acknowledgement_reconciles_once(tmp_path, monkeypatch):
    store, clock, pending = await seeded(tmp_path)
    r = EarlyOutcomeResearch(store, tmp_path/'proofs', clock=clock, collector=collect)
    append = store.append
    def lost(row): append(row); raise OSError('CONTROLLED lost acknowledgement')
    monkeypatch.setattr(store, 'append', lost)
    try:
        with pytest.raises(OSError): await r.step(pending)
        monkeypatch.setattr(store, 'append', append)
        assert not await r.step(pending)
        assert r.state['source_checks'] == 1 and store.count(kind='EventResolutionStudy') == 1
        clock.now += timedelta(seconds=1)
    finally:
        store.close()


@pytest.mark.parametrize('boundary', ['budget', 'global_floor', 'unknown'])
async def test_native_acquisition_reserves_full_evidence_headroom(tmp_path, monkeypatch, boundary):
    store, clock, pending = await seeded(tmp_path)
    calls = []
    async def source(*a, **kw): calls.append(1); return await collect(*a, **kw)
    status = {'health': 'ok', 'usage_bytes': 100, 'budget_bytes': 128*1024**2,
              'free_bytes': 101*1024**3, 'global_floor_bytes': 100*1024**3}
    if boundary == 'budget': status['budget_bytes'] = 100+16*1024**2-1
    if boundary == 'global_floor': status['free_bytes'] = status['global_floor_bytes']+16*1024**2-1
    if boundary == 'unknown': status['free_bytes'] = None
    monkeypatch.setattr(store, 'status', lambda: status, raising=False)
    try:
        r = EarlyOutcomeResearch(store, tmp_path/'proofs', clock=clock, collector=source)
        assert not await r.step(pending) and not calls and store.count(kind='EventResolutionStudy') == 0
    finally:
        store.close()


async def test_unfinalized_first_hit_does_not_starve_later_eligible_forecast(tmp_path, monkeypatch):
    from copy import deepcopy

    import neraium_poly.research.phase21.continuous as module
    from neraium_poly.research.phase14.relationships import digest
    from neraium_poly.research.phase18.continuous import EventProbabilityStudy
    store, clock, pending = await seeded(tmp_path)
    original = store.latest('EventProbabilityStudy', 1)[0]
    other = deepcopy(original)
    other['id'] = digest(['CONTROLLED second original'])
    other['forecast']['id'] = digest(['CONTROLLED second forecast'])
    store.append(EventProbabilityStudy.model_validate(other))
    pending[other['forecast']['id']] = other['forecast']
    attempted = []
    async def unavailable(reference, *_a, **_kw): attempted.append(reference.id); 
    monkeypatch.setattr(module, 'reference_condition', lambda *_a, **_kw:
                        {'eligible_for_native_check': True, 'selected_payout': 1})
    monkeypatch.setattr(module, 'acquire_verified_outcome', unavailable)
    try:
        r = EarlyOutcomeResearch(store, tmp_path/'proofs', clock=clock, collector=collect)
        assert await r.step(pending)
        clock.now += timedelta(seconds=301)
        assert await r.step(pending)
        assert len(attempted) == 2 and len(set(attempted)) == 2
        assert len(r.state['native_checked_at']) == 2 and r.state['verified'] == 0
        assert all(row['outcome'] is None for row in store.latest('EventResolutionStudy', 2))
    finally:
        store.close()
