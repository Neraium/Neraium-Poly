"""Controlled evidence only; none of these records is a genuine market forecast."""

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from hashlib import sha256

import pytest
from neraium_poly.contracts import MarketSnapshot, OrderBookSnapshot, PriceLevel
from neraium_poly.research.phase12.contracts import SettlementProofReference, VerifiedEventOutcome
from neraium_poly.research.phase14.contracts import DomainContract, DomainEvidence, DomainForecast
from neraium_poly.research.phase14.relationships import digest
from neraium_poly.research.phase19.qualification import qualification_readiness

START = datetime(2025, 1, 1, tzinfo=UTC)
TRAIN_END = START+timedelta(days=100)
HELD_START = START+timedelta(days=200)
ASOF = START+timedelta(days=500)


def fixtures(i=0, *, heldout=False, parent=None, side="Yes"):
    at = START+timedelta(days=(200 if heldout else 0)+i)
    identity = f"CONTROLLED-{'held' if heldout else 'train'}-{i}-{side}"
    parent = parent or f"CONTROLLED-parent-{'held' if heldout else 'train'}-{i}"
    m = MarketSnapshot(id=identity+'metadata', timestamp=at, available_at=at,
        source="https://gamma-api.polymarket.com", event_id=parent, market_id=identity+'market',
        token_id=identity+'token', question='CONTROLLED terminal event', outcome=side,
        probability=.5, status="active", resolution_rules='CONTROLLED final result rules',
        resolution_source='https://controlled.invalid/results', end_time=at+timedelta(hours=1))
    b = OrderBookSnapshot(id=identity+'book', timestamp=at, available_at=at,
        source='wss://ws-subscriptions-clob.polymarket.com/ws/market', market_id=m.market_id,
        token_id=m.token_id, bids=(PriceLevel(price=.49,size=100),),asks=(PriceLevel(price=.51,size=100),))
    rule=sha256(m.resolution_rules.encode()).hexdigest()
    c = DomainContract(id=identity+'contract', timestamp=at, available_at=at, source='CONTROLLED',
        event_id=parent, market_id=m.market_id, token_id=m.token_id, domain='crypto',
        contract_type='controlled_terminal', probability_semantics='binary_event_probability',
        rules_sha256=rule, parameters={}, compatible=True, review_required=False)
    evidence = DomainEvidence(id=identity+'external', timestamp=at,available_at=at,
        source='https://controlled.invalid', domain='crypto', provider='CONTROLLED', source_id=identity,
        retrieved_at=at, payload={'CONTROLLED':i}, content_sha256=digest({'CONTROLLED':i}),
        independent_of_polymarket=True, qualification='qualified_research')
    f = DomainForecast(id=identity+'forecast',timestamp=at,available_at=at,source='CONTROLLED',
        event_id=parent,market_id=m.market_id,token_id=m.token_id,domain='crypto',
        contract_type=c.contract_type,probability_semantics=c.probability_semantics,probability=.7,
        evidence_cutoff=at, model_version='CONTROLLED-v1',model_sha256='1'*64,
        feature_version='CONTROLLED-features-v1',dataset_sha256='2'*64,rules_sha256=rule,
        evidence_ids=(evidence.id,),uncertainty={'lower_probability':.1,'upper_probability':.9},
        independent_of_polymarket=True,dependency_group='unreviewed:'+parent,
        contemporaneous_market={'market':m.model_dump(mode='json'),'book':b.model_dump(mode='json'),'contract':c.model_dump(mode='json')})
    result={k:getattr(f,k) for k in ['domain','contract_type','event_id','market_id','token_id','rules_sha256','model_version','model_sha256','feature_version','dataset_sha256','probability_semantics','probability','uncertainty']}
    result.update(status='research_estimate',independent_of_polymarket=True,
        evidence_ids=list(f.evidence_ids),evidence_cutoff=at.isoformat())
    original={'id':identity+'study','timestamp':at.isoformat(),'available_at':at.isoformat(),
        'operation':'forecast_scan','forecast':f.model_dump(mode='json'),'market':m.model_dump(mode='json'),
        'book':b.model_dump(mode='json'),'contract':c.model_dump(mode='json'),'model_result':result,
        'evidence':[evidence.model_dump(mode='json')]}
    reference=SettlementProofReference(id=f.id,event_id=parent,market_id=m.market_id,token_id=m.token_id,
        timestamp=at,evidence_cutoff=at,resolution_rules_sha256=rule,original_record_sha256=digest(original['forecast']))
    proof={'forecast_id':f.id,'forecast_sha256':digest(reference.model_dump(mode='json')),
        'market_sha256':digest(m.model_dump(mode='json')),'native':'CONTROLLED','chain':'CONTROLLED'}
    outcome=VerifiedEventOutcome(id=identity+'outcome',timestamp=at+timedelta(hours=1),available_at=at+timedelta(hours=2),
        source='https://polygon-bor-rpc.publicnode.com',event_id=parent,market_id=m.market_id,token_id=m.token_id,
        payout=1,resolution_rules_sha256=rule,settled_at=at+timedelta(hours=1),
        verification_source='native_final_resolution_plus_finalized_ctf_raw_replay',proof_sha256=digest(proof),verification=proof)
    label={'id':identity+'outcomestudy','timestamp':(at+timedelta(hours=3)).isoformat(),
        'available_at':(at+timedelta(hours=3)).isoformat(),'operation':'outcome_check',
        'forecast':deepcopy(original['forecast']),'outcome':outcome.model_dump(mode='json'),
        'model_result':{'status':'native_and_reference_verified','reference_payout':1}}
    return original,label


def evaluate(studies, *, reviewed=False, **overrides):
    callbacks={}
    if reviewed:
        callbacks={'verify_forecast':lambda _s:{'verified':True,'model_training_cutoff':(START-timedelta(days=1)).isoformat()},
            'verify_outcome':lambda _o,_f:True,
            'review_group':lambda s:{'reviewed':True,'dependency_group':s['forecast']['event_id']}}
    return qualification_readiness(studies,as_of=ASOF,training_end=TRAIN_END,heldout_start=HELD_START,**(callbacks|overrides))


def test_empty_snapshot_preserves_gates_and_null_economics():
    r=evaluate([])
    assert r['counts']['original_forecasts']==0 and r['qualified_training_events']==r['qualified_heldout_events']==0
    assert r['required_training_events']==r['required_heldout_events']==100
    assert r['execution_economics']['estimated_net_edge'] is None
    assert not any(r[k] for k in ['trading_authority','certification_authority','experimental_admission_authority'])


def test_own_flags_and_native_shaped_claims_cannot_self_verify():
    original,label=fixtures();r=evaluate([original,label])
    assert r['counts']['original_forecasts']==1 and r['counts']['pending_forecasts']==1
    assert r['counts']['verified_outcome_forecasts']==0 and not r['calibration_rows']
    assert 'independent_forecast_source_replay_required' in r['rejections']
    assert 'independent_native_and_reference_replay_required' in r['rejections']


def test_verified_replay_builds_causal_row_using_final_corroboration_availability():
    original,label=fixtures();before=deepcopy([original,label]);r=evaluate([label,original],reviewed=True)
    assert [original,label]==before
    assert r['counts']['verified_outcome_forecasts']==1 and r['counts']['pending_forecasts']==0
    row=r['calibration_rows'][0]
    assert row['outcome_available_at']==label['available_at']
    assert row['outcome_available_at']!=label['outcome']['available_at']
    assert row['market_probability']==.5 and row['forecast_sha256']==digest(original['forecast'])
    assert row['original_study_sha256']==digest(original)
    assert r['qualified_training_events']==1 and r['qualified_heldout_events']==0
    assert not r['cohort_sufficient'] and r['validation']['cohorts'][0]['calibration']['metrics'] is None


@pytest.mark.parametrize('change,reason',[
    ('forecast_probability','outcome_forecast_not_original'),
    ('outcome_token','outcome_identity_or_rules_mismatch'),
    ('proof_forecast','native_and_reference_bound_outcome_required'),
    ('outcome_rules','outcome_identity_or_rules_mismatch'),
    ('status','native_and_reference_bound_outcome_required'),
])
def test_outcomes_must_bind_exact_original_forecast(change,reason):
    original,label=fixtures()
    if change=='forecast_probability':label['forecast']['probability']=.6
    if change=='outcome_token':label['outcome']['token_id']='CONTROLLED unrelated'
    if change=='outcome_rules':label['outcome']['resolution_rules_sha256']='0'*64
    if change=='status':label['model_result']['status']='temporary_quote'
    if change=='proof_forecast':label['outcome']['verification']['forecast_sha256']='0'*64;label['outcome']['proof_sha256']=digest(label['outcome']['verification'])
    r=evaluate([original,label],reviewed=True)
    assert r['counts']['pending_forecasts']==1 and not r['calibration_rows']
    assert r['rejections'][reason]==1


def test_shared_parent_yes_no_and_repeated_forecasts_count_one_group():
    a,al=fixtures(parent='CONTROLLED shared');b,bl=fixtures(1,parent='CONTROLLED shared',side='No')
    r=evaluate([a,al,b,bl,a,al],reviewed=True)
    assert r['counts']['original_forecasts']==2 and r['counts']['parent_events']==1
    assert r['qualified_training_events']==1
    assert r['validation']['cohorts'][0]['calibration']['rejections']['repeated_dependency_group']==1


def test_parent_on_both_sides_of_split_is_fully_quarantined():
    a,al=fixtures(parent='CONTROLLED cross');b,bl=fixtures(0,heldout=True,parent='CONTROLLED cross')
    r=evaluate([a,al,b,bl],reviewed=True)
    assert r['qualified_training_events']==r['qualified_heldout_events']==0
    assert r['validation']['cross_split_groups']==['CONTROLLED cross']


def test_no_training_cutoff_is_invented_and_online_training_cannot_be_frozen_heldout():
    a,al=fixtures(heldout=True)
    r=evaluate([a,al],reviewed=True,verify_forecast=lambda _s:{'verified':True})
    assert not r['calibration_rows'] and r['rejections']['verified_model_training_cutoff_required']==1
    r=evaluate([a,al],reviewed=True,verify_forecast=lambda _s:{'verified':True,'model_training_cutoff':HELD_START.isoformat()})
    assert r['qualified_heldout_events']==0
    assert r['validation']['rejections']['heldout_model_not_frozen_before_evaluation']==1


def test_cohorts_never_pool_different_models_to_fake_progress():
    a,al=fixtures();b,bl=fixtures(heldout=True)
    b['forecast']['model_version']='CONTROLLED other';b['model_result']['model_version']='CONTROLLED other'
    bl['forecast']=deepcopy(b['forecast'])
    reference=SettlementProofReference(id=b['forecast']['id'],event_id=b['forecast']['event_id'],market_id=b['forecast']['market_id'],token_id=b['forecast']['token_id'],timestamp=HELD_START,evidence_cutoff=HELD_START,resolution_rules_sha256=b['forecast']['rules_sha256'],original_record_sha256=digest(b['forecast']))
    bl['outcome']['verification']['forecast_sha256']=digest(reference.model_dump(mode='json'));bl['outcome']['proof_sha256']=digest(bl['outcome']['verification'])
    r=evaluate([a,al,b,bl],reviewed=True)
    assert len(r['validation']['cohorts'])==2
    assert r['qualified_training_events']+r['qualified_heldout_events']==1
    assert not r['cohort_sufficient']


def test_future_evidence_missing_origin_and_failed_callbacks_are_not_labels():
    a,al=fixtures();r=evaluate([al],reviewed=True)
    assert r['rejections']['outcome_original_forecast_not_in_snapshot']==1
    a['evidence'][0]['available_at']=(START+timedelta(seconds=1)).isoformat()
    r=evaluate([a,al],reviewed=True)
    assert r['counts']['original_forecasts']==0 and not r['calibration_rows']
    def broken(*_args):raise OSError('CONTROLLED unavailable source')
    a,al=fixtures();r=evaluate([a,al],reviewed=True,verify_outcome=broken)
    assert not r['calibration_rows'] and r['counts']['pending_forecasts']==1


def test_contradictory_recorded_outcomes_remain_unresolved():
    a,al=fixtures();other=deepcopy(al);other['id']='CONTROLLED correction';other['outcome']['payout']=0;other['outcome']['id']='CONTROLLED corrected';other['model_result']['reference_payout']=0
    r=evaluate([a,al,other],reviewed=True)
    assert r['counts']['pending_forecasts']==1 and not r['calibration_rows']
    assert r['rejections']['conflicting_recorded_outcome_claims']==1


def test_withheld_and_policy_studies_do_not_become_forecasts():
    at=START.isoformat();rows=[{'timestamp':at,'available_at':at,'operation':'policy_transition'},
        {'timestamp':at,'available_at':at,'operation':'forecast_scan','forecast':None}]
    r=evaluate(rows)
    assert r['counts']['policy_transitions']==1 and r['counts']['withheld_scans']==1
    assert r['counts']['original_forecasts']==0 and not r['calibration_rows']


def test_bounds_and_naive_time_fail_closed():
    with pytest.raises(ValueError,match='bytes'):evaluate([{'huge':'x'*(2*1024**2)}])
    with pytest.raises(ValueError,match='aware'):qualification_readiness([],as_of=ASOF.replace(tzinfo=None),training_end=TRAIN_END,heldout_start=HELD_START)


def test_market_origin_cannot_be_hidden_in_self_declared_independent_evidence():
    a,al=fixtures();a['evidence'][0]['source']='https://clob.polymarket.com'
    r=evaluate([a,al],reviewed=True)
    assert r['counts']['original_forecasts']==0
    assert r['rejections']['independent_external_source_origin_required']==1


def test_future_training_artifact_has_distinct_causal_rejection():
    a,al=fixtures()
    r=evaluate([a,al],reviewed=True,verify_forecast=lambda _s:{'verified':True,
        'model_training_cutoff':(START+timedelta(seconds=1)).isoformat()})
    assert not r['calibration_rows']
    assert r['rejections']['model_training_artifact_after_forecast_cutoff']==1


def test_nonmapping_studies_are_explicitly_rejected():
    with pytest.raises(TypeError,match='canonical_study_mappings'):evaluate([42])


def test_withheld_scan_reasons_and_missing_event_fields_remain_visible():
    at=START.isoformat()
    r=evaluate([{'timestamp':at,'available_at':at,'operation':'forecast_scan','forecast':None,
        'scan':{'rejections':{'stale_book':6,'missing_liquidity':3}},
        'model_result':{'reasons':['CONTROLLED no model inputs']}}])
    assert r['scan_rejections']=={'stale_book':6,'missing_liquidity':3,'CONTROLLED no model inputs':1}
    assert 'no_prospective_independent_forecasts_in_snapshot' in r['blockers']
    assert 'no_independently_verified_terminal_outcomes_in_snapshot' in r['blockers']
    assert r['qualified_training_events']==r['qualified_heldout_events']==0
