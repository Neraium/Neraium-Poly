"""Controlled research and broker-admission fixtures, never real market evidence."""

from copy import deepcopy
from datetime import timedelta
from types import SimpleNamespace

import pytest
from neraium_poly.data import EventStore
from neraium_poly.experimental.contracts import ExperimentalSignal
from neraium_poly.research.phase16.admission import execution_veto
from neraium_poly.research.phase16.checkpoints import pack_checkpoint, unpack_checkpoint
from neraium_poly.research.phase16.continuous import ContinuousQualification
from test_phase16_history import frame as history_frame


def frame(*args, **kwargs):
    value, now = history_frame(*args, **kwargs)
    for market in value["markets"]:
        market["tick_size"] = .001
    return value, now


def test_source_context_and_incremental_replay_survive_restart(tmp_path):
    store = EventStore(tmp_path/'controlled.sqlite')
    try:
        study = ContinuousQualification(store)
        for i in range(6):
            f, now = frame(i)
            assert study.observe(f, now=now)
        rows = store.latest('QualificationStudy', 20)
        assert len(rows) == 6 and sum(r['full_checkpoint'] is not None for r in rows) == 1
        assert rows[0]['raw_frame']['producer_health']['status'] == 'ok'
        assert rows[0]['raw_frame']['id'] == 'fixture-frame-5'
        restored = ContinuousQualification(store)
        assert restored._state() == study._state()
        assert restored.last_id == study.last_id
        assert not restored.observe(f, now=now)
        assert not restored.summary()['trading_authority']
    finally:
        store.close()


def test_ambiguous_archive_commit_reconciles_without_duplicate_or_lost_history(tmp_path, monkeypatch):
    store = EventStore(tmp_path/'controlled.sqlite')
    try:
        study = ContinuousQualification(store)
        original = store.append
        def committed_but_unacknowledged(row):
            original(row)
            raise OSError('CONTROLLED ambiguous acknowledgement')
        monkeypatch.setattr(store, 'append', committed_but_unacknowledged)
        f, now = frame(0)
        with pytest.raises(OSError):
            study.observe(f, now=now)
        assert study.history.cycles == 0 and store.count() == 1
        monkeypatch.setattr(store, 'append', original)
        f, now = frame(1)
        assert study.observe(f, now=now)
        assert store.count() == 2 and study.history.cycles == 2
        assert ContinuousQualification(store)._state() == study._state()
    finally:
        store.close()


def test_checkpoint_corruption_and_rehashed_time_mismatch_are_rejected(tmp_path, monkeypatch):
    from neraium_poly.research.phase14.relationships import digest
    store = EventStore(tmp_path/'controlled.sqlite')
    try:
        study = ContinuousQualification(store)
        f, now = frame()
        study.observe(f, now=now)
        raw = deepcopy(store.latest('QualificationStudy', 1)[0])
        raw['checkpoint_sha256'] = '0'*64
        monkeypatch.setattr(store, 'latest', lambda *_a, **_k: [raw])
        with pytest.raises(ValueError, match='integrity'):
            ContinuousQualification(store)
        state = unpack_checkpoint(raw['full_checkpoint'])
        state['last_full_at'] = (now+timedelta(seconds=1)).isoformat()
        raw['full_checkpoint'] = pack_checkpoint(state)
        raw['checkpoint_sha256'] = digest(state)
        with pytest.raises(ValueError, match='time binding'):
            ContinuousQualification(store)
    finally:
        store.close()


def test_empty_or_ended_universe_cannot_create_fabricated_studies(tmp_path):
    store = EventStore(tmp_path/'controlled.sqlite')
    try:
        study = ContinuousQualification(store)
        f, now = frame()
        for m in f['markets']:
            m['end_time'] = (now-timedelta(seconds=1)).isoformat()
        assert not study.observe(f, now=now) and store.count() == 0
        assert study.last_error == 'no_execution_compatible_research_cohort'
    finally:
        store.close()


def test_execution_gate_can_only_veto_and_does_not_reidentify_a_passing_signal(market, book, now):
    m = market.model_copy(update={'source':'https://gamma-api.polymarket.com'})
    b = book.model_copy(update={'source':'https://clob.polymarket.com'})
    fee = {'fee_rate':.05,'observed_at':now.isoformat(),'source':'https://clob.polymarket.com','reference':'controlled-fee'}
    signal = ExperimentalSignal(id='controlled-eligible', timestamp=now, available_at=now, source='CONTROLLED',
        strategy_id='short_horizon',market_id=m.market_id,token_id=m.token_id,event_id=m.event_id,
        eligible=True,forecast_value=.65,lower_value=.6,upper_value=.7,estimated_net_edge=.1,
        evidence_ids=('controlled-evidence',),hypothesis='CONTROLLED',uncertainty='CONTROLLED')
    f = SimpleNamespace(markets=(m,),books=(b,),fees={m.token_id:fee})
    passed, records = execution_veto([signal], f, now=now)
    assert passed[0] == signal and not records[0].vetoed
    stale = b.model_copy(update={'timestamp':now-timedelta(seconds=16)})
    f.books = (stale,)
    rejected, records = execution_veto([signal], f, now=now)
    assert rejected[0].eligible is False and records[0].vetoed
    assert rejected[0].id != signal.id and rejected[0].estimated_net_edge == signal.estimated_net_edge
    assert 'phase16_stale_book' in rejected[0].reasons
    assert records[0].trading_authority is False


async def test_runtime_study_recovery_preserves_clear_stop_and_certified_sentinel(tmp_path, now):
    from neraium_poly.experimental.config import ExperimentalConfig
    from neraium_poly.experimental.runtime import ExperimentalRuntime
    from test_experimental_account import fee
    from test_experimental_runtime import Clock, Feed, Fees

    clock = Clock(now)
    class PublicFixtureFeed(Feed):
        async def read(self):
            f = await super().read()
            return f.model_copy(update={
                'markets': tuple(m.model_copy(update={'source':'https://gamma-api.polymarket.com'}) for m in f.markets),
                'books': tuple(b.model_copy(update={'source':'https://clob.polymarket.com'}) for b in f.books)})
    certified = tmp_path/'certified'
    certified.mkdir()
    sentinel = certified/'preserved-evidence'
    sentinel.write_bytes(b'CONTROLLED certified fixture')
    cfg = ExperimentalConfig(data_dir=tmp_path/'experimental',certified_directory=certified,
        phase16_research_enabled=True,phase16_execution_veto_enabled=True,event_research_enabled=False,fee_batch=0)
    runtime = ExperimentalRuntime(cfg,feed=PublicFixtureFeed(clock),clock=clock,fee_adapter=Fees())
    try:
        token = runtime.feed.market.token_id
        runtime.fees[token] = fee(now)
        for i in range(3):
            clock.now = now+timedelta(seconds=i*10)
            await runtime.cycle()
        assert runtime.phase16.history.cycles == 3
        assert runtime.account.snapshot(now=clock())['kill_switch'] is False
        state = runtime.operations_state()
        assert state['operations_research']['phase16']['history']['tokens_tracked'] == 1
        assert state['cash'] == 500 and state['orders_submitted'] == 0
    finally:
        await runtime.close()
    runtime = ExperimentalRuntime(cfg,feed=PublicFixtureFeed(clock),clock=clock,fee_adapter=Fees())
    try:
        assert runtime.phase16.history.cycles == 3
        assert runtime.account.snapshot(now=clock())['kill_switch'] is False
        assert sentinel.read_bytes() == b'CONTROLLED certified fixture'
        assert runtime.events.count(kind='QualificationStudy') == 3
    finally:
        await runtime.close()


def test_bounded_label_cache_can_support_all_eight_tokens_readiness(tmp_path):
    store = EventStore(tmp_path/'controlled.sqlite')
    try:
        study = ContinuousQualification(store)
        for i in range(45):
            f, now = frame(i, step=10, tokens=8)
            study.history.observe(f, now=now)
        rows = study.history.summary()['per_token']
        assert len(rows) == 8
        assert all(r['observations'] >= 40 and r['matured_labels'] >= 20 for r in rows)
        assert study.history.summary()['independent_outcome_events'] == 0
    finally:
        store.close()


def test_veto_audit_preserves_full_original_signal_and_hash_when_prior_rejection_exists(market, book, now):
    from hashlib import sha256
    m = market.model_copy(update={'source':'https://gamma-api.polymarket.com'})
    b = book.model_copy(update={'source':'https://clob.polymarket.com'})
    fee = {'fee_rate':.05,'observed_at':now.isoformat(),'source':'https://clob.polymarket.com','reference':'CONTROLLED'}
    original = ExperimentalSignal(id='CONTROLLED-candidate',timestamp=now,available_at=now,source='CONTROLLED',
        strategy_id='short_horizon',market_id=m.market_id,token_id=m.token_id,event_id=m.event_id,
        eligible=True,forecast_value=.5,lower_value=.43,upper_value=.6,estimated_net_edge=.04,
        evidence_ids=('CONTROLLED-full-provenance',),hypothesis='CONTROLLED',uncertainty='CONTROLLED')
    prior = original.model_copy(update={'id':'CONTROLLED-earlier-rejection','eligible':False,'reasons':('CONTROLLED-not-ready',)})
    frame = SimpleNamespace(markets=(m,),books=(b,),fees={m.token_id:fee})
    output, audit = execution_veto([prior,original],frame,now=now)
    assert output[0] is prior and output[1].eligible is False
    assert len(audit) == 1 and type(audit[0]).__name__ == 'ExecutionVeto'
    assert audit[0].original_signal == original.model_dump(mode='json')
    assert audit[0].original_signal_sha256 == sha256(original.model_dump_json().encode()).hexdigest()
    assert not audit[0].qualified and not audit[0].trading_authority
