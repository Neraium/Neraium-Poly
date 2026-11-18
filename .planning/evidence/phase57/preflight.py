"""Select from activity metadata and current depth without scoring."""
import asyncio
import gzip
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx

HERE = Path(__file__).resolve().parent
FROZEN = json.loads((HERE.parent/'phase56-baskets/freeze.json').read_text())
tape = Path((HERE.parent/'phase55/forward-output-location.txt').read_text().strip())/'forward-tape.jsonl.gz'

async def main():
    with gzip.open(tape,'rt') as stream:
        frame = next(r['frame'] for line in stream if 'frame' in (r:=json.loads(line)))
    candidates = {'crypto':['6507424','7085179','701552','701502','6507428','7097168','7121563'],
                  'economics':['3215006','3215007','4620900','3215011','3215012','6322990','6322991']}
    selected = {}
    checks = []
    async with httpx.AsyncClient(base_url='https://clob.polymarket.com',timeout=6,trust_env=False) as client:
        async def get(path, **params):
            response = await client.get(path,params=params)
            response.raise_for_status()
            return response.json()
        for category, ids in candidates.items():
            for mid in ids:
                rows = [m for m in frame['markets'] if m['market_id']==mid]
                result = {'category':category,'market':mid}
                checks.append(result)
                try:
                    assert len(rows)==2 and {r['outcome'].lower() for r in rows}=={'yes','no'}
                    assert all(r['status']=='active' and r['resolution_rules'] and r['resolution_source'] and
                               datetime.fromisoformat(r['end_time'])>datetime.now(UTC)+timedelta(hours=25) for r in rows)
                    assert len({(r['resolution_rules'],r['resolution_source'],r['end_time']) for r in rows})==1
                    tokens=[r['token_id'] for r in rows]
                    identity=await get('/markets-by-token/'+tokens[0])
                    native=await get('/clob-markets/'+identity['condition_id'])
                    assert set(tokens)=={t['t'] for t in native['t']}=={identity['primary_token_id'],identity['secondary_token_id']}
                    assert native['c']==identity['condition_id'] and native['fd']['e']==1 and native['fd']['to']
                    qualifying=0
                    for _ in range(3):
                        books=await asyncio.gather(*(get('/book',token_id=t) for t in tokens))
                        now=datetime.now(UTC).timestamp()
                        minimum=float(native['mos'])
                        if all(b['asset_id']==t and b['market']==native['c'] and b.get('neg_risk') is False
                               and 0<=now-int(b['timestamp'])/1000<=15
                               and all(sum(float(x['size']) for x in b[s])>=minimum for s in ('bids','asks'))
                               for b,t in zip(books,tokens,strict=True)):
                            qualifying+=1
                        await asyncio.sleep(1)
                    result['fresh_two_sided_samples']=qualifying
                    if qualifying>=2:
                        selected[mid]={'category':category,'rows':rows,'token_source':identity,'native':native,
                                       'fee_available_at':datetime.now(UTC).isoformat()}
                    if sum(m['category']==category for m in selected.values())>=2:
                        break
                except (AssertionError,KeyError,ValueError,httpx.HTTPError) as error:
                    result['excluded']=type(error).__name__
    (HERE/'preflight.json').write_text(json.dumps(checks,indent=2)+'\n')
    assert selected,'No qualifying markets'
    F={**FROZEN,'markets':selected,'relationships':[
        {'id':k,'legs':[r['token_id'] for r in m['rows']],'kind':'complete_set','payoffs':[[1,0],[0,1],[.5,.5]],'floor':1}
        for k,m in selected.items()],
        'duration_seconds':86400,'capture_interval_seconds':5,'capture_limit_bytes':2147483648}
    (HERE/'freeze.json').write_text(json.dumps(F,indent=2)+'\n')
    print([(k,v['category']) for k,v in selected.items()])
asyncio.run(main())
