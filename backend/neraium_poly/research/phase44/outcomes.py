"""Bounded research payout reconciliation. No financial/certification authority."""
import asyncio
import json
from pathlib import Path
from typing import Literal

import httpx

from neraium_poly.contracts import Record
from neraium_poly.experimental.research_worker import _drain
from neraium_poly.research.phase14.relationships import digest
from neraium_poly.research.phase24.continuous import at
from neraium_poly.research.phase44.native import acquire, replay


class NativeCycle46(Record):
    capacity:dict
    attempted:int
    deferred:int
    cached_proofs:int


class NativePayout44(Record):
    forecast_id:str
    forecast_sha256:str
    original_study_sha256:str
    directory:str|None=None
    verified:bool
    reason:str
    proof:dict|None=None
    research_only:Literal[True]=True
    trading_authority:Literal[False]=False


def rebind(proof,original,forecast):
    keys=('market_id','event_id','token_id','rules_sha256')
    if any(forecast[k]!=original[k] for k in keys) or any(forecast['market'][k]!=original['market'][k] for k in ('resolution_rules','resolution_source','end_time','outcome','question')):
        raise ValueError('native_rebind_original_contract_mismatch')
    if not at(forecast['evidence_cutoff'])<=at(forecast['timestamp'])<at(proof['resolved_at']):raise ValueError('native_rebind_forecast_not_prospective')
    return {**proof,'forecast_id':forecast['id'],'original_forecast_sha256':digest(forecast)}


async def collect(bound,store,directory,*,clock,can_write,max_requests=2):
    if not 0<=max_requests<=2:raise ValueError('bounded native requests required')
    root=Path(directory);root.mkdir(parents=True,exist_ok=True);now=at(clock());found={};attempts={};cache={}
    wanted={(v['forecast']['market_id'],v['forecast']['event_id'],v['forecast']['token_id'],v['forecast']['rules_sha256']) for v in bound.values()}
    rows=store.latest('NativePayout44',256)
    failures={}
    for row in rows:
        attempts.setdefault(row['forecast_id'],row['available_at'])
        if not row['verified']:
            original=bound.get(row['forecast_id'])
            if original:
                f=original['forecast'];key=(f['market_id'],f['token_id'])
                if key not in failures:failures[key]=row
            continue
        if tuple((row.get('proof') or {}).get(k) for k in ('market_id','event_id','token_id','rules_sha256')) not in wanted:continue
        path=root/row['directory']
        if path.parent!=root or path.is_symlink():raise ValueError('unsafe_native_recovery_path')
        # One bounded proof replay per condition in this pass, never all history.
        if row['directory'] not in cache:
            proof=replay(path);original=json.loads((path/'bundle.json').read_bytes())['forecast']
            if digest(original)!=row['forecast_sha256'] or proof!=row['proof']:raise ValueError('native_stored_proof_original_mismatch')
            cache[row['directory']]=(proof,original)
        proof,original=cache[row['directory']]
        for fid,item in bound.items():
            try:result=rebind(proof,original,item['forecast'])
            except ValueError:continue
            found[fid]=result
    due=sorted((fid for fid,v in bound.items() if at(v['forecast']['event_end_time'])<=now and fid not in found),key=lambda fid:(attempts.get(fid,''),bound[fid]['forecast']['event_end_time'],fid))
    requests=0;tried=set();deferred=0
    def finish():
        used=sum(p.stat().st_size for p in root.rglob('*') if p.is_file())
        summary=NativeCycle46(id=digest(['native-cycle46',now.isoformat(),sorted(bound),requests,deferred,len(found),used]),timestamp=now,available_at=at(clock()),source='neraium-poly/native-capacity/v46',
            capacity={'limit_bytes':64*1024**2,'used_bytes':used,'remaining_bytes':max(0,64*1024**2-used),'originals_deleted':False},attempted=requests,deferred=deferred,cached_proofs=len(found))
        if can_write():store.append(summary)
        return found
    for fid in due:
        f=bound[fid]['forecast'];key=(f['market_id'],f['token_id'])
        failure=failures.get(key)
        if failure:
            reason=failure['reason'];seconds=1800 if 'pending_or_disputed' in reason else 3600
            if (now-at(failure['available_at'])).total_seconds()<seconds:deferred+=1;continue
        if key in tried or requests>=max_requests:continue
        tried.add(key)
        if not can_write():raise ValueError('native_publication_capacity_unavailable')
        # Same existing64MiB guard, including all legacy originals. No cleanup,
        # replacement or guard increase is needed for the new verifier.
        used=sum(p.stat().st_size for p in root.rglob('*') if p.is_file())
        remaining=64*1024**2-used
        if remaining<=0:return finish()  # Never discard independently replayed cached proofs on capacity exhaustion.
        requests+=1
        name='v44-'+digest([fid,now.isoformat()]);path=root/name;proof=None
        try:
            # Drain cancellation before another SQLite/evidence owner can run.
            proof=await _drain(asyncio.create_task(asyncio.to_thread(acquire,f,path,disk_budget=min(2*1024**2,remaining))))
            reason='finalized_standard_CTF_and_exact_original_outcome_asset'
        except (ValueError,KeyError,TypeError,httpx.HTTPError,OSError) as error:
            reason=type(error).__name__+':'+str(error)[:200]
        ended=at(clock())
        row=NativePayout44(id=digest(['native44',fid,name,reason]),timestamp=ended,available_at=ended,source='neraium-poly/research-native44',
            forecast_id=fid,forecast_sha256=digest(f),original_study_sha256=bound[fid]['study_sha256'] if 'study_sha256' in bound[fid] else digest(bound[fid]['study']),directory=name,verified=proof is not None,reason=reason,proof=proof)
        if not can_write():raise ValueError('native_publication_capacity_unavailable')
        store.append(row)
        if proof is not None:
            for other,item in bound.items():
                try:found[other]=rebind(proof,f,item['forecast'])
                except ValueError:continue
    return finish()
