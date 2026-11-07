"""Controlled engineering fixtures, never genuine model-performance evidence."""
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from hashlib import sha256

import pytest
from neraium_poly.research.phase14.relationships import digest
from neraium_poly.research.phase16.checkpoints import pack_checkpoint
from neraium_poly.research.phase23.competition import (
    aggregate_capacity,
    build_leaderboard,
    challenger_definitions,
)
from neraium_poly.research.phase23.relationships import evaluate_relationships, project_frame

NOW=datetime(2026,11,7,20,tzinfo=UTC)


def frame(at=NOW, *, mid=.5, imbalance=0., sequence=1):
    markets=[];books=[]
    for outcome,token in [('Yes','yes'),('No','no')]:
        m={'id':'market-'+token,'schema_version':'1.0','timestamp':at.isoformat(),'available_at':at.isoformat(),
           'source':'https://gamma-api.polymarket.com','market_id':'m','event_id':'e',
           'question':'CONTROLLED event?','token_id':token,'outcome':outcome,'probability':.5,
           'status':'active','resolution_rules':'CONTROLLED binary rules','resolution_source':'https://example.org/result',
           'end_time':(NOW+timedelta(days=2)).isoformat()}
        b={'id':f'book-{token}-{sequence}','schema_version':'1.0','timestamp':at.isoformat(),'available_at':at.isoformat(),
           'source':'https://clob.polymarket.com','market_id':'m','token_id':token,
           'bids':[{'price':mid-.01,'size':100*(1+imbalance)}],
           'asks':[{'price':mid+.01,'size':100*(1-imbalance)}]}
        markets.append(m);books.append(b)
    return {'id':f'CONTROLLED-{sequence}','available_at':at.isoformat(),'markets':markets,'books':books}


def study(*, identity='f', model='model-1', event='e', at=NOW):
    raw=frame(at);market,book=raw['markets'][0],raw['books'][0];market['event_id']=event
    payload={'CONTROLLED':True};e={'id':'evidence','timestamp':at.isoformat(),'available_at':at.isoformat(),
        'source':'https://example.org/observed','domain':'crypto','provider':'CONTROLLED-provider',
        'source_id':'CONTROLLED-asset','retrieved_at':at.isoformat(),'source_timestamp':at.isoformat(),
        'content_sha256':digest(payload),'payload':payload,'independent_of_polymarket':True,
        'qualification':'qualified_research'}
    f={'id':identity,'model_id':model,'model_version':model,'model_sha256':'a'*64,
       'event_id':event,'market_id':'m','token_id':'yes','probability':.7,'market_probability':.5,
       'timestamp':at.isoformat(),'evidence_cutoff':at.isoformat(),'evidence_ids':['evidence'],
       'rules_sha256':sha256(market['resolution_rules'].encode()).hexdigest(),
       'lower_probability':0.,'upper_probability':1.,'research_only':True,'trading_authority':False}
    definitions=[{'model_id':model,'model_version':model,'model_sha256':'a'*64,'trading_authority':False}]
    state={'code_sha256':'c'*64}
    enrollment_id=digest(['phase23-prospective-research',definitions,state['code_sha256']])
    f['enrollment_id']=enrollment_id
    return {'available_at':at.isoformat(),'operation':'forecast_batch','forecasts':[f],
            'enrollment':definitions,'enrollment_id':enrollment_id,'checkpoint':pack_checkpoint(state),
            'checkpoint_sha256':digest(state),
            'evidence':[e],'market':market,'book':book}


def proof(f):
    return {**{k:f[k] for k in ('event_id','market_id','token_id','rules_sha256')},
        'forecast_id':f['id'],'resolved_at':(NOW+timedelta(days=2)).isoformat(),
        'available_at':(NOW+timedelta(days=2,hours=1)).isoformat(),'outcome':1,
        'verified':True,'reviewed_dependency_group':'CONTROLLED-group','evidence_sha256':'b'*64}


def test_pending_forecasts_have_no_profitability_rank_and_share_source_lineage():
    rows=[study(),study(identity='f2',model='model-2')];before=deepcopy(rows)
    result=build_leaderboard(rows,as_of=NOW)
    assert rows==before
    assert result['counts']['prospective_forecasts']==2
    assert result['counts']['native_parent_events']==1
    assert result['counts']['independent_verified_groups']==0
    assert all(r['metrics'] is None and r['profitability_rank'] is None for r in result['leaderboard'])
    assert result['shared_lineage_models'][0]['independent_confirmations'] is False
    assert not result['trading_authority']


@pytest.mark.parametrize('mutation,reason',[
    ('future','prospective_causal_forecast_time_required'),
    ('payload','causal_independent_source_payload_required'),
    ('rule','original_forecast_market_rule_book_binding_required'),
    ('baseline','same_timestamp_book_baseline_required'),
    ('book','original_forecast_market_rule_book_binding_required'),
    ('authority','research_only_forecast_required'),
])
def test_invalid_forecast_provenance_cannot_enter_leaderboard(mutation,reason):
    row=study();f=row['forecasts'][0]
    if mutation=='future':f['timestamp']=(NOW+timedelta(seconds=1)).isoformat()
    if mutation=='payload':row['evidence'][0]['payload']['CONTROLLED']=False
    if mutation=='rule':f['rules_sha256']='c'*64
    if mutation=='baseline':f['market_probability']=.9
    if mutation=='book':row['book']['timestamp']=(NOW-timedelta(seconds=16)).isoformat()
    if mutation=='authority':f['trading_authority']=True
    r=build_leaderboard([row],as_of=NOW)
    assert r['counts']['prospective_forecasts']==0 and reason in r['rejections']


def test_verified_flag_alone_does_not_create_labels():
    s=study();p=proof(s['forecasts'][0]);r=build_leaderboard([s],[p],as_of=NOW+timedelta(days=3))
    assert r['counts']['independent_verified_groups']==0
    assert r['leaderboard'][0]['metrics'] is None
    assert r['rejections']['independent_outcome_replay_required']==1


def test_replayed_outcomes_are_grouped_before_scoring_and_never_certified():
    s=study();s2=study(identity='later',at=NOW+timedelta(minutes=1));s2['enrollment']=[];p=proof(s['forecasts'][0]);p2=proof(s2['forecasts'][0])
    r=build_leaderboard([s,s2],[p,p2],as_of=NOW+timedelta(days=3),outcome_verifier=lambda p,f:p)
    row=r['leaderboard'][0]
    assert row['independent_verified_events']==1
    assert row['metrics']['brier']==pytest.approx(.09)
    assert row['metrics']['market_brier']==.25
    assert not row['statistically_supported_brier_improvement']
    assert not row['certification_authority']
    assert r['counts']['certified_execution_authorized_challengers']==0


def test_resolution_before_forecast_and_wrong_token_are_rejected():
    s=study();p=proof(s['forecasts'][0]);p['token_id']='other'
    r=build_leaderboard([s],[p],as_of=NOW+timedelta(days=3),outcome_verifier=lambda p,f:p)
    assert not r['counts']['independent_verified_groups']
    p['token_id']='yes';p['resolved_at']=NOW.isoformat()
    r=build_leaderboard([s],[p],as_of=NOW+timedelta(days=3),outcome_verifier=lambda p,f:p)
    assert not r['counts']['independent_verified_groups']


def test_historical_results_are_separate_and_hypotheses_immutable():
    definitions=challenger_definitions(declared_at=NOW)
    assert len(definitions)==7 and len({r['enrollment_sha256'] for r in definitions})==7
    assert all(not r['trading_authority'] for r in definitions)
    r=build_leaderboard([{'operation':'historical_replay'}],as_of=NOW)
    assert r['counts']['historical_exploratory_studies']==1 and not r['leaderboard']


def test_source_projection_is_compact_content_bound_and_causal():
    raw=frame();p=project_frame(raw,cutoff=NOW)
    assert len(p['observations'])==2
    assert p['observations'][0]['imbalance']==0
    assert 'bids' not in p['observations'][0]
    assert digest({k:v for k,v in p.items() if k!='projection_sha256'})==p['projection_sha256']
    raw['books'][0]['timestamp']=(NOW+timedelta(seconds=1)).isoformat()
    assert len(project_frame(raw,cutoff=NOW)['observations'])==1


def test_binary_consistency_observation_is_never_logical_arbitrage_authority():
    r=evaluate_relationships(frame(),[],cutoff=NOW)
    assert len(r['microstructure_observations'])==2
    logical=r['binary_consistency_observations'][0]
    assert logical['buy_both_observed_ask_sum']==1.02
    assert logical['after_cost_edge'] is None
    assert not logical['logical_scope_reviewed'] and not logical['executable_opportunity']


def test_future_and_tampered_history_cannot_enter_relationship_model():
    old=project_frame(frame(NOW-timedelta(minutes=1)),cutoff=NOW-timedelta(minutes=1))
    tampered=deepcopy(old);tampered['observations'][0]['midpoint']=.1
    future=project_frame(frame(NOW+timedelta(minutes=1)),cutoff=NOW+timedelta(minutes=1))
    r=evaluate_relationships(frame(),[old,tampered,future],cutoff=NOW)
    assert r['history_frames_used']==1
    assert r['rejections']['historical_projection_hash_required']==1
    assert r['rejections']['future_relationship_history']==1


def test_persistent_joint_change_requires_nonconstant_baseline_and_source_persistence():
    frames=[]
    for i in range(13):
        at=NOW+timedelta(minutes=i)
        imbalance=((i%5)-2)*.2
        mid=.5+.05*imbalance if i<10 else .7+.05*imbalance
        frames.append(frame(at,mid=mid,imbalance=imbalance,sequence=i))
    history=[project_frame(f,cutoff=NOW+timedelta(minutes=i)) for i,f in enumerate(frames[:-1])]
    r=evaluate_relationships(frames[-1],history,cutoff=NOW+timedelta(minutes=12))
    assert len(r['persistent_relationship_findings'])==2
    f=r['persistent_relationship_findings'][0]
    assert f['persistence_count']==3 and f['baseline_count']==10
    assert not f['forecast_improvement_verified'] and not f['trading_authority']
    flat=[project_frame(frame(NOW+timedelta(minutes=i),sequence=i),cutoff=NOW+timedelta(minutes=i)) for i in range(12)]
    assert not evaluate_relationships(frames[-1],flat,cutoff=NOW+timedelta(minutes=12))['persistent_relationship_findings']


def test_repeated_source_book_is_not_independent_temporal_evidence():
    hist=[project_frame(frame(NOW+timedelta(minutes=i),sequence=1),cutoff=NOW+timedelta(minutes=i)) for i in range(12)]
    r=evaluate_relationships(frame(NOW+timedelta(minutes=12),sequence=1),hist,cutoff=NOW+timedelta(minutes=12))
    assert not r['persistent_relationship_findings']
    assert r['rejections']['prior10_and_current3_distinct_observations_required']==2


def test_capacity_shared_parent_and_unreviewed_groups_are_not_added():
    def row(parent,amount,group=None):
        return {'event_id':parent,'market_id':parent,'reviewed_dependency_group':group,
            'capacity':{'status':'liquidity_only_unqualified','scenarios':[{'hypothetical_bankroll':1000,'modeled_entry_notional':amount}]}}
    rows=[row('a',10),row('a',20),row('b',30)]
    r=aggregate_capacity(rows)['scenarios'][0]
    assert r['parent_capacity_rows']==2 and r['largest_parent_entry_notional']==30
    assert r['reviewed_disjoint_group_liquidity_sum'] is None
    assert r['profitable_deployable_capital'] is None
    rows=[row('a',20,'g1'),row('b',30,'g1'),row('c',15,'g2')]
    r=aggregate_capacity(rows,reviewed_disjoint_groups=['g1','g2'])['scenarios'][0]
    assert r['reviewed_disjoint_group_liquidity_sum']==45


def test_bounds_and_naive_cutoffs_fail_closed():
    with pytest.raises(ValueError):build_leaderboard([],as_of=NOW.replace(tzinfo=None))
    with pytest.raises(ValueError):evaluate_relationships(frame(),[{}]*65,cutoff=NOW)
    with pytest.raises(ValueError):project_frame(frame(),cutoff=NOW,max_tokens=0)


def test_missing_and_postdated_enrollment_rejects_prediction():
    s=study();s['enrollment']=[]
    assert build_leaderboard([s],as_of=NOW)['rejections']['prior_immutable_model_enrollment_required']==1
    s=study();s['enrollment'][0]['model_sha256']='d'*64
    assert not build_leaderboard([s],as_of=NOW)['leaderboard']


def test_conflicting_forecasts_and_outcomes_are_quarantined_not_scored():
    s=study();other=deepcopy(s);other['forecasts'][0]['probability']=.8
    r=build_leaderboard([s,other],as_of=NOW)
    assert not r['counts']['prospective_forecasts']
    p=proof(s['forecasts'][0]);p2={**p,'outcome':0}
    r=build_leaderboard([s],[p,p2],as_of=NOW+timedelta(days=3),outcome_verifier=lambda p,f:p)
    assert r['leaderboard'][0]['metrics'] is None


def test_ternary_sports_predictions_do_not_turn_expected_payout_into_win_baseline():
    s=study();f=s['forecasts'][0];f.update(probability_semantics='outcome_distribution',
        probability=.7,outcome_probabilities={'win':.7,'tie':.02,'loss':.28},expected_payout=.71,
        market_probability=None,market_expected_payout=.5,sports_mapping={'CONTROLLED':True})
    f['source_reference']={'manifest_sha256':'d'*64,'source_lineage':'CONTROLLED-sports',
        'availability_basis':'actual_original_retrieval','artifacts':[{'provider':'CONTROLLED-sports',
        'source_id':'CONTROLLED-schedule','source_url':'https://example.org/games.csv',
        'retrieved_at':NOW.isoformat(),'available_at':NOW.isoformat(),'content_sha256':'e'*64,
        'raw_path':'CONTROLLED-file','quality':'qualified'}]}
    f['evidence_ids']=['d'*64]
    r=build_leaderboard([s],as_of=NOW)
    assert r['counts']['prospective_forecasts']==1
    assert r['leaderboard'][0]['metrics'] is None
    assert 'ternary' in r['leaderboard'][0]['score_semantics']
    p=proof(f);r=build_leaderboard([s],[p],as_of=NOW+timedelta(days=3),outcome_verifier=lambda p,f:p)
    assert not r['counts']['independent_verified_groups']
    f['market_probability']=.5
    assert not build_leaderboard([s],as_of=NOW)['counts']['prospective_forecasts']
