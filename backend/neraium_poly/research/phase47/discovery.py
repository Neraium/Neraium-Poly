"""Official lookup hints never establish payout; condition-scoped RPC logs do."""
from neraium_poly.research.phase24.continuous import at
from neraium_poly.research.settlement_evidence import CONDITION_RESOLUTION, CTF, HEX32


def validate_hint(hint,g):
    rows=hint.get('data')
    if not isinstance(rows,list) or len(rows)>1:raise ValueError('native_resolution_hint_schema_or_ambiguity')
    if not rows:return {}
    row=rows[0]
    if (row.get('condition_id','').lower()!=g['conditionId'].lower() or row.get('status')!='resolved'
        or row.get('extended_review') is not False or row.get('was_disputed') is not False
        or (row.get('question_id') is not None and row['question_id'].lower()!=g['questionID'].lower())):
        raise ValueError('native_transaction_hint_mismatch')
    return row


def discover(c,g,hint):
    row=validate_hint(hint,g);tx=row.get('transaction_hash','');receipt=None;logs=[]
    if isinstance(tx,str) and HEX32.fullmatch(tx):
        receipt=c.request('eth_getTransactionReceipt',[tx])
        logs=[v for v in (receipt or {}).get('logs',[]) if v.get('address','').lower()==CTF and v.get('topics',[])[:2]==[CONDITION_RESOLUTION,g['conditionId']]]
    if len(logs)==1:return logs[0],receipt
    final=c.request('eth_getBlockByNumber',['finalized',False]);height=int(final['number'],16)
    published=row.get('resolved_block')
    if type(published) is int and 0<=published<=height:anchor=published
    else:
        if not g.get('closedTime'):raise ValueError('native_resolution_transaction_and_close_search_hint_unavailable')
        target=at(g['closedTime']).timestamp();low=0;high=height
        while low<high:
            middle=(low+high)//2;header=c.request('eth_getBlockByNumber',[hex(middle),False])
            if int(header['timestamp'],16)<target:low=middle+1
            else:high=middle
        anchor=low
    query={'address':CTF,'topics':[CONDITION_RESOLUTION,g['conditionId']],'fromBlock':hex(max(0,anchor-1500)),'toBlock':hex(min(height,anchor+1500))}
    logs=c.request('eth_getLogs',[query])
    if not isinstance(logs,list) or len(logs)!=1:raise ValueError('unique_native_condition_resolution_log_unavailable_in_published_close_bracket')
    log=logs[0]
    if log.get('address','').lower()!=CTF or log.get('topics',[])[:2]!=query['topics'] or not int(query['fromBlock'],16)<=int(log['blockNumber'],16)<=int(query['toBlock'],16):raise ValueError('native_log_outside_exact_query')
    return log,c.request('eth_getTransactionReceipt',[log['transactionHash']])
