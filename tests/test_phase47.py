"""Engineering controls; fixture outcomes are never prospective performance."""
import gzip
import json
from pathlib import Path

import pytest
from neraium_poly.research.phase44.native import replay, verify
from neraium_poly.research.phase46.file_budget import FileBudget
from neraium_poly.research.phase47.discovery import discover, validate_hint
from neraium_poly.research.phase47.storage import CompressedPath, read

FIXTURE=Path('.planning/evidence/phase44/native-spx2')


def test_lossless_new_representation_preserves_every_original_byte_and_proof(tmp_path):
    expected=replay(FIXTURE);source={str(p.relative_to(FIXTURE)):p.read_bytes() for p in FIXTURE.rglob('*') if p.is_file()};budget=FileBudget(tmp_path,2*1024**2)
    for name,raw in source.items():
        target=CompressedPath(tmp_path/name,budget=budget);target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw)
        assert read(tmp_path/name)==raw
    assert replay(tmp_path)==expected
    assert budget.used<sum(map(len,source.values()))*.5
    assert all(p.read_bytes()==source[str(p.relative_to(FIXTURE))] for p in FIXTURE.rglob('*') if p.is_file())
    with pytest.raises(ValueError):CompressedPath(tmp_path/'too-big',budget=FileBudget(tmp_path/'other',1)).write_bytes(b'x')


def test_compressed_corruption_and_bomb_withheld(tmp_path):
    p=tmp_path/'x.json.gz';p.write_bytes(b'not gzip')
    with pytest.raises((OSError,EOFError)):read(tmp_path/'x.json')
    p.write_bytes(gzip.compress(b'x'*(8*1024**2+1)))
    with pytest.raises(ValueError,match='budget'):read(tmp_path/'x.json')


def test_missing_transaction_hash_and_optional_question_use_exact_bounded_logs():
    b=json.loads((FIXTURE/'bundle.json').read_bytes());g=b['gamma'];hint=json.loads(json.dumps(b['resolution_hint']));row=hint['data'][0];row.pop('question_id',None);row['transaction_hash']='';row['resolved_block']=int(b['log']['blockNumber'],16)
    calls=[]
    class Client:
        def request(self,method,params):
            calls.append((method,params))
            if method=='eth_getBlockByNumber':return b['finalized']
            if method=='eth_getLogs':return [b['log']]
            if method=='eth_getTransactionReceipt':return b['receipt']
            raise AssertionError(method)
    log,receipt=discover(Client(),g,hint);assert log==b['log'] and receipt==b['receipt']
    assert [c[0] for c in calls]==['eth_getBlockByNumber','eth_getLogs','eth_getTransactionReceipt']
    assert calls[1][1][0]['topics'][1]==g['conditionId']
    q=calls[1][1][0];assert int(q['toBlock'],16)-int(q['fromBlock'],16)<=3000
    assert verify({**b,'resolution_hint':hint})['native_payout_verified']
    with pytest.raises(ValueError):validate_hint({'data':[{**row,'condition_id':'WRONG'}]},g)
    with pytest.raises(ValueError):validate_hint({'data':[{**row,'question_id':'WRONG'}]},g)
    with pytest.raises((ValueError,KeyError)):verify({**b,'resolution_hint':hint,'state':[]})


async def test_held_fee_refresh_without_any_book_or_reference(setup):
    from neraium_poly.experimental.research_fee_cache import AsyncBudgetResearchFeeCache
    _,clock,_,_,_,_,_,store,_=setup
    seen=[]
    class Adapter:
        async def observed_fee(self,t):seen.append(t);
    c=AsyncBudgetResearchFeeCache(store,Adapter(),clock=lambda:clock[0],can_write=lambda:True)
    await c.refresh(None,forecast_tokens=[],priority_tokens=['ACTUAL-HELD-TOKEN'])
    assert seen==['ACTUAL-HELD-TOKEN'] and c.errors['ACTUAL-HELD-TOKEN']=='native_curve_unavailable'

from test_phase42_strategies import setup as _setup

setup=_setup


def test_full_acquisition_missing_hint_transaction_compressed_replay(tmp_path):
    import httpx
    from neraium_poly.research.phase44.native import acquire
    b=json.loads((FIXTURE/'bundle.json').read_bytes());hint=json.loads(json.dumps(b['resolution_hint']));hint['data'][0].pop('question_id',None);hint['data'][0]['transaction_hash']='';hint['data'][0]['resolved_block']=int(b['log']['blockNumber'],16)
    native={f"https://gamma-api.polymarket.com/markets/{b['forecast']['market_id']}":b['gamma'],f"https://clob.polymarket.com/markets-by-token/{b['forecast']['token_id']}":b['clob'],f"https://gamma-api.polymarket.com/events/{b['forecast']['event_id']}":b['parent'],f"https://data-api.polymarket.com/v2/resolutions?condition={b['gamma']['conditionId']}":hint}
    def request(req):
        if req.method=='GET':return httpx.Response(200,json=native[str(req.url)])
        call=json.loads(req.content);m,p=call['method'],call['params']
        if m=='eth_getLogs':value=[b['log']]
        elif m=='eth_getTransactionReceipt':value=b['receipt']
        elif m=='eth_getBlockByHash':value=b['block']
        elif m=='eth_getBlockByNumber':value=b['finalized'] if p[0]=='finalized' else b['canonical']
        elif m=='eth_chainId':value=b['chain_id']
        elif m=='eth_call':value=next(v['result'] for v in b['state'] if v['to'].lower()==p[0]['to'].lower() and v['data']==p[0]['data'])
        else:raise AssertionError(m)
        return httpx.Response(200,json={'jsonrpc':'2.0','id':call['id'],'result':value})
    with httpx.Client(transport=httpx.MockTransport(request)) as client:proof=acquire(b['forecast'],tmp_path/'new',client=client,disk_budget=128*1024)
    assert proof==replay(tmp_path/'new') and proof['payout']==verify(b)['payout']
    assert (tmp_path/'new/bundle.json.gz').exists() and not (tmp_path/'new/bundle.json').exists()
    assert sum(p.stat().st_size for p in (tmp_path/'new').rglob('*') if p.is_file())<=128*1024


def test_frozen_cohort_monitoring_is_time_based_not_payout_based(setup,monkeypatch):
    from datetime import timedelta

    from neraium_poly.research.phase47 import cohort
    from test_phase46 import prepare_program
    p,f,refs,frame=prepare_program(setup);p.register({f['id']:f},refs,frame,{},{});key=next(iter(p.rows));monkeypatch.setattr(cohort,'FROZEN',[key])
    assert f['id'] in cohort.watch(p,p.clock())
    assert cohort.report(p,[],p.clock())['verified_trials']==0
    original=p.rows[key]['probabilities'].copy()
    p.rows[key]['source_forecast']['event_end_time']=(p.clock()+timedelta(days=2)).isoformat()
    assert not cohort.watch(p,p.clock()) and p.rows[key]['probabilities']==original
