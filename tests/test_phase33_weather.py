"""Controlled causal weather analysis; fixture scores are not genuine evidence."""
from copy import deepcopy
from datetime import timedelta
from types import SimpleNamespace

import pytest
from neraium_poly.research.phase32 import weather as verifier
from neraium_poly.research.phase33.weather import prioritize_weather, weather_cohort
from test_phase24_weather_economics import NOW, book, market
from test_phase32_weather import OBSERVED, install_source, original


@pytest.fixture(autouse=True)
def fixture_disk(monkeypatch):
    monkeypatch.setattr(verifier.shutil,'disk_usage',lambda _:SimpleNamespace(free=200*1024**3))


async def case(monkeypatch,tmp_path):
    f,s=await original(monkeypatch);install_source(monkeypatch,f['contract'])
    r=await verifier.verify_weather_event(f,directory=tmp_path,clock=lambda:OBSERVED)
    assert r['event_result_verified']
    return {'forecast':f,'study':s,'result':r}


async def test_actual_sources_and_original_models_replay_but_native_baseline_stays_withheld(monkeypatch,tmp_path):
    row=await case(monkeypatch,tmp_path);r=weather_cohort([row,row],evidence_root=tmp_path,as_of=OBSERVED)
    assert r['official_reference_forecasts_scored']==r['distinct_scored_station_days']==1
    assert r['forecasts_replayed']==1 and r['forecasts_with_any_prior_qualified_station_day']==0
    assert r['market_baseline_metrics'] is None and not r['market_superiority_established']
    assert r['certified_training_events']==0 and not r['trading_authority']


@pytest.mark.parametrize('fault',['bytes','token','availability','identity_conflict'])
async def test_forecast_and_official_source_integrity_fail_closed(monkeypatch,tmp_path,fault):
    row=await case(monkeypatch,tmp_path);bad=deepcopy(row);records=[bad]
    if fault=='bytes':(tmp_path/bad['result']['evidence_directory']/bad['result']['official_evidence'][0]['raw_file']).write_text('[]')
    elif fault=='token':bad['result']['token_id']='WRONG'
    elif fault=='availability':bad['study']['available_at']=(OBSERVED+timedelta(seconds=1)).isoformat()
    else:bad['forecast']['probability']=.999;records=[row,bad]
    r=weather_cohort(records,evidence_root=tmp_path,as_of=OBSERVED)
    assert r['official_reference_forecasts_scored']==0 and r['rejections']


async def test_future_verification_is_not_backdated_to_station_day_end(monkeypatch,tmp_path):
    row=await case(monkeypatch,tmp_path)
    r=weather_cohort([row],evidence_root=tmp_path,as_of=OBSERVED-timedelta(seconds=1))
    assert r['forecasts_replayed']==1 and r['official_reference_forecasts_scored']==0
    assert r['pending_forecasts']==1 and r['observations'][0]['status']=='pending_outcome_availability'
    assert 'outcome' not in r['observations'][0]


async def test_multiple_models_same_day_never_become_prior_independent_training_events(monkeypatch,tmp_path):
    row=await case(monkeypatch,tmp_path);other=deepcopy(row);other['forecast']['id']='OTHER'
    other['study']['forecasts']=[other['forecast']];other['result']=None
    r=weather_cohort([row,other],evidence_root=tmp_path,as_of=OBSERVED)
    assert r['distinct_scored_station_days']==1
    assert all(x['point_in_time_prior_qualified_station_days']==0 for x in r['observations'])


def test_new_station_days_rank_first_and_tokens_do_not_create_independent_days():
    m=market();b=book(m)
    r=prioritize_weather([m],[b],[],as_of=NOW)
    assert r['new_station_days_with_eligible_books']==1
    e={'type':'forecast','replay_verified':True,'available_at':NOW.isoformat(),'forecast':{'domain':'weather','timestamp':NOW.isoformat()},
        'review':{'descriptor':{'station':'ZUCK','day':'2026-11-08'}}}
    r=prioritize_weather([m],[b],[e],as_of=NOW)
    assert r['new_station_days_with_eligible_books']==0 and r['candidates'][0]['station_day_already_forecast']
    assert not r['candidates'][0]['forecast_created']


@pytest.mark.parametrize('fault',['missing','stale','wrong_market','wrong_source','conflict'])
def test_book_subscription_candidates_cannot_be_presented_as_qualified_forecasts(fault):
    m=market();b=book(m);books=[b]
    if fault=='missing':books=[]
    elif fault=='stale':books=[b.model_copy(update={'timestamp':NOW-timedelta(seconds=16),'available_at':NOW-timedelta(seconds=16)})]
    elif fault=='wrong_market':books=[b.model_copy(update={'market_id':'OTHER'})]
    elif fault=='wrong_source':books=[b.model_copy(update={'source':'SYNTHETIC'})]
    else:books.append(b.model_copy(update={'sequence':2}))
    r=prioritize_weather([m],books,[],as_of=NOW)
    assert r['supported_station_days']==1 and r['new_station_days_with_eligible_books']==0
    assert r['candidates'][0]['blockers'] and not r['candidates'][0]['book_eligible_at_evaluation']


def test_conflicting_metadata_token_is_quarantined_entirely():
    m=market();bad=m.model_copy(update={'resolution_rules':'OTHER'})
    r=prioritize_weather([m,bad],[book(m)],[],as_of=NOW)
    assert not r['candidates'] and r['rejections']['conflicting_market_tokens_quarantined']==1


def test_metadata_only_subscription_priority_avoids_dead_tail_bins_without_predicting():
    m=market();tail=m.model_copy(update={"market_id":"000","token_id":"TAIL","probability":.001})
    central=m.model_copy(update={"market_id":"999","token_id":"CENTRAL","probability":.45})
    r=prioritize_weather([tail,central],[],[],as_of=NOW)
    assert r['candidates'][0]['token_id']=="CENTRAL"
    assert not r['candidates'][0]['book_eligible_at_evaluation']
    assert not r['candidates'][0]['forecast_created']


def test_only_label_receipt_not_day_end_makes_a_group_available_for_learning():
    from neraium_poly.research.phase33.weather import prior_weather_groups
    label={"station_day_id":"EARLIER","model_id":"MODEL","end":NOW.isoformat(),"label_available_at":(NOW+timedelta(hours=2)).isoformat()}
    later={"station_day_id":"NEXT","model_id":"MODEL","evidence_cutoff":(NOW+timedelta(hours=1)).isoformat()}
    assert not prior_weather_groups([label],later)
    later["evidence_cutoff"]=(NOW+timedelta(hours=3)).isoformat()
    assert prior_weather_groups([label],later)=={"EARLIER"}
    later["station_day_id"]="EARLIER";assert not prior_weather_groups([label],later)
    later["station_day_id"]="NEXT";later["model_id"]="OTHER";assert not prior_weather_groups([label],later)


async def test_challengers_need_same_exact_targets_not_just_shared_station_day(monkeypatch,tmp_path):
    from neraium_poly.research.phase24 import weather as generator
    from test_phase24_weather_economics import weather_evidence
    first=await case(monkeypatch,tmp_path)
    async def collect(*a,**k):return weather_evidence()
    monkeypatch.setattr(generator,"collect",collect)
    m=market(threshold=19).model_copy(update={"market_id":"OTHER-MARKET","token_id":"OTHER-TOKEN"})
    result=await generator.forecast(m.model_dump(),book(m).model_dump(),clock=lambda:NOW)
    f=result['forecasts'][1];f['id']='OTHER-TARGET';study={'forecasts':[f],'available_at':NOW.isoformat(),'evidence':result['evidence']}
    install_source(monkeypatch,f['contract']);proof=await verifier.verify_weather_event(f,directory=tmp_path,clock=lambda:OBSERVED)
    r=weather_cohort([first,{"forecast":f,"study":study,"result":proof}],evidence_root=tmp_path,as_of=OBSERVED)
    assert r['official_reference_forecasts_scored']==2 and r['distinct_scored_station_days']==1
    assert r['paired_model_comparisons'][0]['same_exact_targets']==0
    assert r['paired_model_comparisons'][0]['descriptive_brier_a_minus_b'] is None
