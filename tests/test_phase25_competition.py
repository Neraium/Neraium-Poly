"""Controlled engineering fixtures; none represent authentic research evidence."""

import hashlib
from copy import deepcopy
from datetime import UTC, datetime, timedelta

import pytest
from neraium_poly.contracts import OrderBookSnapshot, PriceLevel
from neraium_poly.research.phase14.relationships import digest
from neraium_poly.research.phase25.competition import competition_report, executable_diagnostic
from neraium_poly.research.phase25.dependencies import canonical_event, review_events

NOW = datetime(2026, 11, 7, 23, tzinfo=UTC)
END = NOW + timedelta(hours=2)


def fixture(identity='controlled', *, parent='parent', model='baseline'):
    rules='CONTROLLED exact final game rule; these observations are synthetic.'
    book=OrderBookSnapshot(id='controlled-book',timestamp=NOW,available_at=NOW,
        source='https://clob.polymarket.com',market_id='market',token_id='token',
        bids=(PriceLevel(price=.4,size=100),),asks=(PriceLevel(price=.41,size=100),))
    f={'id':identity,'domain':'sports','league':'NHL','model_id':model,'model_version':model,'model_sha256':'a'*64,
       'feature_version':'controlled','event_id':parent,'market_id':'market','token_id':'token','probability':.6,
       'probability_semantics':'binary_event_probability','target_conditioning':'official_completed_game',
       'lower_probability':0.,'upper_probability':1.,'timestamp':NOW.isoformat(),'evidence_cutoff':NOW.isoformat(),
       'event_end_time':END.isoformat(),'source_game_id':'game-A','source_lineages':['CONTROLLED:publisher'],
       'contract':{'parameters':{'participants':['Club-A','Club-B'],'scheduled_start':END.isoformat()}},
       'market':{'event_id':parent,'market_id':'market','token_id':'token','resolution_rules':rules,
                 'resolution_source':'https://official.example/result','available_at':NOW.isoformat(),'min_order_size':5},
       'rules_sha256':hashlib.sha256(rules.encode()).hexdigest(),'book':book.model_dump(mode='json'),'book_id':book.id,
       'book_sha256':digest(book.model_dump(mode='json')),'research_only':True,'trading_authority':False,'certification_authority':False}
    s={'id':'study-'+identity,'timestamp':NOW.isoformat(),'available_at':NOW.isoformat(),'forecasts':[f]}
    return s,f


def verified(*args,**kwargs):return {'verified':True}


def test_identity_review_needs_independent_replay_not_a_recorded_flag():
    s,f=fixture();f['source_model_replay_verified']=True
    r=review_events([s],as_of=NOW)
    assert r['counts']['reviewed_canonical_groups']==0 and 'independently_replayed_source_model_required' in r['rejections']
    r=review_events([s],as_of=NOW,forecast_verifier=verified)
    assert r['counts']['reviewed_canonical_groups']==1 and r['counts']['statistically_independent_events']==0
    assert r['counts']['certification_independent_events']==0 and not r['certification_authority']


def test_same_source_event_cross_parent_and_model_never_increases_group_count():
    a,_=fixture();b,_=fixture('other',parent='other-parent',model='challenger')
    r=review_events([a,b],as_of=NOW,forecast_verifier=verified)
    assert r['counts']['native_parent_ids']==2 and r['counts']['reviewed_canonical_groups']==1
    assert r['groups'][0]['forecasts']==2


def test_shared_team_creates_risk_cluster_not_causal_or_independence_claim():
    a,_=fixture();b,f=fixture('other',parent='other-parent')
    f['source_game_id']='game-B';f['contract']['parameters']['participants']=['Club-A','Club-C']
    r=review_events([a,b],as_of=NOW,forecast_verifier=verified)
    assert r['counts']['reviewed_canonical_groups']==2 and r['counts']['conservative_dependency_clusters']==1
    assert r['counts']['statistically_independent_events']==0
    assert r['shared_evidence_lineages'][0]['lineage']=='CONTROLLED:publisher'


def test_conflicting_source_game_identity_quarantines_both():
    a,_=fixture();b,f=fixture('other',parent='other-parent');f['contract']['parameters']['participants']=['Club-C','Club-D']
    r=review_events([a,b],as_of=NOW,forecast_verifier=verified)
    assert r['counts']['reviewed_canonical_groups']==0 and r['rejections']['conflicting_source_game_identity']==1


@pytest.mark.parametrize('fault',['future_source','late_commit','wrong_token','wrong_rules','conflicting_forecast','authority'])
def test_temporal_identity_and_duplicate_conflicts_fail_closed(fault):
    a,f=fixture();studies=[a]
    if fault=='future_source':f['evidence_cutoff']=(NOW+timedelta(seconds=1)).isoformat()
    elif fault=='late_commit':a['available_at']=END.isoformat()
    elif fault=='wrong_token':f['market']['token_id']='not-token'
    elif fault=='wrong_rules':f['rules_sha256']='b'*64
    elif fault=='authority':f['trading_authority']=True
    else:
        b=deepcopy(a);b['forecasts'][0]['probability']=.9;studies.append(b)
    r=review_events(studies,as_of=END+timedelta(hours=1),forecast_verifier=verified)
    assert r['counts']['reviewed_canonical_groups']==0


def test_weather_bins_merge_exact_station_day_across_market_parents():
    _a,f=fixture();f['domain']='weather';f['contract']={'station':'ZUCK','day':'2026-11-07','timezone':'Asia/Shanghai',
        'period_start':'2026-11-06T16:00:00+00:00','period_end':'2026-11-07T16:00:00+00:00','threshold':15}
    first=canonical_event(f)[1];f['contract']['threshold']=16;f['event_id']='another-parent'
    assert canonical_event(f)[1]==first
    f['contract']['period_start']='2026-11-06T15:00:00+00:00'
    with pytest.raises(ValueError):canonical_event(f)


def test_crypto_nested_thresholds_share_reference_window_group():
    _,f=fixture();f['domain']='crypto';f['contract']={'parameters':{'symbol':'BTCUSDT',
        'period_start_utc':NOW.isoformat(),'period_end_utc':END.isoformat(),'threshold':100}}
    first=canonical_event(f)[1];f['contract']['parameters']['threshold']=200
    assert canonical_event(f)[1]==first
    f['contract']['parameters']['symbol']='ETHUSDT'
    assert canonical_event(f)[1]!=first


def test_economic_series_period_and_financial_reference_are_exact():
    _,f=fixture();f['domain']='economics';f['contract']={'series_id':'ONS:IHYQ','target_period':'2026 Q3'}
    first=canonical_event(f)[1];f['contract']['target_period']='2026 Q4';assert canonical_event(f)[1]!=first
    f['domain']='finance';f['contract']={'symbol':'SPX','reference_source':'https://www.wsj.com/market-data/stocks',
        'period_start':NOW.isoformat(),'period_end':END.isoformat(),'settlement_at':END.isoformat()}
    first=canonical_event(f)[1];f['contract']['reference_source']='https://fred.stlouisfed.org';assert canonical_event(f)[1]!=first


def test_same_cohort_disagreement_is_not_an_ensemble_or_profitability_rank():
    a,_=fixture();b,f=fixture('other',model='challenger');f['probability']=.8
    r=competition_report([a,b],as_of=NOW,forecast_verifier=verified)
    assert r['same_cohort_disagreements'][0]['probability_range']==pytest.approx(.2)
    assert r['same_cohort_disagreements'][0]['independent_confirmation_count'] is None
    assert r['ensemble']['weights'] is None and r['performance']['counts']['individually_verified_forecasts']==0
    assert all(row['profitability_rank'] is None for row in r['performance']['leaderboard'])


@pytest.mark.parametrize('fault',['timestamp','cutoff','book','conditioning','token'])
def test_unmatched_time_book_or_target_never_produces_paired_disagreement(fault):
    a,_=fixture();b,f=fixture('other',model='challenger')
    if fault=='timestamp':f['timestamp']=(NOW-timedelta(seconds=1)).isoformat();f['evidence_cutoff']=f['timestamp'];f['market']['available_at']=f['timestamp']
    elif fault=='cutoff':f['evidence_cutoff']=(NOW-timedelta(seconds=1)).isoformat();f['market']['available_at']=f['evidence_cutoff']
    elif fault=='book':f['book_sha256']='b'*64
    elif fault=='conditioning':f['target_conditioning']='different-conditional-target'
    else:f['token_id']='other-token';f['market']['token_id']='other-token'
    r=competition_report([a,b],as_of=NOW,forecast_verifier=verified)
    assert not r['same_cohort_disagreements'] and not r['sii']['resolved_pairs']


def test_sii_stored_feature_flag_cannot_qualify_experiment_without_pure_replay():
    a,f=fixture();b,g=fixture('other',model='challenger')
    f['sii_experiment']={'variant':'without_sii','experiment_id':'controlled-experiment'}
    g['sii_experiment']={'variant':'with_sii','experiment_id':'controlled-experiment','baseline_model_id':'baseline','baseline_model_sha256':'a'*64,'verified':True}
    r=competition_report([a,b],as_of=NOW,forecast_verifier=verified)
    assert r['sii']['candidate_exact_pairs']==1 and r['sii']['qualified_pairs']==0 and r['sii']['incremental_predictive_value'] is None


def test_conditional_forecast_only_yields_liquidity_not_edge_or_admission():
    _,f=fixture();r=executable_diagnostic(f,evaluated_at=NOW,forecast_verified=True)
    assert r['status']=='withheld' and r['capacity']['status']=='liquidity_only_unqualified'
    assert r['estimated_net_edge'] is None and not r['execution_authorized']
    assert all(row['conditional_expected_net_value'] is None for row in r['capacity']['scenarios'])


def test_stored_cost_flag_alone_never_creates_executable_edge():
    _,f=fixture();f.pop('target_conditioning')
    r=executable_diagnostic(f,evaluated_at=NOW,forecast_verified=True,cost_evidence={'independently_verified':True})
    assert r['status']=='withheld' and 'independently_verified_decision_cost_and_calibration_evidence_required' in r['reasons']


def test_future_or_stale_book_cannot_produce_depth_capacity():
    _,f=fixture()
    r=executable_diagnostic(f,evaluated_at=NOW+timedelta(seconds=16),forecast_verified=True)
    assert r['status']=='withheld' and r['capacity'] is None


def test_controlled_qualified_cost_diagnostic_keeps_partial_fills_and_no_authority():
    _,f=fixture();f.pop('target_conditioning');f.update(probability=.85,lower_probability=.8,upper_probability=.9)
    costs={'forecast_id':f['id'],'book_sha256':f['book_sha256'],'available_at':NOW.isoformat(),
           'calibration_cutoff':NOW.isoformat(),'calibration_artifact_sha256':'c'*64,
           'calibration_verified':True,'event_disjoint_calibration_verified':True,'fee_rate':0.,
           'slippage_per_share':.01,'latency_adverse_selection_per_share':.005,
           'capital_lockup_cost_per_share':.003,'settlement_risk_cost_per_share':.002}
    result=executable_diagnostic(f,evaluated_at=NOW,forecast_verified=True,cost_evidence=costs,cost_verifier=verified)
    assert result['status']=='qualified_research_diagnostic' and result['estimated_net_edge']==pytest.approx(.37)
    assert result['capacity']['status']=='qualified_research_capacity'
    assert all(row['partial_depth'] for row in result['capacity']['scenarios'])
    assert result['capacity']['net_pnl'] is None and not result['execution_authorized'] and not result['trading_authority']
    costs['calibration_cutoff']=(NOW+timedelta(seconds=1)).isoformat()
    assert executable_diagnostic(f,evaluated_at=NOW,forecast_verified=True,cost_evidence=costs,cost_verifier=verified)['status']=='withheld'


def test_unavailable_raw_source_withholds_review_instead_of_inventing_identity():
    s,_=fixture()
    def missing(*args,**kwargs):raise FileNotFoundError('controlled missing original raw source')
    result=review_events([s],as_of=NOW,forecast_verifier=missing)
    assert result['counts']['reviewed_canonical_groups']==0
    assert result['rejections']['controlled missing original raw source']==1
