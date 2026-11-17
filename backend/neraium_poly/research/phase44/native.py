"""Research-only standard CTF settlement with exact asset and finalized log proof.

The resolution API supplies a transaction LOOKUP HINT, never a payout. Its
new_version_q flag describes the oracle question; proof comes from the CTF
receipt/log, canonical finality and contract-computed original outcome assets.
Legacy certified settlement requirements are unchanged.
"""
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import httpx

from neraium_poly.research.phase14.relationships import digest
from neraium_poly.research.phase24.continuous import at
from neraium_poly.research.phase35.native import USDC, NativeResearchClient, call_key
from neraium_poly.research.settlement_evidence import (
    CONDITION_RESOLUTION,
    CTF,
    HEX32,
    canonical,
    corroborate_resolution,
)


def values(v):return json.loads(v) if isinstance(v,str) else v


def identity(f,g,c,parent):
    m=f['market'];outcomes=values(g['outcomes']);tokens=list(map(str,values(g['clobTokenIds'])))
    if (g.get('version')!='v1' or g.get('negRisk') is not False or g.get('closed') is not True or g.get('umaResolutionStatus')!='resolved'
        or str(g['id'])!=f['market_id'] or len(tokens)!=2 or len(set(tokens))!=2 or len(outcomes)!=2
        or m['outcome'] not in outcomes or tokens[outcomes.index(m['outcome'])]!=f['token_id']
        or g['question']!=m['question'] or g['description']!=m['resolution_rules'] or g.get('resolutionSource')!=m['resolution_source']
        or hashlib.sha256(g['description'].encode()).hexdigest()!=f['rules_sha256']
        or at(g['endDate'])!=at(m['end_time']) or c['condition_id'].lower()!=g['conditionId'].lower()
        or {str(c['primary_token_id']),str(c['secondary_token_id'])}!=set(tokens)
        or str(parent['id'])!=f['event_id'] or sum(str(v.get('id'))==f['market_id'] for v in parent['markets'])!=1):
        raise ValueError('native_original_market_rules_parent_or_token_mismatch')
    return outcomes,tokens


def verify(bundle):
    f,g,c,parent=(bundle[k] for k in ('forecast','gamma','clob','parent'))
    outcomes,tokens=identity(f,g,c,parent);condition=g['conditionId'].lower();log=bundle['log']
    hint=bundle['resolution_hint'];rows=hint.get('data',[])
    if (len(rows)!=1 or rows[0].get('condition_id','').lower()!=condition or rows[0].get('question_id','').lower()!=g['questionID'].lower() or rows[0].get('status')!='resolved' or rows[0].get('extended_review') is not False or rows[0].get('was_disputed') is not False):
        raise ValueError('native_transaction_hint_mismatch')
    if bundle['chain_id']!='0x89':raise ValueError('wrong_native_chain')
    proof=corroborate_resolution(condition,log,bundle['receipt'],bundle['block'],bundle['canonical'],bundle['finalized'],available_at=at(bundle['available_at']))
    if not at(f['evidence_cutoff'])<=at(f['timestamp'])<at(proof['settlement_at']):raise ValueError('forecast_not_prospective_to_native_resolution')
    oracle='0x'+log['topics'][2][-40:].lower()
    if oracle!=g['resolvedBy'].lower() or log['topics'][3].lower()!=g['questionID'].lower():raise ValueError('native_oracle_or_question_mismatch')
    state={(v['to'].lower(),v['data']):v for v in bundle['state']}
    def read(name,*args):
        row=state[call_key(CTF,name,*args)]
        if row['block_hash']!=bundle['finalized']['hash'] or not HEX32.fullmatch(row['result']):raise ValueError('state_not_canonical_finalized')
        return row['result'].lower()
    if read('condition',oracle,g['questionID'],2)!=condition:raise ValueError('native_onchain_condition_mismatch')
    for i,token in enumerate(tokens):
        collection=read('collection','0x'+'00'*32,condition,1<<i)
        if int(read('position',USDC,collection),16)!=int(token):raise ValueError('unsupported_collateral_or_outcome_asset')
    if int(read('denominator',condition),16)!=sum(proof['payouts']):raise ValueError('native_denominator_mismatch')
    if [int(read('numerator',condition,i),16) for i in range(2)]!=proof['payouts']:raise ValueError('native_payout_vector_mismatch')
    return {'forecast_id':f['id'],'event_id':f['event_id'],'market_id':f['market_id'],'token_id':f['token_id'],'rules_sha256':f['rules_sha256'],
        'payout':proof['payouts'][outcomes.index(f['market']['outcome'])],'resolved_at':proof['settlement_at'],
        'available_at':bundle['available_at'],'verified':True,'native_payout_verified':True,'proof_sha256':digest(bundle),
        'verification_source':'standard_CTF_receipt_canonical_finality_and_original_USDC_outcome_asset_v44',
        'trust_limit':proof['trust_limit'],'independence_reviewed':False,'research_only':True,'trading_authority':False}


def replay(directory):
    directory=Path(directory);bundle=json.loads((directory/'bundle.json').read_bytes());manifest=json.loads((directory/'manifest.json').read_bytes())
    native={};rpc={};calls={}
    for row in manifest['responses']:
        path=directory/row['response_path']
        if path.parent!=directory/'raw' or path.is_symlink():raise ValueError('unsafe_native_proof_path')
        raw=path.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=row['response_sha256'] or row['status']!=200:raise ValueError('native_raw_hash_or_http_mismatch')
        payload=json.loads(raw)
        if row['method']=='GET':native[row['url']]=payload;continue
        req=row['request']
        if payload.get('id')!=req['id'] or 'error' in payload:raise ValueError('native_rpc_response_mismatch')
        method,params=req['method'],req['params'];value=payload['result']
        if method=='eth_call':
            if params[1]!={'blockHash':bundle['finalized']['hash'],'requireCanonical':True}:raise ValueError('native_state_request_not_finalized')
            calls[(params[0]['to'].lower(),params[0]['data'])]=value
        else:rpc[(method,json.dumps(params))]=value
    f=bundle['forecast']
    for key,url in [('gamma','https://gamma-api.polymarket.com/markets/'+f['market_id']),('clob','https://clob.polymarket.com/markets-by-token/'+f['token_id']),('parent','https://gamma-api.polymarket.com/events/'+f['event_id']),('resolution_hint','https://data-api.polymarket.com/v2/resolutions?condition='+bundle['gamma']['conditionId'])]:
        if native.get(url)!=bundle[key]:raise ValueError('native_original_response_binding_failed')
    if bundle['log']['transactionHash']!=bundle['resolution_hint']['data'][0]['transaction_hash'] and not any(method=='eth_getLogs' and bundle['log'] in value for (method,_params),value in rpc.items() if isinstance(value,list)):raise ValueError('native_fallback_log_not_in_original_query')
    expected={'chain_id':('eth_chainId',[]),'receipt':('eth_getTransactionReceipt',[bundle['log']['transactionHash']]),'block':('eth_getBlockByHash',[bundle['log']['blockHash'],False]),'canonical':('eth_getBlockByNumber',[bundle['log']['blockNumber'],False]),'finalized':('eth_getBlockByNumber',['finalized',False])}
    for key,(method,params) in expected.items():
        if rpc.get((method,json.dumps(params)))!=bundle[key]:raise ValueError('native_chain_original_binding_failed')
    for row in bundle['state']:
        if calls.get((row['to'].lower(),row['data']))!=row['result']:raise ValueError('native_state_original_binding_failed')
    return verify(bundle)


class Client(NativeResearchClient):
    def resolution_hint(self,condition):
        if not HEX32.fullmatch(condition) or self.requests>=self.max_requests:raise ValueError('bounded_resolution_hint_required')
        url='https://data-api.polymarket.com/v2/resolutions?condition='+condition;self.requests+=1
        raw=bytearray()
        with self.client.stream('GET',url) as response:
            for part in response.iter_bytes():
                self.bytes+=len(part)
                if self.bytes>self.max_bytes or len(raw)+len(part)>2*1024**2:raise ValueError('native_hint_byte_budget')
                raw.extend(part)
            h=hashlib.sha256(raw).hexdigest();path='raw/'+h+'.json';(self.directory/path).write_bytes(raw)
            self.manifest.append({'url':url,'method':'GET','response_sha256':h,'response_path':path,'bytes':len(raw),'status':response.status_code,'received_at':datetime.now(UTC).isoformat()})
            self.save_manifest();response.raise_for_status()
        return json.loads(raw)


def acquire(f,directory,*,client=None):
    """Bounded read-only acquisition; raw failures are retained, never called proof."""
    owned=client is None;transport=client or httpx.Client(timeout=3,trust_env=False)
    c=Client(directory,client=transport,max_requests=48,max_bytes=2*1024**2,interval=.05)
    try:
        g=c.native_get('https://gamma-api.polymarket.com/markets/'+f['market_id'])
        if g.get('closed') is not True or g.get('umaResolutionStatus')!='resolved':raise ValueError('native_pending_or_disputed')
        clob=c.native_get('https://clob.polymarket.com/markets-by-token/'+f['token_id'])
        parent=c.native_get('https://gamma-api.polymarket.com/events/'+f['event_id']);identity(f,g,clob,parent)
        hint=c.resolution_hint(g['conditionId']);rows=hint.get('data',[])
        if len(rows)!=1 or not HEX32.fullmatch(rows[0].get('transaction_hash','')):raise ValueError('native_resolution_transaction_unavailable')
        tx=rows[0]['transaction_hash'];receipt=c.request('eth_getTransactionReceipt',[tx])
        logs=[v for v in receipt.get('logs',[]) if v.get('address','').lower()==CTF and v.get('topics',[])[:2]==[CONDITION_RESOLUTION,g['conditionId']]]
        if len(logs)!=1:
            # A resolution API transaction can be an oracle proposal, not the
            # CTF payout. Use the official closedTime only as a search hint;
            # canonical logs and state remain the actual proof.
            target=at(g['closedTime']).timestamp()
            final=c.request('eth_getBlockByNumber',['finalized',False]);height=int(final['number'],16)
            low=max(0,height-65536);high=height
            while low<high:
                middle=(low+high)//2;header=c.request('eth_getBlockByNumber',[hex(middle),False])
                if int(header['timestamp'],16)<target:low=middle+1
                else:high=middle
            logs=c.request('eth_getLogs',[{'address':CTF,'topics':[CONDITION_RESOLUTION,g['conditionId']],
                'fromBlock':hex(max(0,low-1500)),'toBlock':hex(min(height,low+1500))}])
            if not isinstance(logs,list) or len(logs)!=1:raise ValueError('unique_native_condition_resolution_log_unavailable_in_published_close_bracket')
            receipt=c.request('eth_getTransactionReceipt',[logs[0]['transactionHash']])
        log=logs[0];bundle={'forecast':f,'gamma':g,'clob':clob,'parent':parent,'resolution_hint':hint,'log':log,'receipt':receipt,
            'chain_id':c.request('eth_chainId',[]),'block':c.request('eth_getBlockByHash',[log['blockHash'],False]),
            'canonical':c.request('eth_getBlockByNumber',[log['blockNumber'],False]),'finalized':c.request('eth_getBlockByNumber',['finalized',False]),'state':[]}
        block=bundle['finalized']['hash'];state=bundle['state'];condition=g['conditionId'];oracle='0x'+log['topics'][2][-40:]
        state.append(c.call(CTF,'condition',block,oracle,g['questionID'],2))
        for i in range(2):
            state.append(c.call(CTF,'collection',block,'0x'+'00'*32,condition,1<<i))
            state.append(c.call(CTF,'position',block,USDC,state[-1]['result']))
        state.append(c.call(CTF,'denominator',block,condition))
        for i in range(2):state.append(c.call(CTF,'numerator',block,condition,i))
        bundle['available_at']=datetime.now(UTC).isoformat();(Path(directory)/'bundle.json').write_bytes(canonical(bundle))
        c.save_manifest();result=replay(directory);(Path(directory)/'proof.json').write_bytes(canonical(result));return result
    finally:
        c.save_manifest();c.close()
        if owned:transport.close()
