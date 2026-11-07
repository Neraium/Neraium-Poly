"""Controlled fixtures exercise engineering; never authentic research evidence."""

from copy import deepcopy
from datetime import timedelta

import pytest
from neraium_poly.research.phase14.relationships import digest
from neraium_poly.research.phase20.ab import declare_experiment, evaluate_pairs, prospective_pair
from test_phase19_qualification import ASOF, START, fixtures


def setup_pair(i=0, parent=None, *, market_features=False):
    original, label = fixtures(i, parent=parent)
    f = original['forecast']
    at = START+timedelta(days=i)
    spec = declare_experiment(experiment_id='CONTROLLED-p20', declared_at=START-timedelta(days=1),
        heldout_start=START, baseline_model_sha256='1'*64, challenger_model_sha256='3'*64,
        challenger_feature_version='CONTROLLED-sii-v1', execution_assumptions={'fees':'CONTROLLED'})
    features = {'engine_version':'universal-joint-relationship-v1','engine_sha256':'4'*64,
        'persistent':True,'classification':'persistent_statistical_relationship_change','persistence_count':3,
        'baseline_cutoff':(at-timedelta(minutes=10)).isoformat(),
        'persistence_since':(at-timedelta(minutes=2)).isoformat(),
        'evaluated_at':at.isoformat(),'available_at':at.isoformat(),
        'definition_sha256':'5'*64,'uncertainty':'CONTROLLED',
        'evidence_sha256':[digest(['test-evidence',j]) for j in range(2)],
        'baseline_evidence_sha256':[digest(['test-baseline',j]) for j in range(10)],
        'current_window_evidence_sha256':[digest(['test-window',j]) for j in range(3)]}
    challenger = {'experiment_sha256':spec['manifest_sha256'],'forecast_sha256':digest(f),
        'features_sha256':digest(features),'model_sha256':'3'*64,'feature_version':'CONTROLLED-sii-v1',
        'timestamp':f['timestamp'],'evidence_cutoff':f['evidence_cutoff'],
        'event_id':f['event_id'],'market_id':f['market_id'],'token_id':f['token_id'],
        'rules_sha256':f['rules_sha256'],'probability':.8,
        'trained_at':(START-timedelta(days=2)).isoformat(),'available_at':(at+timedelta(milliseconds=1)).isoformat()}
    kwargs = {'experiment':spec,'now':at+timedelta(seconds=1),'sii_features':features,'challenger':challenger,
        'verify_forecast':lambda s:{'verified':True},
        'verify_features':lambda fs:{'verified':True,'uses_market_features':market_features},
        'verify_challenger':lambda c,s,fs:True}
    return original, label, kwargs


def score(pairs, originals, labels, spec, **overrides):
    return evaluate_pairs(pairs,originals,labels,experiment=spec,as_of=ASOF,
        **({'verify_pair':lambda p:True,'verify_forecast':lambda s:{'verified':True},
            'verify_outcome':lambda s,o:True,
            'review_group':lambda s:{'reviewed':True,'dependency_group':s['forecast']['event_id']}}|overrides))


def test_manifest_is_frozen_and_cannot_grant_authority():
    o,_l,k=setup_pair();before=deepcopy(k['experiment'])
    r=prospective_pair(o,**k)
    assert k['experiment']==before and r['status']=='paired_research'
    spec=deepcopy(k['experiment']);spec['trading_authority']=True
    with pytest.raises(ValueError,match='integrity'):prospective_pair(o,**(k|{'experiment':spec}))
    spec['manifest_sha256']=digest({x:v for x,v in spec.items() if x!='manifest_sha256'})
    with pytest.raises(ValueError,match='policy'):prospective_pair(o,**(k|{'experiment':spec}))


def test_no_challenger_never_fabricates_probability_or_scores():
    o,l,k=setup_pair()
    spec=declare_experiment(experiment_id='CONTROLLED-withheld',declared_at=START-timedelta(days=1),
        heldout_start=START,baseline_model_sha256='1'*64)
    r=prospective_pair(o,experiment=spec,now=k['now'],verify_forecast=k['verify_forecast'])
    assert r['status']=='withheld' and r['pair'] is None
    assert r['reasons']==['frozen_trained_sii_challenger_unavailable']
    assert r['enrollment']['forecast_id']==o['forecast']['id'] and r['enrollment']['book_sha256']==digest(o['book'])
    report=score([r],[o],[l],spec)
    assert report['metrics'] is None and report['verified_independent_groups']==0
    assert report['after_cost_edge'] is report['simulated_returns'] is None
    assert not report['incremental_sii_skill_supported']


@pytest.mark.parametrize('change,reason',[
    ('prospective','prospective_predeclared_event_enrollment_required'),
    ('model','predeclared_baseline_model_mismatch'),
    ('source','original_independent_forecast_replay_required'),
    ('persistence','qualified_persistent_sii_relationship_required'),
    ('availability','causal_sii_baseline_persistence_and_availability_required'),
    ('time','causal_sii_baseline_persistence_and_availability_required'),
    ('duplicate','distinct_causal_sii_lineage_required'),
    ('feature_replay','independent_sii_raw_lineage_replay_required'),
    ('challenger','same_cutoff_event_rule_and_frozen_challenger_binding_required'),
    ('untrained','predeclared_frozen_challenger_artifact_required'),
    ('replay','independent_frozen_challenger_replay_required'),
])
def test_pair_denies_leakage_invented_coefficients_and_unreplayed_sources(change,reason):
    o,_l,k=setup_pair()
    if change=='prospective':k['now']=START+timedelta(hours=2)
    if change=='model':
        spec=k['experiment'];spec['baseline_model_sha256']='9'*64
        spec['manifest_sha256']=digest({x:v for x,v in spec.items() if x!='manifest_sha256'})
    if change=='source':k['verify_forecast']=None
    if change=='persistence':k['sii_features']['persistence_count']=2
    if change=='availability':k['sii_features']['available_at']=(START+timedelta(seconds=1)).isoformat()
    if change=='time':k['sii_features']['persistence_since']=(START-timedelta(seconds=20)).isoformat()
    if change=='duplicate':k['sii_features']['current_window_evidence_sha256']=['1'*64]*3
    if change=='feature_replay':k['verify_features']=None
    if change=='challenger':k['challenger']['token_id']='CONTROLLED wrongtoken'
    if change=='untrained':k['challenger']['trained_at']=START.isoformat()
    if change=='replay':k['verify_challenger']=None
    r=prospective_pair(o,**k)
    assert r['status']=='withheld' and r['pair'] is None and r['reasons']==[reason]


def test_market_informed_sii_is_not_labeled_independent():
    o,_l,k=setup_pair(market_features=True)
    r=prospective_pair(o,**k)
    assert r['status']=='paired_research'
    assert r['pair']['baseline_independent_of_market'] and not r['pair']['sii_independent_of_market']


def test_native_outcomes_callbacks_and_prospective_pair_replay_default_deny():
    o,l,k=setup_pair();p=prospective_pair(o,**k)
    result=evaluate_pairs([p],[o],[l],experiment=k['experiment'],as_of=ASOF)
    assert result['metrics'] is None and result['rejections']=={'independent_prospective_pair_replay_required':1}
    r=score([p],[o],[l],k['experiment'],verify_outcome=None)
    assert r['metrics'] is None and r['rejections']=={'independently_verified_terminal_outcome_pending':1}


def test_paired_scoring_equal_event_groups_and_same_timestamp_market_baseline():
    a,al,k=setup_pair();p=prospective_pair(a,**k)
    before=deepcopy([a,al,p]);r=score([p],[a],[al],k['experiment'])
    assert [a,al,p]==before
    assert r['verified_independent_groups']==1
    metrics=r['metrics']
    assert metrics['baseline']['brier']==pytest.approx(.09)
    assert metrics['with_sii']['brier']==pytest.approx(.04)
    assert metrics['market']['brier']==pytest.approx(.25)
    assert metrics['with_sii']['log_loss']==pytest.approx(-__import__('math').log(.8))
    assert metrics['comparisons']['sii_minus_baseline']['paired_brier_difference']==pytest.approx(-.05)
    assert metrics['comparisons']['sii_minus_baseline']['simultaneous_95_bound']==[-1.,1.]
    assert not r['incremental_sii_skill_supported']
    assert r['after_cost_edge'] is r['simulated_returns'] is r['risk_adjusted_returns'] is None


def test_same_parent_multiple_markets_and_updates_do_not_inflate_independent_events():
    a,al,k=setup_pair(parent='CONTROLLED shared');b,bl,bk=setup_pair(1,parent='CONTROLLED shared')
    p,q=prospective_pair(a,**k),prospective_pair(b,**bk)
    r=score([p,q,p],[a,b],[al,bl],k['experiment'])
    assert r['verified_independent_groups']==1
    assert r['rejections']=={'duplicate_pair_record':1,'repeated_dependency_group_not_independent':1}


def test_training_group_cannot_be_heldout_and_false_native_outcome_not_scored():
    a,al,k=setup_pair()
    spec=k['experiment'];spec['training_groups']=[a['forecast']['event_id']]
    spec['manifest_sha256']=digest({x:v for x,v in spec.items() if x!='manifest_sha256'})
    k['challenger']['experiment_sha256']=spec['manifest_sha256']
    p=prospective_pair(a,**k);r=score([p],[a],[al],spec)
    assert r['metrics'] is None and r['rejections']=={'heldout_event_group_in_training':1}
    a,al,k=setup_pair();p=prospective_pair(a,**k)
    al['outcome']['token_id']='CONTROLLED unrelated'
    r=score([p],[a],[al],k['experiment'])
    assert r['metrics'] is None and 'outcome_identity_or_rules_mismatch' in r['rejections']


def test_wrong_side_zero_probability_reports_infinite_loss_not_finite_clipping():
    a,al,k=setup_pair();k['challenger']['probability']=0.
    p=prospective_pair(a,**k);r=score([p],[a],[al],k['experiment'])
    assert r['metrics']['with_sii']['log_loss'] is None
    assert r['metrics']['with_sii']['log_loss_status']=='positive_infinity'


def test_conflicting_outcomes_and_forged_pair_context_remain_unresolved():
    a,al,k=setup_pair();p=prospective_pair(a,**k)
    wrong=deepcopy(al);wrong['outcome']['payout']=0
    wrong['model_result']['reference_payout']=0
    r=score([p],[a],[al,wrong],k['experiment'])
    assert r['metrics'] is None and r['rejections']=={'conflicting_outcomes_preserve_unresolved':1}
    p['pair']['market_probability']=.9
    p['record_sha256']=digest({x:v for x,v in p.items() if x!='record_sha256'})
    r=score([p],[a],[al],k['experiment'])
    assert r['metrics'] is None and r['rejections']=={'same_prospective_cutoff_original_event_required':1}


def test_earliest_pair_is_selected_before_outcome_availability():
    a,_al,k=setup_pair(parent='CONTROLLED shared');b,bl,bk=setup_pair(1,parent='CONTROLLED shared')
    p,q=prospective_pair(a,**k),prospective_pair(b,**bk)
    r=score([q,p],[a,b],[bl],k['experiment'])
    assert r['metrics'] is None and r['verified_independent_groups']==0
    assert r['rejections']['independently_verified_terminal_outcome_pending']==1
