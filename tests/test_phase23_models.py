"""Controlled engineering fixtures; never authentic forecasts or performance."""
import asyncio
from copy import deepcopy
from datetime import UTC, datetime, timedelta

import pytest
from neraium_poly.data import EventStore
from neraium_poly.research.phase23.continuous import ChallengerResearch
from neraium_poly.research.phase23.models import MODELS, forecast_models, map_challenger_contract
from test_phase18_continuous import Clock, collect, frame
from test_phase18_forecasting import CUTOFF, artifact, market


def test_two_distinct_models_causal_reproducible_and_no_authority():
    c=map_challenger_contract(market(),now=CUTOFF);e=(artifact(),)
    a=forecast_models(c,e,cutoff=CUTOFF);assert a==forecast_models(c,e,cutoff=CUTOFF)
    assert [x['model_id'] for x in a]==list(MODELS)
    assert a[0]['probability']!=a[1]['probability']
    for r in a:
        assert 0<=r['probability']<=1 and r['lower_probability']==0 and r['upper_probability']==1
        assert r['training_returns']==720 and r['calibration_status']=='unvalidated_research'
        assert r['brier'] is None and r['log_loss'] is None and not r['trading_authority']
        assert r['independent_of_polymarket'] and r['source_lineages']==['binance:BTCUSDT']
    assert a[1]['monte_carlo']['paths']==512


def test_market_probability_not_hidden_feature_and_yes_no_complement():
    a=forecast_models(map_challenger_contract(market(),now=CUTOFF),(artifact(),),cutoff=CUTOFF)
    m=market().model_copy(update={'probability':.999})
    b=forecast_models(map_challenger_contract(m,now=CUTOFF),(artifact(),),cutoff=CUTOFF)
    no=forecast_models(map_challenger_contract(market(outcome='No'),now=CUTOFF),(artifact(),),cutoff=CUTOFF)
    assert [r['probability'] for r in a]==[r['probability'] for r in b]
    for yes,n in zip(a,no):assert abs(yes['probability']+n['probability']-1)<1e-12


def test_future_day_exact_binding_and_window_differs_from_immediate_barrier():
    m=market().model_copy(update={'question':'Will Bitcoin dip to $74,800 on November 7?', 'end_time':datetime(2026,11,8,5,tzinfo=UTC)})
    c=map_challenger_contract(m,now=CUTOFF);assert c.compatible and not c.review_required
    r=forecast_models(c,(artifact(),),cutoff=CUTOFF)
    assert len(r)==2 and all(x['forecast_horizon_seconds']>86400 for x in r)
    bad=map_challenger_contract(m.model_copy(update={'resolution_rules':m.resolution_rules+' alteration'}),now=CUTOFF)
    assert not bad.compatible


@pytest.mark.parametrize('change',['future_evidence','raw_corruption','tampered_contract','observed_barrier'])
def test_leakage_corruption_rule_tampering_or_already_hit_withheld(change):
    m=market();e=artifact();c=map_challenger_contract(m,now=CUTOFF);cutoff=CUTOFF
    if change=='future_evidence':cutoff-=timedelta(seconds=1)
    elif change=='raw_corruption':
        p=deepcopy(e.payload);p['responses'][0]['raw_response_utf8']+=' ';e=e.model_copy(update={'payload':p})
    elif change=='tampered_contract':
        p=deepcopy(c.parameters);p['threshold']=74700;c=c.model_copy(update={'parameters':p})
    else:c=map_challenger_contract(market(75000),now=CUTOFF)
    with pytest.raises(ValueError):forecast_models(c,(e,),cutoff=cutoff)


async def test_immutable_enrollment_append_prospective_restart_dedup(tmp_path):
    s=EventStore(tmp_path/'fixture.sqlite');clock=Clock()
    try:
        r=ChallengerResearch(s,clock=clock,collector=collect)
        assert await r.step(frame(clock));assert r.status()['forecasts']==2
        rows=s.latest('ChallengerStudy',3);assert len(rows)==2
        enrollment=next(x for x in rows if x['operation']=='enrollment');assert len(enrollment['enrollment'])==4
        study=next(x for x in rows if x['operation']=='forecast_batch');assert len(study['forecasts'])==2 and study['evidence']
        for f in study['forecasts']:
            assert datetime.fromisoformat(f['timestamp'])>=datetime.fromisoformat(f['evidence_cutoff']) and datetime.fromisoformat(f['book']['timestamp'])<=datetime.fromisoformat(f['timestamp'])
            assert f['book_sha256'] and f['rules_sha256'] and f['enrollment_id']==r.enrollment_id
        again=ChallengerResearch(s,clock=clock,collector=collect);assert again.state==r.state
        assert not await again.step(frame(clock))
        clock.now+=timedelta(minutes=6)
        await again.step(frame(clock));assert again.status()['forecasts']==2
        assert again.status()['unreviewed_parent_events']==1
    finally:s.close()


async def test_source_failure_stale_book_and_budget_do_not_invent_forecasts(tmp_path):
    s=EventStore(tmp_path/'fixture.sqlite');clock=Clock()
    async def fail(*args,**kwargs):raise OSError('CONTROLLED absent source')
    try:
        r=ChallengerResearch(s,clock=clock,collector=fail)
        assert not await r.step(frame(clock));assert r.status()['forecasts']==0
        assert any('external_source_withheld' in k for k in r.status()['rejections'])
        clock.now+=timedelta(minutes=6)
        old=frame(clock);old['books'][0]['timestamp']=(clock()-timedelta(minutes=1)).isoformat()
        assert not await r.step(old);assert r.status()['forecasts']==0
        blocked=ChallengerResearch(s,clock=clock,collector=collect,can_write=lambda:False)
        n=s.count();assert not await blocked.step(frame(clock));assert s.count()==n
    finally:s.close()


async def test_two_source_groups_are_genuinely_concurrent_bounded(tmp_path):
    clock=Clock();f=frame(clock);m=deepcopy(f['markets'][0]);b=deepcopy(f['books'][0])
    m.update(market_id='future-market',event_id='future-parent',token_id='future-token',question='Will Bitcoin dip to $74,800 on November 7?',end_time='2026-11-08T05:00:00Z')
    b.update(market_id='future-market',token_id='future-token');f['markets'].append(m);f['books'].append(b)
    active=0;peak=0
    async def source(c,*,now):
        nonlocal active,peak
        active+=1;peak=max(peak,active);await asyncio.sleep(.01);active-=1;return (artifact(now),)
    s=EventStore(tmp_path/'fixture.sqlite')
    try:
        r=ChallengerResearch(s,clock=clock,collector=source);await r.step(f)
        assert peak==2 and r.status()['forecasts']==4 and r.status()['unreviewed_parent_events']==2
    finally:s.close()


def nfl_fixture():
    from neraium_poly.research.phase13.contracts import SourceArtifact
    from test_phase13_mapping import NOW, game
    from test_phase13_models import corpus
    games,_target=corpus('NFL')
    converted=[]
    for g in games:
        home='DET' if g.home_id=='A' else 'MIA';away='MIA' if home=='DET' else 'DET'
        converted.append(g.model_copy(update={'provider':'nflverse/nflverse-data','home_id':home,'away_id':away}))
    converted[0]=converted[0].model_copy(update={'home_score':17,'away_score':17})
    return {'games':converted+[game()], 'artifacts':[SourceArtifact(provider='nflverse/nflverse-data',source_id='CONTROLLED',source_url='https://fixture.invalid',retrieved_at=NOW-timedelta(days=1),available_at=NOW-timedelta(days=1),content_sha256='a'*64,raw_path='fixture.csv',quality='qualified')]}


def test_nfl_davidson_and_frequency_preserve_ties_reproduce_and_ignore_market_price():
    from neraium_poly.research.phase23.models import SPORTS_MODELS, forecast_nfl
    from test_phase13_mapping import NOW
    from test_phase13_mapping import market as nfl_market
    data=nfl_fixture();a=forecast_nfl(nfl_market(),data,cutoff=NOW)
    assert a==forecast_nfl(nfl_market(),data,cutoff=NOW)
    assert [x['model_id'] for x in a]==list(SPORTS_MODELS)
    assert a[0]['probability']!=a[1]['probability']
    other=forecast_nfl(nfl_market(probability=.999),data,cutoff=NOW)
    for r,s in zip(a,other):
        assert r['probability']==s['probability']
        probs=r['outcome_probabilities'];assert sum(probs.values())==pytest.approx(1)
        assert probs['tie']>0 and probs['win']==r['probability']
        assert r['expected_payout']==pytest.approx(r['probability']+.5*probs['tie'])
        assert r['probability_semantics']=='outcome_distribution' and not r['trading_authority']
        assert r['training_observations']==60 and r['brier'] is None


def test_nfl_future_source_unavailable_and_old_elo_gate_preserved():
    from neraium_poly.research.phase13.models import predict_game
    from neraium_poly.research.phase23.models import forecast_nfl
    from test_phase13_mapping import NOW, game
    from test_phase13_mapping import market as nfl_market
    data=nfl_fixture();data['artifacts'][0]=data['artifacts'][0].model_copy(update={'available_at':NOW+timedelta(seconds=1)})
    with pytest.raises(ValueError,match='after_forecast'):forecast_nfl(nfl_market(),data,cutoff=NOW)
    with pytest.raises(ValueError,match='Elo expected score'):predict_game(data['games'],game(),'DET',NOW,method='elo')


async def test_append_failure_does_not_advance_in_memory_forecast_keys(tmp_path):
    class FailingStore:
        def __init__(self):self.calls=0
        def latest(self,*args,**kwargs):return []
        def append(self,row):
            self.calls+=1
            if self.calls>1:raise OSError('CONTROLLED disk full')
    store=FailingStore();clock=Clock();r=ChallengerResearch(store,clock=clock,collector=collect)
    with pytest.raises(OSError,match='disk full'):await r.step(frame(clock))
    assert r.state['enrolled'] and r.state['forecasts']==0 and not r.state['seen']
