"""Controlled engineering fixtures; never live performance or settlement evidence."""
from datetime import UTC, datetime, timedelta

import pytest
from neraium_poly.contracts import Record
from neraium_poly.data import EventStore
from neraium_poly.experimental.config import ExperimentalConfig
from neraium_poly.ops.monitor import render_monitor
from neraium_poly.research.phase14.relationships import digest
from neraium_poly.research.phase16.checkpoints import pack_checkpoint
from neraium_poly.research.phase23.outcomes import ChallengerOutcomes, ChallengerOutcomeStudy

NOW=datetime(2026,11,7,21,tzinfo=UTC)


class ChallengerStudy(Record):
    operation: str='forecast_batch'
    forecasts: list[dict]


def original(store,*,end=NOW+timedelta(hours=1)):
    row=ChallengerStudy(id='controlled-original',timestamp=NOW,available_at=NOW,source='controlled-fixture',
        forecasts=[{'id':'controlled-forecast','domain':'crypto','event_end_time':end.isoformat()}])
    store.append(row)
    return row


async def test_outcome_index_survives_restart_without_inventing_a_label(tmp_path):
    with_store=EventStore(tmp_path/'events.sqlite')
    try:
        original(with_store)
        runtime=ChallengerOutcomes(with_store,tmp_path/'proofs',clock=lambda:NOW)
        assert not await runtime.step()
        assert runtime.status()['registered_pending_forecasts']==1
        assert runtime.status()['verified_forecasts']==0
        restarted=ChallengerOutcomes(with_store,tmp_path/'proofs',clock=lambda:NOW)
        assert restarted.state==runtime.state
        assert not await restarted.step()
        assert with_store.count(kind='ChallengerOutcomeStudy')==1
    finally:with_store.close()


async def test_unverified_matured_forecast_cannot_create_outcome(tmp_path):
    store=EventStore(tmp_path/'events.sqlite')
    try:
        original(store,end=NOW-timedelta(hours=1))
        runtime=ChallengerOutcomes(store,tmp_path/'proofs',clock=lambda:NOW)
        assert await runtime.step()
        assert runtime.status()['checks']==1 and runtime.status()['verified_forecasts']==0
        row=store.latest('ChallengerOutcomeStudy',1)[0]
        assert row['outcome'] is None and row['reason'] and not row['trading_authority']
    finally:store.close()


async def test_storage_denial_or_interrupted_commit_does_not_publish_index(tmp_path,monkeypatch):
    store=EventStore(tmp_path/'events.sqlite')
    try:
        original(store)
        runtime=ChallengerOutcomes(store,tmp_path/'proofs',clock=lambda:NOW,can_write=lambda:False)
        assert not await runtime.step() and not runtime.state['registered']
        runtime.can_write=lambda:True
        append=store.append
        def fail(_record):raise OSError('CONTROLLED disk full')
        monkeypatch.setattr(store,'append',fail)
        with pytest.raises(OSError):await runtime.step()
        assert not runtime.state['registered']
        monkeypatch.setattr(store,'append',append)
        assert not await runtime.step()
        assert len(runtime.state['registered'])==1
    finally:store.close()


def test_corrupt_outcome_checkpoint_is_not_reset(tmp_path):
    store=EventStore(tmp_path/'events.sqlite')
    try:
        s={'last_at':NOW.isoformat()}
        store.append(ChallengerOutcomeStudy(id='corrupt',timestamp=NOW,available_at=NOW,source='controlled',
            checkpoint=pack_checkpoint(s),checkpoint_sha256='0'*64))
        with pytest.raises(ValueError,match='checkpoint'):ChallengerOutcomes(store,tmp_path/'proofs',clock=lambda:NOW)
    finally:store.close()


def test_competition_commit_recovery_and_temporal_dedup(tmp_path,monkeypatch):
    from neraium_poly.research.phase23 import competition, relationships
    from neraium_poly.research.phase23.operations import ContinuousCompetition
    monkeypatch.setattr(competition,'build_leaderboard',lambda studies,outcomes=(),*,as_of,**kw:{'verified':0,'input_count':len(studies)})
    monkeypatch.setattr(relationships,'project_frame',lambda frame,cutoff:{'id':frame['id'],'at':cutoff.isoformat()})
    monkeypatch.setattr(relationships,'evaluate_relationships',lambda frame,history,cutoff:{'prior_frames':len(history)})
    store=EventStore(tmp_path/'events.sqlite')
    try:
        runtime=ContinuousCompetition(store,clock=lambda:NOW)
        assert runtime.step({'id':'controlled-frame'})
        recovered=ContinuousCompetition(store,clock=lambda:NOW)
        assert recovered.state==runtime.state and not recovered.step({'id':'controlled-frame'})
        assert recovered.status()['history_frames']==1 and not recovered.status()['trading_authority']
        runtime.clock=lambda:NOW+timedelta(minutes=1)
        prior=digest(runtime.state)
        def fail(_record):raise OSError('CONTROLLED disk full')
        monkeypatch.setattr(store,'append',fail)
        with pytest.raises(OSError):runtime.step({'id':'next-frame'})
        assert digest(runtime.state)==prior
    finally:store.close()


def test_challenger_monitor_narrow_stale_and_safe_default():
    assert ExperimentalConfig().phase23_research_enabled is False
    exp={'generated_at':datetime.now(UTC).isoformat(),'bankroll':496.11,
        'service':{'paper_trading':True,'live_trading_enabled':False},
        'operations_research':{'phase23':{'status':'research_only','last_evaluation_at':datetime.now(UTC).isoformat(),
            'forecasts':8,'pending_forecasts':8,'unreviewed_parent_events':3,'models':{'controlled-unvalidated':{'forecasts':8,'resolved':0}}}}}
    cert={'cash':500,'operation':{'service':{'paper_trading':True,'live_trading_enabled':False}}}
    rendered=render_monitor(cert,exp,width=32,height=16,view='challengers').plain
    assert all(len(line)<=32 for line in rendered.splitlines())
    assert 'NO TRADING AUTHORITY' in rendered and 'insufficient evidence' in rendered and '$496.11' in rendered
    exp['operations_research']['phase23']['last_evaluation_at']=(datetime.now(UTC)-timedelta(hours=1)).isoformat()
    stale=render_monitor(cert,exp,width=32,height=16,view='challengers').plain
    assert 'unavailable / stale' in stale and 'Forecasts 8' not in stale


def outcome_records(*,crossed=False):
    from neraium_poly.research.phase14.contracts import DomainEvidence
    from neraium_poly.research.phase23.models import forecast_models, map_challenger_contract
    from test_phase18_forecasting import CUTOFF
    from test_phase20_outcomes import records
    old,label,now=records(crossed=crossed)
    c=map_challenger_contract(old['market'],now=CUTOFF)
    result=forecast_models(c,(DomainEvidence.model_validate(old['evidence'][0]),),cutoff=CUTOFF)[0]
    b=old['book']
    f={**result,'id':'controlled-new-forecast','timestamp':CUTOFF.isoformat(),
       'market_probability':(b['bids'][0]['price']+b['asks'][0]['price'])/2,
       'book':b,'book_sha256':digest(b),'market':old['market'],'contract':c.model_dump(mode='json')}
    study={'id':'controlled-new-study','operation':'forecast_batch','timestamp':CUTOFF.isoformat(),
           'available_at':CUTOFF.isoformat(),'forecasts':[f],'evidence':old['evidence']}
    row=ChallengerOutcomeStudy(id='controlled-new-label',timestamp=now,available_at=now,source='controlled-only',
        original_study_id=study['id'],original_study_sha256=digest(study),forecast_id=f['id'],
        outcome=label['outcome'],evidence=label['evidence'],checkpoint=pack_checkpoint({}),checkpoint_sha256=digest({}))
    return study,f,row.model_dump(mode='json'),now


def test_new_challenger_replays_source_and_recomputes_score(tmp_path,monkeypatch):
    import neraium_poly.research.phase23.outcomes as module
    study,f,row,now=outcome_records()
    monkeypatch.setattr(module,'verify_collected_outcome',lambda *a:True) # Controlled native boundary only.
    score=module.verify_outcome(row,study,f,evidence_root=tmp_path,as_of=now)
    assert score['verified'] and score['brier']==(f['probability']-row['outcome']['payout'])**2
    assert score['independence_reviewed'] is False and score['reviewed_dependency_group'] is None
    assert score['trading_authority'] is False


@pytest.mark.parametrize('change',['probability','source_future','missing_final_source','payout','early_settlement'])
def test_new_challenger_rejects_corrupt_or_unavailable_evidence(tmp_path,monkeypatch,change):
    import neraium_poly.research.phase23.outcomes as module
    study,f,row,now=outcome_records()
    monkeypatch.setattr(module,'verify_collected_outcome',lambda *a:True) # Never authentic settled evidence.
    if change=='probability':f['probability']=1-f['probability']
    elif change=='source_future':study['evidence'][0]['available_at']=now.isoformat()
    elif change=='missing_final_source':row['evidence']=[]
    elif change=='payout':row['outcome']['payout']=1-row['outcome']['payout']
    else:row['outcome']['settled_at']=f['timestamp']
    row['original_study_sha256']=digest(study)
    with pytest.raises(ValueError):module.verify_outcome(row,study,f,evidence_root=tmp_path,as_of=now)


def test_competition_accepts_actual_shared_frame_contract_and_recovers(tmp_path):
    from neraium_poly.experimental.contracts import SharedMarketFrame
    from neraium_poly.research.phase23.operations import ContinuousCompetition

    store=EventStore(tmp_path/'controlled.sqlite')
    try:
        frame=SharedMarketFrame(id='controlled-shared-frame',timestamp=NOW,available_at=NOW,
            source='controlled public observation fixture',producer_health={'status':'ok'})
        runtime=ContinuousCompetition(store,clock=lambda:NOW)
        assert runtime.step(frame)
        assert runtime.status()['cycles']==1 and runtime.status()['history_frames']==1
        assert store.latest('CompetitionStudy',1)[0]['source_frame_id']==frame.id
        recovered=ContinuousCompetition(store,clock=lambda:NOW)
        assert recovered.state==runtime.state and not recovered.step(frame)
    finally:
        store.close()


async def test_archive_publisher_runs_while_real_coordinator_cycle_is_waiting():
    import asyncio
    import threading
    from types import SimpleNamespace

    from neraium_poly.ops.live import LivePaperRuntime

    measured=threading.Event();release=asyncio.Event();finished=False
    runtime=LivePaperRuntime.__new__(LivePaperRuntime)
    runtime.stopping=False;runtime.config=SimpleNamespace(archive_management_enabled=True,cycle_interval_seconds=1)
    runtime.events=SimpleNamespace(status=lambda:measured.set())
    async def blocked_cycle():
        await release.wait()
    runtime.cycle=blocked_cycle
    task=asyncio.create_task(runtime.run(lambda:finished))
    try:
        assert await asyncio.wait_for(asyncio.to_thread(measured.wait,2),3)
        assert not task.done()
        finished=True;release.set()
        await asyncio.wait_for(task,3)
    finally:
        release.set();task.cancel();await asyncio.gather(task,return_exceptions=True)


async def test_archive_publisher_shutdown_drains_worker_before_connection_close():
    import asyncio
    import threading
    from types import SimpleNamespace

    from neraium_poly.ops.live import LivePaperRuntime

    entered=threading.Event();release=threading.Event();completed=threading.Event()
    def measure():
        entered.set();release.wait(3);completed.set()
    runtime=LivePaperRuntime.__new__(LivePaperRuntime);runtime.stopping=False
    runtime.events=SimpleNamespace(status=measure)
    task=asyncio.create_task(runtime._archive_measurements(lambda:False))
    try:
        assert await asyncio.wait_for(asyncio.to_thread(entered.wait,2),3)
        task.cancel();await asyncio.sleep(.02)
        assert not task.done() and not completed.is_set()
        release.set();await asyncio.gather(task,return_exceptions=True)
        assert completed.is_set()
    finally:
        release.set();task.cancel();await asyncio.gather(task,return_exceptions=True)


def test_full_reference_can_verify_genuine_early_native_barrier_yes(tmp_path,monkeypatch):
    import hashlib
    import json
    from datetime import datetime

    import neraium_poly.research.phase23.outcomes as module
    study,f,row,now=outcome_records(crossed=True)
    ev=row['evidence'][0];response=ev['payload']['responses'][-1]
    candles=json.loads(response['raw_response_utf8']);candles[-100][3]='74000'
    raw=json.dumps(candles,separators=(',',':'))
    response['raw_response_utf8']=raw;response['raw_response_sha256']=hashlib.sha256(raw.encode()).hexdigest()
    ev['content_sha256']=digest(ev['payload'])
    early=datetime.fromtimestamp(candles[-90][6]/1000,UTC)
    row['outcome']['settled_at']=row['outcome']['timestamp']=early.isoformat()
    monkeypatch.setattr(module,'verify_collected_outcome',lambda *a:True) # Controlled native-proof boundary.
    score=module.verify_outcome(row,study,f,evidence_root=tmp_path,as_of=now)
    assert score['verified'] and score['outcome']==1 and not score['trading_authority']


def test_early_native_no_and_later_reference_hit_cannot_be_verified(tmp_path,monkeypatch):
    import neraium_poly.research.phase23.outcomes as module
    monkeypatch.setattr(module,'verify_collected_outcome',lambda *a:True)
    for crossed in [False,True]:
        study,f,row,now=outcome_records(crossed=crossed)
        end=datetime.fromisoformat(f['event_end_time'])
        row['outcome']['settled_at']=row['outcome']['timestamp']=(end-timedelta(minutes=10)).isoformat()
        with pytest.raises(ValueError):module.verify_outcome(row,study,f,evidence_root=tmp_path,as_of=now)
