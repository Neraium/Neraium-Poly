"""Engineering fixtures only; no manufactured prospective outcome claims."""
import copy
from datetime import timedelta
from types import SimpleNamespace

import pytest
from neraium_poly.experimental.research_fee_cache import AsyncBudgetResearchFeeCache
from neraium_poly.research.phase14.relationships import digest
from neraium_poly.research.phase46.file_budget import BudgetPath, FileBudget
from neraium_poly.research.phase46.program import Program, frequency
from test_phase42_strategies import setup as _setup

setup=_setup


def test_exact_disk_budget_counts_manifests_and_replacements_and_preserves_originals(tmp_path):
    root=tmp_path/'new';root.mkdir();budget=FileBudget(root,10);p=BudgetPath(root,budget=budget)
    (p/'raw').mkdir();(p/'raw'/'x').write_bytes(b'123456');(p/'manifest.json').write_bytes(b'1234')
    with pytest.raises(ValueError):(p/'proof.json').write_bytes(b'x')
    (p/'manifest.json').write_text('12');(p/'proof.json').write_bytes(b'12')
    assert sum(f.stat().st_size for f in root.rglob('*') if f.is_file())==10
    assert (root/'raw/x').read_bytes()==b'123456'
    with pytest.raises(ValueError):FileBudget(root,100)
    with pytest.raises(ValueError):(p/'..'/'escape').write_bytes(b'x')


async def test_held_token_fee_refresh_does_not_require_any_current_book(setup):
    _,clock,_m,_,_,frame,_,_,_=setup;calls=[]
    async def observe(t):calls.append(t)
    cache=AsyncBudgetResearchFeeCache(None,SimpleNamespace(observed_fee=observe),clock=lambda:clock[0],can_write=lambda:True)
    await cache.refresh(frame.model_copy(update={'markets':(),'books':()}),forecast_tokens=[],priority_tokens=['HELD'])
    assert calls==['HELD']


def prepare_program(setup):
    _,clock,_m,_b,f,frame,_fees,store,_risk=setup
    # Use a valid existing canonical crypto contract from fixture; if its
    # parameter mapping is absent this engineering test supplies one explicitly.
    f=copy.deepcopy(f);f['domain']='crypto';f['contract']={'parameters':{'symbol':'BTCUSDT','period_start_utc':(clock[0]-timedelta(hours=1)).isoformat(),'period_end_utc':f['event_end_time']}}
    program=Program(store,lambda:clock[0],lambda:True)
    refs={f['id']:{'study_id':'CONTROLLED-study','study_sha256':'CONTROLLED-sha','forecast_sha256':digest(f)}}
    return program,f,refs,frame


def test_prospective_program_registers_once_and_records_baselines_without_scoring_pending(setup):
    p,f,refs,frame=prepare_program(setup);original=copy.deepcopy(f)
    p.register({f['id']:f},refs,frame,{},{});p.register({f['id']:f},refs,frame,{},{});
    assert len(p.rows)==1 and f==original
    row=next(iter(p.rows.values()));assert row['probabilities']['zero']==0 and row['probabilities']['one']==1
    assert row['probabilities']['past_frequency']==.5 and row['training']['blocks']==0
    assert p.report()['native_results']==0 and p.report()['scores_equal_block_weight']=={}
    assert Program(p.store,p.clock,p.can_write).rows==p.rows


@pytest.mark.parametrize('payout',[0,1])
def test_program_scores_positive_and_zero_only_with_exact_causal_native_proof(setup,payout):
    p,f,refs,frame=prepare_program(setup);p.register({f['id']:f},refs,frame,{},{});clock=setup[1];clock[0]+=timedelta(seconds=2)
    proof={k:f[k] for k in ('market_id','event_id','token_id','rules_sha256')};proof.update(forecast_id=f['id'],verified=True,native_payout_verified=True,payout=payout,resolved_at=(clock[0]-timedelta(seconds=1)).isoformat(),available_at=clock[0].isoformat())
    with pytest.raises(ValueError):p.settle({f['id']:{**proof,'token_id':'WRONG'}})
    p.settle({f['id']:proof});p.settle({f['id']:proof})
    r=p.report();assert r['native_results']==1 and r['conservative_date_blocks']==1 and r['reviewed_independent_training']==0
    assert r['scores_equal_block_weight']['zero']['brier']==payout
    assert r['scores_equal_block_weight']['one']['brier']==1-payout


def test_frequency_never_selects_later_resolved_contract_when_first_is_unresolved(setup):
    _p,f,_refs,_frame=prepare_program(setup);clock=setup[1]
    old={**f,'id':'FIRST','event_id':'OLD','timestamp':(clock[0]-timedelta(days=2)).isoformat(),'event_end_time':(clock[0]-timedelta(days=1)).isoformat(),
         'contract':{'parameters':{'symbol':'BTCUSDT','period_start_utc':(clock[0]-timedelta(days=2)).isoformat(),'period_end_utc':(clock[0]-timedelta(days=1)).isoformat()}}}
    later={**old,'id':'SECOND','timestamp':(clock[0]-timedelta(days=2)+timedelta(seconds=1)).isoformat()}
    proof={k:later[k] for k in ('market_id','event_id','token_id','rules_sha256')};proof.update(native_payout_verified=True,payout=1,resolved_at=(clock[0]-timedelta(days=1)).isoformat(),available_at=(clock[0]-timedelta(hours=1)).isoformat())
    a,b,training=frequency(f,{'FIRST':old,'SECOND':later},{'SECOND':proof},clock[0]);assert training['blocks']==0 and a==b==.5


def test_native_acquisition_cannot_bypass_remaining_budget_on_failure(tmp_path):
    import httpx
    from neraium_poly.research.phase44.native import acquire
    client=httpx.Client(transport=httpx.MockTransport(lambda _:httpx.Response(200,json={'closed':False,'umaResolutionStatus':'pending'})))
    try:
        with pytest.raises(ValueError):acquire({'market_id':'123'},tmp_path/'new',client=client,disk_budget=16)
        assert sum(p.stat().st_size for p in (tmp_path/'new').rglob('*') if p.is_file())<=16
        assert not (tmp_path/'new'/'proof.json').exists()
    finally:client.close()


async def test_cached_native_proofs_survive_capacity_exhaustion(setup,tmp_path,monkeypatch):
    import json
    import shutil
    from pathlib import Path

    from neraium_poly.research.phase44 import outcomes
    from neraium_poly.research.phase44.native import replay
    _,clock,_,_,_,_,_,store,_=setup
    root=tmp_path/'native';root.mkdir();path=root/'proof'
    original=Path('.planning/evidence/phase44/native-spx2');shutil.copytree(original,path)
    f=json.loads((path/'bundle.json').read_bytes())['forecast'];proof=replay(path);clock[0]=outcomes.at(proof['available_at'])+timedelta(seconds=1)
    record=outcomes.NativePayout44(id='CONTROLLED-cache',timestamp=clock[0],available_at=clock[0],source='CONTROLLED',forecast_id=f['id'],forecast_sha256=digest(f),original_study_sha256='CONTROLLED',directory='proof',verified=True,reason='CONTROLLED actual captured proof',proof=proof);store.append(record)
    with (root/'sparse-control').open('wb') as stream:stream.truncate(64*1024**2)
    other={**f,'id':'CONTROLLED-other','market_id':'OTHER'}
    def forbidden(*a,**k):raise AssertionError('network acquisition despite exhausted guard')
    monkeypatch.setattr(outcomes,'acquire',forbidden)
    found=await outcomes.collect({f['id']:{'forecast':f},other['id']:{'forecast':other}},store,root,clock=lambda:clock[0],can_write=lambda:True)
    assert found[f['id']]['native_payout_verified'] and other['id'] not in found
    assert store.latest('NativeCycle46',1)[0]['capacity']['remaining_bytes']==0


def test_refresh_versions_cannot_overwrite_a_single_prospective_trial(setup):
    p,f,refs,frame=prepare_program(setup);clock=setup[1];clock[0]+=timedelta(seconds=2)
    newer={**f,'id':'CONTROLLED-new','timestamp':(clock[0]-timedelta(seconds=1)).isoformat()}
    refs[newer['id']]={**refs[f['id']],'forecast_sha256':digest(newer)}
    p.register({f['id']:f,newer['id']:newer},refs,frame,{},{});assert len(p.rows)==1
    assert next(iter(p.rows.values()))['source_forecast']['id']==newer['id']


def test_information_selection_prefers_balanced_contract_without_reading_outcomes(setup,monkeypatch):
    from neraium_poly.contracts import PriceLevel
    from neraium_poly.research.phase46 import selection
    _,clock,m,b,_f,frame,_fees,_store,_risk=setup
    rare=m.model_copy(update={'market_id':'1','token_id':'RARE','outcome':'Yes'});balanced=m.model_copy(update={'market_id':'2','token_id':'BALANCED','outcome':'Yes'})
    br=b.model_copy(update={'market_id':'1','token_id':'RARE','bids':(PriceLevel(price=.01,size=1000),),'asks':(PriceLevel(price=.02,size=1000),)})
    bb=b.model_copy(update={'market_id':'2','token_id':'BALANCED','bids':(PriceLevel(price=.49,size=1000),),'asks':(PriceLevel(price=.51,size=1000),)})
    monkeypatch.setattr(selection,'map_challenger_contract',lambda *a,**k:SimpleNamespace(compatible=True,review_required=False,parameters={'period_start_utc':'CONTROLLED-same-date','period_end_utc':'CONTROLLED-same-end'}))
    chosen=selection.select(frame.model_copy(update={'markets':(rare,balanced),'books':(br,bb)}),clock[0],crypto=True)
    assert [m.market_id for m in chosen.markets]==['2']


def test_source_inventory_budgets_the_exact_controller_representation():
    import json
    from threading import RLock

    from neraium_poly.research.phase42.sources import forecast_studies
    # Specific regression: compact UTF8 records fit, expanded JSON does not.
    # Originals remain available; defer excess records instead of poisoning
    # the entire inventory or increasing the existing16MiB guard.
    raw=json.dumps({'forecasts':[{}],'evidence':'é'*600000},ensure_ascii=False,separators=(',',':'))
    rows={str(i):('RefreshDomainStudy',raw) for i in range(5)}
    class Connection:
        def execute(self,_sql,args):return SimpleNamespace(fetchall=lambda:[(k,) for k in rows] if args[0]=='RefreshDomainStudy' else [])
    store=SimpleNamespace(catalog=Connection(),_lock=RLock(),get=rows.get)
    assert sum(len(r[1].encode()) for r in rows.values())<16*1024**2
    studies,audit=forecast_studies(store)
    assert len(studies)==4 and audit['deferred_for_serialized_budget']==1
    assert len(json.dumps(studies).encode())==audit['retained_bytes']<=16*1024**2
    assert len(rows)==5 and all(r[1]==raw for r in rows.values())
