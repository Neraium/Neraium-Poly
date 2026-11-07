"""Controlled engineering fixtures, never real prospective evidence."""
from copy import deepcopy
from datetime import timedelta

import pytest
from neraium_poly.data import EventStore
from neraium_poly.research.phase18.continuous import IndependentEventResearch
from neraium_poly.research.phase20.continuous import ProspectiveABResearch
from test_phase18_continuous import Clock, collect, frame


async def setup(store):
    clock = Clock()
    prior = IndependentEventResearch(store, clock=clock, collector=collect)
    await prior.step(frame(clock))
    original = store.latest('EventProbabilityStudy', 1)[0]
    clock.now -= timedelta(seconds=1)
    research = ProspectiveABResearch(store, baseline_model_sha256=original['forecast']['model_sha256'], clock=clock)
    clock.now += timedelta(seconds=1)
    return clock, research, original


async def test_durable_withheld_pair_restart_without_fake_challenger(tmp_path):
    store = EventStore(tmp_path/'controlled.sqlite')
    try:
        clock, research, original = await setup(store)
        before = deepcopy(original)
        assert research.observe(original)
        assert original == before
        assert research.summary()['observations'] == research.summary()['withheld'] == 1
        assert research.summary()['paired'] == 0
        assert research.summary()['rejections'] == {'frozen_trained_sii_challenger_unavailable': 1}
        assert research.summary()['brier_improvement'] is None
        row = store.latest('PairedForecastStudy', 1)[0]
        assert row['result']['pair'] is None and not row['trading_authority']
        recovered = ProspectiveABResearch(store, baseline_model_sha256=original['forecast']['model_sha256'], clock=clock)
        assert recovered.state == research.state and not recovered.observe(original)
        assert store.count() == 3  # original + declaration + withheld observation
    finally:
        store.close()


async def test_no_retrospective_enrollment_or_storage_bypass(tmp_path):
    store = EventStore(tmp_path/'controlled.sqlite')
    try:
        _clock, research, original = await setup(store)
        old = deepcopy(original)
        old['forecast']['timestamp'] = research.state['declared_at']
        assert not research.observe(old)
        research.can_write = lambda: False
        assert not research.observe(original)
        assert research.summary()['observations'] == 0
        assert research.last_error == 'paired_research_storage_backpressure'
        assert store.count() == 2
    finally:
        store.close()


async def test_ambiguous_append_reconciles_idempotently(tmp_path, monkeypatch):
    store = EventStore(tmp_path/'controlled.sqlite')
    try:
        _clock, research, original = await setup(store)
        before = deepcopy(research.state)
        append = store.append
        def lost(row):
            append(row)
            raise OSError('CONTROLLED lost acknowledgement')
        monkeypatch.setattr(store, 'append', lost)
        with pytest.raises(OSError):
            research.observe(original)
        assert research.state == before and store.count() == 3
        monkeypatch.setattr(store, 'append', append)
        assert not research.observe(original)
        assert research.state['observations'] == 1 and store.count() == 3
    finally:
        store.close()


async def test_corruption_or_changed_policy_cannot_reset_checkpoint(tmp_path, monkeypatch):
    store = EventStore(tmp_path/'controlled.sqlite')
    try:
        clock, _research, original = await setup(store)
        with pytest.raises(ValueError, match='no reset'):
            ProspectiveABResearch(store, baseline_model_sha256='0'*64, clock=clock)
        row = deepcopy(store.latest('PairedForecastStudy', 1)[0])
        row['checkpoint_sha256'] = '0'*64
        monkeypatch.setattr(store, 'latest', lambda *_a, **_kw: [row])
        with pytest.raises(ValueError, match='integrity'):
            ProspectiveABResearch(store, baseline_model_sha256=original['forecast']['model_sha256'], clock=clock)
    finally:
        store.close()


async def test_budget_failure_during_declaration_leaves_archive_unchanged(tmp_path):
    store = EventStore(tmp_path/'controlled.sqlite')
    try:
        with pytest.raises(ValueError, match='backpressure'):
            ProspectiveABResearch(store, baseline_model_sha256='1'*64, clock=Clock(), can_write=lambda: False)
        assert store.count() == 0
    finally:
        store.close()


async def test_crash_after_original_commit_records_gap_without_backdating(tmp_path):
    store = EventStore(tmp_path/'controlled.sqlite')
    try:
        clock, research, original = await setup(store)
        clock.now += timedelta(minutes=5)
        recovered = ProspectiveABResearch(store, baseline_model_sha256=None, clock=clock)
        assert recovered.summary()['observations'] == 1
        assert recovered.summary()['rejections'] == {'missed_timely_enrollment_after_recovery': 1}
        assert recovered.state['declared_at'] == research.state['declared_at']
        assert not recovered.observe(original)
        assert store.latest('PairedForecastStudy', 1)[0]['result']['pair'] is None
    finally:
        store.close()


async def test_runtime_research_flag_preserves_account_and_recovers_declaration(tmp_path):
    from neraium_poly.experimental.config import ExperimentalConfig
    from neraium_poly.experimental.runtime import ExperimentalRuntime
    from test_experimental_runtime import Feed, Fees
    config = ExperimentalConfig(data_dir=tmp_path/'experimental', certified_directory=tmp_path/'certified',
        min_free_disk_mb=512, fee_batch=0, phase18_event_research_enabled=True, phase20_ab_research_enabled=True)
    clock = Clock()
    from neraium_poly.experimental.account import ExperimentalAccount
    account = ExperimentalAccount(config.data_dir, config.certified_directory, clock=clock)
    account.close()
    seed = EventStore(config.data_dir/'events.sqlite')
    try:
        engine = IndependentEventResearch(seed, clock=clock, collector=collect)
        await engine.step(frame(clock))
    finally:
        seed.close()
    r = ExperimentalRuntime(config, feed=Feed(clock), clock=clock, fee_adapter=Fees())
    assert r.phase20 is not None and r.phase20_error is None
    declaration = r.phase20.experiment
    assert r.account.risk.snapshot(now=clock())['cash'] == 500
    assert r.phase20.summary()['observations'] == 0
    await r.close()
    r = ExperimentalRuntime(config, feed=Feed(clock), clock=clock, fee_adapter=Fees())
    try:
        assert r.phase20.experiment == declaration and not r.phase20_error
        assert r.account.risk.snapshot(now=clock())['cash'] == 500
        assert r.events.count(kind='PairedForecastStudy') == 1
    finally:
        await r.close()
