"""Controlled evidence fixtures; never authentic forecast or settlement results."""
import json
import sqlite3
from copy import deepcopy
from datetime import UTC, datetime, timedelta

import pytest
from neraium_poly.research.phase14.relationships import digest
from neraium_poly.research.phase24 import evaluation as ev
from neraium_poly.research.phase24 import reconciliation as rec

NOW=datetime(2026,11,7,22,tzinfo=UTC)
START=NOW-timedelta(hours=6)
MAPPING={'league':'NFL','selected_team_id':'JAX','opponent_team_id':'BAL','event_start':START.isoformat(),'game_id':'2026_09_JAX_BAL'}


def html(*,phase='FINAL',home=10,away=33,offset=0,reference=False):
    summary={'phase':phase,'quarter':'END_OF_GAME','homeTeam':{'score':{'total':home}},'awayTeam':{'score':{'total':away}}}
    game={'gameId':'controlled-official-game','gameTime':(START+timedelta(hours=offset)).isoformat(),
        'analyticsProperties':{'gameState':phase},'homeTeam':{'abbreviation':'BAL'},'awayTeam':{'abbreviation':'JAX'},
        'gameSummary':'$b' if reference else summary}
    flight='a:'+json.dumps(game)+'\n'
    if reference:flight+='b:'+json.dumps(summary)+'\n'
    return ('<script>self.__next_f.push('+json.dumps([1,flight])+')</script>').encode()


def forecast():
    return {'id':'controlled-f','model_id':'controlled-model','domain':'sports','event_id':'controlled-parent','market_id':'m','token_id':'t','rules_sha256':'a'*64,
        'timestamp':(START-timedelta(hours=1)).isoformat(),'evidence_cutoff':(START-timedelta(hours=1)).isoformat(),
        'outcome_probabilities':{'win':.6,'tie':.1,'loss':.3},'market_expected_payout':.55,'probability_semantics':'outcome_distribution'}


def test_official_source_exact_final_and_json_reference_replay():
    result=ev.parse_official_nfl(html(reference=True),MAPPING,available_at=NOW)
    assert result['actual']=='win' and result['home_score']==10 and result['away_score']==33
    assert result['official_league_source'] and result['completion_timestamp'] is None
    assert result['includes_overtime']


def test_pending_official_event_is_not_settlement():
    assert ev.parse_official_nfl(html(phase='PREGAME'),MAPPING,available_at=NOW)['status']=='pending'


@pytest.mark.parametrize('change',['time','team','future','large','bad_json','score'])
def test_official_mapping_and_quality_fail_closed(change):
    mapping=deepcopy(MAPPING);body=html();now=NOW
    if change=='time':body=html(offset=1)
    elif change=='team':mapping['selected_team_id']='CIN'
    elif change=='future':now=START-timedelta(seconds=1)
    elif change=='large':body=b'x'*(ev.MAX_BYTES+1)
    elif change=='bad_json':body=b'<script>evil_not_json()</script>'
    else:body=html(home='10')
    with pytest.raises(ValueError):ev.parse_official_nfl(body,mapping,available_at=now)


def test_ternary_tie_score_preserves_expected_payout_semantics():
    f=forecast();scores=ev.score_ternary(f,'tie')
    assert scores['observed_payout']==.5 and scores['expected_payout']==pytest.approx(.65)
    assert scores['expected_payout_mse']==pytest.approx(.15**2)
    assert scores['market_expected_payout_mse']==pytest.approx(.05**2)
    assert scores['market_binary_brier'] is None and scores['market_ternary_baseline'] is None
    assert scores['ternary_brier']==pytest.approx(.6**2+.9**2+.3**2)


def test_zero_likelihood_is_infinite_logloss_not_clipped_success():
    f=forecast();f['outcome_probabilities']={'win':.7,'tie':0.,'loss':.3}
    score=ev.score_ternary(f,'tie')
    assert score['log_loss'] is None and score['log_loss_status']=='positive_infinity'


async def test_unstarted_original_never_fetches_or_forces_a_result(monkeypatch,tmp_path):
    mapping={**MAPPING,'event_start':(NOW+timedelta(hours=1)).isoformat()}
    monkeypatch.setattr(ev,'_original',lambda *a,**kw:(None,mapping,None))
    result=await ev.acquire_nfl_outcome({},forecast(),directory=tmp_path/'uncreated',clock=lambda:NOW)
    assert result['status']=='pending' and not (tmp_path/'uncreated').exists()


def test_asserted_verified_flags_do_not_create_evaluation_scores():
    f=forecast();result=ev.evaluate([{'forecasts':[f]}],[{'forecast_id':f['id'],'verified':True}],as_of=NOW)
    assert result['counts']['individually_verified_forecasts']==0
    assert result['leaderboard'][0]['metrics'] is None and result['leaderboard'][0]['profitability_rank'] is None


def test_verified_descriptive_scoring_stays_outside_independence_and_certification():
    f=forecast()
    def verifier(row,original):
        return {'verified':True,'forecast_id':original['id'],**{k:original[k] for k in ['event_id','market_id','token_id','rules_sha256']},
            'resolved_at':NOW.isoformat(),'available_at':NOW.isoformat(),'scores':ev.score_ternary(original,row['actual'])}
    result=ev.evaluate([{'forecasts':[f]}],[{'forecast_id':f['id'],'actual':'win'}],as_of=NOW,outcome_verifier=verifier)
    assert result['counts']['individually_verified_forecasts']==1
    assert result['counts']['reviewed_independent_groups']==0
    assert result['leaderboard'][0]['calibration'] is None and not result['trading_authority']
    contradictory=ev.evaluate([{'forecasts':[f]}],[{'forecast_id':f['id'],'actual':'win'},{'forecast_id':f['id'],'actual':'loss'}],as_of=NOW,outcome_verifier=verifier)
    assert contradictory['counts']['individually_verified_forecasts']==0


def test_new_conditional_domain_forecasts_remain_pending_without_labels():
    f=forecast();f['probability_semantics']='conditional_on_no_tie';f['unconditional_contract_probability']=False
    result=ev.evaluate([{'forecasts':[f]}],as_of=NOW)
    assert result['counts']['pending_forecasts']==1 and result['leaderboard'][0]['metrics'] is None


def inventory(monkeypatch,tmp_path,*,missing=False,changed=False):
    records=[]
    for i in range(24):
        f={'id':f'old-{i}','timestamp':NOW.isoformat(),'event_id':f'crypto-{i%2}','market_id':str(i),'token_id':str(i),'model_version':'old-model'}
        records.append(('EventProbabilityStudy',{'id':f'study-{i}','available_at':NOW.isoformat(),'operation':'forecast_scan','forecast':f}))
    fs=[{'id':f'new-{i}','timestamp':NOW.isoformat(),'event_id':f'parent-{i%8}','market_id':str(i),'token_id':str(i),'model_id':'new-model','probability':.4} for i in range(18)]
    records.append(('ChallengerStudy',{'id':'new-study','available_at':NOW.isoformat(),'operation':'forecast_batch','forecasts':fs}))
    refs=tmp_path/'refs';(refs/'phase22-evidence').mkdir(parents=True);(refs/'phase23').mkdir()
    crypto=[{'forecast_id':r['forecast']['id'],'original_study_sha256':digest(r)} for k,r in records if k=='EventProbabilityStudy']
    old_sports=[{'id':f'nfl-{i}','timestamp':NOW.isoformat(),'mapping':{'event_id':f'nfl-parent-{i}','market_id':f'nm-{i}','token_id':f'nt-{i}'},'prediction':{'model_version':'old-nfl'}} for i in range(8)]
    sports=[rec._entry(f,'phase13_nfl',f['id'],digest(f)) for f in old_sports]
    (refs/'phase22-evidence/forecast-audit.json').write_text(json.dumps({'crypto':crypto,'sports':[{'forecast_id':f['id']} for f in old_sports[:3]],'sports_journal_records':3,'sports_journal_head_sha256':'b'*64}))
    (refs/'phase23/forecasts-final.json').write_text(json.dumps({'forecast_rows':[{'id':f['id'],'probability':f['probability'],'timestamp':f['timestamp']} for f in fs]}))
    if missing:records.pop(0)
    if changed:records[-1][1]['forecasts'][0]['probability']=.9
    class Archive:
        def __init__(self,*a,**kw):pass
        def __enter__(self):return self
        def __exit__(self,*a):pass
        def _catalog_rows(self,sql,args):return [{'id':r['id']} for k,r in records if k==args[0]]
        def _fetch(self,row):
            k,r=next((k,r) for k,r in records if r['id']==row['id']);raw=json.dumps(r);return k,raw,digest(r)
    monkeypatch.setattr(rec,'ReadonlyArchive',Archive)
    monkeypatch.setattr(rec,'_replay_archive',lambda *a:None)
    monkeypatch.setattr(rec,'_sports_journal',lambda *a:(sports,{'status':'verified','prefix_heads':{'3':'b'*64}}))
    return refs


def test_27_versus_18_are_distinct_preserved_scopes_plus_five_extra_legacy(monkeypatch,tmp_path):
    refs=inventory(monkeypatch,tmp_path)
    r=rec.reconcile(tmp_path,as_of=NOW,reference_directory=refs)
    assert r['scope_counts']=={'phase18_crypto':24,'phase23_challengers':18,'phase13_nfl':8}
    assert r['total_original_forecasts']==50 and r['additional_legacy_nfl_since_reported_three']==5
    assert r['preservation_witnesses']['phase22_reported_27']['preserved']==27
    assert r['preservation_witnesses']['phase23_reported_18']['preserved']==18
    assert r['reviewed_independent_event_groups']==0 and not r['trading_authority']


@pytest.mark.parametrize('change',['missing','changed'])
def test_missing_or_changed_originals_never_reconstructed(monkeypatch,tmp_path,change):
    refs=inventory(monkeypatch,tmp_path,**{change:True})
    with pytest.raises(ValueError):rec.reconcile(tmp_path,as_of=NOW,reference_directory=refs)


def test_sports_journal_tampering_and_naive_cutoffs_rejected(tmp_path):
    p=tmp_path/'event-intelligence/sports';p.mkdir(parents=True)
    c=sqlite3.connect(p/'prospective.sqlite');c.execute('CREATE TABLE records(seq INTEGER,kind TEXT,id TEXT,payload TEXT,digest TEXT,previous TEXT,chain TEXT)')
    c.execute('INSERT INTO records VALUES (1,?,?,?,?,?,?)',('note','bad','{}','0'*64,None,'0'*64));c.commit();c.close()
    with pytest.raises(ValueError,match='integrity'):rec._sports_journal(tmp_path,NOW)
    with pytest.raises(ValueError,match='aware'):rec.reconcile(tmp_path,as_of=datetime(2026,11,7))


def native_envelope(tmp_path,monkeypatch,*,payout=1):
    import hashlib

    from neraium_poly.research.phase12.contracts import VerifiedEventOutcome
    f=forecast();raw=html();path=tmp_path/'controlled-official.html';path.write_bytes(raw)
    official=ev.parse_official_nfl(raw,MAPPING,available_at=NOW)
    outcome=VerifiedEventOutcome(id='controlled-native',timestamp=NOW,available_at=NOW,source='controlled-native-boundary',
        event_id=f['event_id'],market_id=f['market_id'],token_id=f['token_id'],payout=payout,
        resolution_rules_sha256=f['rules_sha256'],settled_at=NOW,verification_source='controlled-only',proof_sha256='f'*64,verification={})
    result={'status':'verified','forecast_id':f['id'],'available_at':NOW.isoformat(),
        'official_evidence':{'source_url':ev._url(MAPPING),'retrieved_at':NOW.isoformat(),'available_at':NOW.isoformat(),
            'raw_file':path.name,'content_sha256':hashlib.sha256(raw).hexdigest()},
        'official_result':official,'native_outcome':outcome.model_dump(mode='json')}
    monkeypatch.setattr(ev,'_original',lambda *a,**kw:(None,MAPPING,None))
    return f,result,path


def test_official_result_and_native_proof_required_before_scoring(tmp_path,monkeypatch):
    f,result,_=native_envelope(tmp_path,monkeypatch)
    monkeypatch.setattr(ev,'verify_collected_outcome',lambda *a:False)
    with pytest.raises(ValueError,match='native'):ev.replay_nfl_outcome(result,{},f,evidence_root=tmp_path,as_of=NOW)
    monkeypatch.setattr(ev,'verify_collected_outcome',lambda *a:True) # Controlled proof boundary, not genuine settlement.
    score=ev.replay_nfl_outcome(result,{},f,evidence_root=tmp_path,as_of=NOW)
    assert score['verified'] and score['scores']['market_binary_brier'] is None
    assert score['reviewed_dependency_group'] is None and not score['trading_authority']


def test_disagreement_corruption_and_path_escape_never_score(tmp_path,monkeypatch):
    f,result,path=native_envelope(tmp_path,monkeypatch,payout=0)
    monkeypatch.setattr(ev,'verify_collected_outcome',lambda *a:True)
    with pytest.raises(ValueError,match='disagree'):ev.replay_nfl_outcome(result,{},f,evidence_root=tmp_path,as_of=NOW)
    result['native_outcome']['payout']=1;path.write_bytes(b'CONTROLLED corruption')
    with pytest.raises(ValueError,match='hash'):ev.replay_nfl_outcome(result,{},f,evidence_root=tmp_path,as_of=NOW)
    result['official_evidence']['raw_file']='../escape.html'
    with pytest.raises(ValueError,match='escape'):ev.replay_nfl_outcome(result,{},f,evidence_root=tmp_path,as_of=NOW)
