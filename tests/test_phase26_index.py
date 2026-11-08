"""Controlled projection engineering fixtures; never authentic forecasts."""
import sqlite3
from copy import deepcopy
from datetime import timedelta

import pytest
from neraium_poly.contracts import Record
from neraium_poly.data.segmented import ManagedEventStore
from neraium_poly.research.phase14.relationships import digest
from neraium_poly.research.phase26.index import ResearchIndex
from pydantic import Field
from test_phase25_competition import END, NOW, fixture


class ChallengerStudy(Record):
    enrollment_id:str='controlled-enrollment'
    enrollment:list=Field(default_factory=list)
    forecasts:list=Field(default_factory=list)


class DomainOutcomeStudy(Record):
    result:dict
    original_study_id:str
    original_study_sha256:str


@pytest.fixture
def environment(tmp_path):
    store=ManagedEventStore(tmp_path/'source'/'events.sqlite',segment_bytes=256*1024,budget_bytes=128*1024**2,min_free_bytes=0,compress=False,cold_verification_enabled=False)
    index=ResearchIndex(tmp_path/'projection.sqlite',source_directory=store.directory)
    yield store,index
    index.close();store.close()


def add(store,identity='controlled',*,model='baseline',enroll=True):
    s,f=fixture(identity,model=model)
    record=ChallengerStudy(id=s['id'],timestamp=NOW,available_at=NOW,source='controlled-fixture',
        enrollment=[{'model_id':model,'model_sha256':f['model_sha256']}] if enroll else [],forecasts=[f])
    store.append(record)
    return record.model_dump(mode='json'),f


def ok(*args,**kwargs):return {'verified':True}


def test_full_counts_survive_tail_aging_restart_without_replaying_sources(environment,tmp_path):
    store,index=environment;_s,_f=add(store);calls=[]
    def verify(*a,**kw):calls.append(a[1]['id']);return ok()
    first=index.step(store,as_of=NOW,forecast_verifier=verify);assert first['caught_up']
    later=NOW+timedelta(seconds=1)
    for i in range(8):store.append(ChallengerStudy(id=f'scan-{i}',timestamp=later,available_at=later,source='controlled-fixture'))
    assert store.latest('ChallengerStudy',1)[0]['forecasts']==[]
    index.step(store,as_of=later,forecast_verifier=verify)
    assert index.report(as_of=later)['counts']['forecasts']==1 and calls==['controlled']
    other=ResearchIndex(index.path,source_directory=store.directory)
    try:
        other.step(store,as_of=later,forecast_verifier=verify)
        r=other.report(as_of=later);assert r['counts']['forecasts']==1 and calls==['controlled']
        assert not r['trading_authority'] and r['research_competition']['event_review']['counts']['certification_independent_events']==0
    finally:other.close()


def test_cache_corruption_cannot_self_approve_projection(environment):
    store,index=environment;add(store);index.step(store,as_of=NOW,forecast_verifier=ok)
    # Simulate hostile/coordinated derived-cache modification. The immutable
    # primary anchor remains authoritative even if a local row checksum is changed.
    index.db.execute('DROP TRIGGER projection_no_update')
    row=index.db.execute('SELECT * FROM entries ORDER BY rowid DESC LIMIT 1').fetchone()
    index.db.execute('UPDATE entries SET payload=?,sha=? WHERE chain=?',('{}',digest({}),row['chain']));index.db.commit()
    with pytest.raises(ValueError,match='checksum/chain'):index.report(as_of=NOW)


def test_orphan_cache_branch_after_failed_anchor_is_never_published(environment,monkeypatch):
    store,index=environment;add(store);original=store.append
    def fail(record):raise OSError('CONTROLLED disk full')
    monkeypatch.setattr(store,'append',fail)
    with pytest.raises(OSError):index.step(store,as_of=NOW,forecast_verifier=ok)
    assert index.report(as_of=NOW)['counts']['forecasts']==0
    monkeypatch.setattr(store,'append',original)
    index.step(store,as_of=NOW,forecast_verifier=ok)
    assert index.report(as_of=NOW)['counts']['forecasts']==1


def test_failed_replay_does_not_become_identity_reviewed_or_scored(environment):
    store,index=environment;add(store)
    index.step(store,as_of=NOW,forecast_verifier=lambda *a,**kw:{'verified':False})
    r=index.report(as_of=NOW);assert r['counts']['forecasts']==1
    assert r['research_competition']['event_review']['counts']['source_identity_reviewed_forecasts']==0
    assert 'independent source/model replay failed' in r['rejections']


def test_new_sources_only_and_bounded_bootstrap(environment):
    store,index=environment;add(store,'a');add(store,'b',enroll=False);calls=[]
    def verify(s,f,**kw):calls.append(f['id']);return ok()
    assert not index.step(store,as_of=NOW,forecast_verifier=verify,max_records=1)['caught_up']
    assert index.report(as_of=NOW)['counts']['forecasts']==1
    assert index.step(store,as_of=NOW,forecast_verifier=verify,max_records=1)['caught_up']
    assert calls==['a','b'] and index.report(as_of=NOW)['counts']['forecasts']==2


def test_outcomes_require_independent_exact_final_proof_and_preserve_recovery(environment):
    store,index=environment;s,f=add(store);index.step(store,as_of=NOW,forecast_verifier=ok)
    after=END+timedelta(hours=1)
    store.append(DomainOutcomeStudy(id='outcome',timestamp=after,available_at=after,source='controlled-fixture',result={'status':'verified','forecast_id':f['id']},original_study_id=s['id'],original_study_sha256=digest(s)))
    def verify(row,forecast):
        return {'verified':True,**{k:forecast[k] for k in ['event_id','market_id','token_id','rules_sha256']},'forecast_id':forecast['id'],
            'resolved_at':END.isoformat(),'available_at':after.isoformat(),'brier':.16,'log_loss':.5}
    index.step(store,as_of=after,forecast_verifier=ok,outcome_verifier=verify)
    result=index.report(as_of=after);assert result['counts']['individually_verified_forecasts']==1
    assert result['leaderboard'][0]['metrics'] is None and result['leaderboard'][0]['calibration'] is None
    assert result['leaderboard'][0]['profitability_rank'] is None


def test_recorded_verified_flag_does_not_create_an_outcome(environment):
    store,index=environment;s,f=add(store);index.step(store,as_of=NOW,forecast_verifier=ok);after=END+timedelta(hours=1)
    store.append(DomainOutcomeStudy(id='fake-outcome',timestamp=after,available_at=after,source='controlled-fixture',result={'status':'verified','forecast_id':f['id']},original_study_id=s['id'],original_study_sha256=digest(s)))
    index.step(store,as_of=after,forecast_verifier=ok)
    assert index.report(as_of=after)['counts']['individually_verified_forecasts']==0


def test_clock_regression_and_changed_source_cursor_fail_closed(environment):
    store,index=environment;add(store);index.step(store,as_of=NOW,forecast_verifier=ok)
    with pytest.raises(ValueError,match='predates'):index.report(as_of=NOW-timedelta(seconds=1))
    with pytest.raises(ValueError,match='clock regression'):index.step(store,as_of=NOW-timedelta(seconds=1),forecast_verifier=ok)
    store.catalog.execute('DROP TRIGGER records_no_update');store.catalog.execute("UPDATE records SET digest=? WHERE id='study-controlled'",('b'*64,));store.catalog.commit()
    with pytest.raises(ValueError,match='witness'):index.report(as_of=NOW)


def test_unknown_model_enrollment_is_not_implicitly_registered(environment):
    store,index=environment;add(store,enroll=False)
    index.step(store,as_of=NOW,forecast_verifier=ok)
    r=index.report(as_of=NOW);assert r['research_competition']['event_review']['counts']['source_identity_reviewed_forecasts']==0
    assert 'original declared model and enrollment required' in r['rejections']


def test_index_does_not_change_original_research_or_financial_records(environment):
    store,index=environment;s,_f=add(store);original=store.get(s['id'])
    index.step(store,as_of=NOW,forecast_verifier=ok)
    assert store.get(s['id'])==original and store.count(kind='RiskDecision')==0 and store.count(kind='OrderIntent')==0


def test_duplicate_forecast_conflicts_quarantine_all_versions(environment):
    store,index=environment;_s,f=add(store);other=deepcopy(f);other['probability']=.9
    store.append(ChallengerStudy(id='conflict',timestamp=NOW,available_at=NOW,source='controlled-fixture',forecasts=[other]))
    index.step(store,as_of=NOW,forecast_verifier=ok)
    r=index.report(as_of=NOW);assert r['counts']['forecasts']==0 and r['rejections']['conflicting_original_forecast_identity']==1


def test_disagreement_requires_exact_same_cohort_and_sii_never_self_qualifies(environment):
    store,index=environment;add(store,'a');_s,f=add(store,'b',model='other');f['sii_experiment']={'variant':'with_sii'}
    index.step(store,as_of=NOW,forecast_verifier=ok);r=index.report(as_of=NOW)
    assert len(r['research_competition']['same_cohort_disagreements'])==1
    assert r['research_competition']['sii']['qualified_pairs']==0


def test_failed_local_transaction_leaves_original_source_untouched(environment,monkeypatch):
    store,index=environment;_s,_f=add(store);before=store.count()
    def fail(*a):raise sqlite3.OperationalError('CONTROLLED full disk')
    monkeypatch.setattr(index,'_append',fail)
    with pytest.raises(sqlite3.OperationalError):index.step(store,as_of=NOW,forecast_verifier=ok)
    assert store.count()==before and index.report(as_of=NOW)['counts']['forecasts']==0


def test_readonly_cli_report_never_initializes_or_ingests(environment):
    store,index=environment;add(store);index.step(store,as_of=NOW,forecast_verifier=ok)
    reader=ResearchIndex(index.path,source_directory=store.directory,readonly=True)
    try:
        assert reader.report(as_of=NOW)['counts']['forecasts']==1
        with pytest.raises(ValueError,match='readonly'):reader.step(store,as_of=NOW,forecast_verifier=ok)
    finally:reader.close()


def test_missing_readonly_projection_is_not_created(environment,tmp_path):
    store,_index=environment;target=tmp_path/'absent.sqlite'
    with pytest.raises(ValueError,match='existing projection'):ResearchIndex(target,source_directory=store.directory,readonly=True)
    assert not target.exists()


def test_failed_anchor_after_valid_checkpoint_preserves_old_published_prefix(environment,monkeypatch):
    store,index=environment;add(store,'first');index.step(store,as_of=NOW,forecast_verifier=ok);add(store,'second',enroll=False)
    append=store.append
    def fail(_record):raise OSError('CONTROLLED interrupted anchor append')
    monkeypatch.setattr(store,'append',fail)
    with pytest.raises(OSError):index.step(store,as_of=NOW,forecast_verifier=ok)
    assert index.report(as_of=NOW)['counts']['forecasts']==1
    monkeypatch.setattr(store,'append',append)
    # A different failure-proof result branches off the trusted prefix. The
    # previously written orphan must not grant a positive replay flag.
    index.step(store,as_of=NOW,forecast_verifier=lambda *a,**kw:{'verified':False})
    result=index.report(as_of=NOW)
    assert result['counts']['forecasts']==2 and result['research_competition']['event_review']['counts']['source_identity_reviewed_forecasts']==1


def test_bootstrap_status_never_claims_partial_counts_are_current_all_source(environment):
    store,index=environment;add(store,'a');add(store,'b',enroll=False)
    index.step(store,as_of=NOW,forecast_verifier=ok,max_records=1)
    result=index.report(as_of=NOW)
    assert result['projection']['status']=='bootstrapping' and not result['projection']['progress']['caught_up']


def test_temporarily_unavailable_original_proof_is_retryable_without_false_publication(environment):
    store,index=environment;add(store)
    def unavailable(*a,**kw):raise FileNotFoundError('CONTROLLED missing original evidence')
    with pytest.raises(FileNotFoundError):index.step(store,as_of=NOW,forecast_verifier=unavailable)
    assert index.report(as_of=NOW)['counts']['forecasts']==0
    index.step(store,as_of=NOW,forecast_verifier=ok)
    assert index.report(as_of=NOW)['research_competition']['event_review']['counts']['source_identity_reviewed_forecasts']==1


def test_existing_cache_cannot_be_rebound_to_a_different_original_archive(environment,tmp_path):
    store,index=environment;add(store);index.step(store,as_of=NOW,forecast_verifier=ok)
    with pytest.raises(ValueError,match='identity mismatch'):
        ResearchIndex(index.path,source_directory=tmp_path/'different-source')
