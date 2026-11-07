"""Controlled prospective mark research; fixtures are not authentic market evidence."""

from copy import deepcopy
from datetime import timedelta
from types import SimpleNamespace

import pytest
from neraium_poly.data import EventStore
from neraium_poly.research.phase16.history import CausalHistory
from neraium_poly.research.phase17.continuous import EmpiricalResearch
from test_phase16_history import START, frame


def advance(study, i):
    f, now = frame(i, step=21)
    for m in f['markets']:
        m['tick_size'] = .001
    study.history.observe(f, now=now)
    study.last_id, study.last_at = f['id'], now.isoformat()
    return now


def fixture():
    return SimpleNamespace(history=CausalHistory(), last_id=None, last_at=None)


def test_prospective_maturation_recovery_and_no_duplicate_scores(tmp_path):
    store = EventStore(tmp_path/'controlled.sqlite')
    try:
        study = fixture(); research = EmpiricalResearch(store, activation_at=START)
        for i in range(34):
            now = advance(study, i); research.observe(study, now=now)
        result = research.summary()
        assert result['forecast_points'] > result['matured_points'] > 0
        assert result['models']['unchanged']['mae'] == 0
        assert result['reviewed_independent_events'] == 0
        assert result['models']['unchanged']['confidence_interval'] is None
        assert result['account_pnl'] is None and not result['trading_authority']
        restored = EmpiricalResearch(store, activation_at=now+timedelta(days=1))
        assert restored.state == research.state and restored.last_id == research.last_id
        assert restored.state['activation_at'] == START.isoformat()
        assert not restored.observe(study, now=now)
        for row in store.latest('EmpiricalResearchUpdate',100):
            for f in row['forecasts']:
                assert f['created_at'] >= f['decision']['observed_at']
            for score in row['scores']:
                assert score['forecast_created_at'] < score['label']['label']['source_at']
        assert store.count() == result['updates']
    finally:
        store.close()


def test_activation_does_not_retroactively_forecast_old_history(tmp_path):
    store = EventStore(tmp_path/'controlled.sqlite')
    try:
        study = fixture()
        for i in range(25):now = advance(study,i)
        research = EmpiricalResearch(store,activation_at=now+timedelta(seconds=1))
        research.observe(study,now=now+timedelta(seconds=1))
        assert research.summary()['forecast_points'] == 0
        research.observe(study,now=now+timedelta(minutes=5))
        assert research.last_error == 'committed_source_study_stale'
        assert research.summary()['forecast_points'] == 0
    finally:store.close()


def test_ambiguous_commit_rolls_back_then_reconciles_exactly_once(tmp_path,monkeypatch):
    store = EventStore(tmp_path/'controlled.sqlite')
    try:
        study=fixture();now=advance(study,0);research=EmpiricalResearch(store,activation_at=START)
        before=deepcopy(research.state);append=store.append
        def fail(row):append(row);raise OSError('CONTROLLED lost acknowledgement')
        monkeypatch.setattr(store,'append',fail)
        with pytest.raises(OSError):research.observe(study,now=now)
        assert research.state==before and store.count()==1
        monkeypatch.setattr(store,'append',append)
        assert not research.observe(study,now=now)
        assert store.count()==1 and research.state['updates']==1
        assert EmpiricalResearch(store,activation_at=now).state==research.state
    finally:store.close()


def test_corruption_never_silently_resets_research(tmp_path,monkeypatch):
    store=EventStore(tmp_path/'controlled.sqlite')
    try:
        study=fixture();now=advance(study,0);research=EmpiricalResearch(store,activation_at=START)
        research.observe(study,now=now)
        row=deepcopy(store.latest('EmpiricalResearchUpdate',1)[0]);row['checkpoint_sha256']='0'*64
        monkeypatch.setattr(store,'latest',lambda *_a,**_k:[row])
        with pytest.raises(ValueError,match='integrity'):EmpiricalResearch(store,activation_at=now)
    finally:store.close()


def test_expired_missing_labels_never_receive_fabricated_scores(tmp_path):
    store=EventStore(tmp_path/'controlled.sqlite')
    try:
        study=fixture();research=EmpiricalResearch(store,activation_at=START)
        for i in range(21):now=advance(study,i);research.observe(study,now=now)
        assert research.summary()['pending_points']>0
        f,late=frame(40,step=21)
        study.history.observe(f,now=late);study.last_at=late.isoformat();study.last_id=f['id']
        research.observe(study,now=late)
        assert research.summary()['expired_points']>0
        assert research.summary()['matured_points']==0
    finally:store.close()


async def test_integrated_runtime_restart_preserves_stop_accounts_and_original_source_guard(tmp_path,now):
    from neraium_poly.experimental.config import ExperimentalConfig
    from neraium_poly.experimental.runtime import ExperimentalRuntime
    from neraium_poly.experimental.migration import strategy_code_hash
    from test_experimental_runtime import Clock,Feed,Fees
    from test_experimental_account import fee
    clock=Clock(now)
    class PublicFixtureFeed(Feed):
        async def read(self):
            f=await super().read()
            return f.model_copy(update={'markets':tuple(m.model_copy(update={'source':'https://gamma-api.polymarket.com'}) for m in f.markets),
                'books':tuple(b.model_copy(update={'source':'https://clob.polymarket.com'}) for b in f.books)})
    certified=tmp_path/'certified';certified.mkdir();sentinel=certified/'evidence';sentinel.write_bytes(b'CONTROLLED certified unchanged')
    config=ExperimentalConfig(data_dir=tmp_path/'experimental',certified_directory=certified,event_research_enabled=False,
        phase16_research_enabled=True,phase17_research_enabled=True,fee_batch=0)
    original_hash=strategy_code_hash();runtime=ExperimentalRuntime(config,feed=PublicFixtureFeed(clock),clock=clock,fee_adapter=Fees())
    try:
        runtime.fees[runtime.feed.market.token_id]=fee(now)
        await runtime.cycle()
        assert runtime.phase17.summary()['updates']==1 and runtime.phase17_error is None
        assert runtime.operations_state()['operations_research']['phase17']['trading_authority'] is False
        runtime.account.stop(now=clock(),reason='CONTROLLED stop preserved across restart')
        saved=deepcopy(runtime.phase17.state)
    finally:await runtime.close()
    runtime=ExperimentalRuntime(config,feed=PublicFixtureFeed(clock),clock=clock,fee_adapter=Fees())
    try:
        assert runtime.phase17.state==saved and runtime.model_hash==original_hash
        state=runtime.account.snapshot(now=clock());assert state['cash']==500 and state['kill_switch'] is True
        assert state['orders_submitted']==0 and sentinel.read_bytes()==b'CONTROLLED certified unchanged'
    finally:await runtime.close()
