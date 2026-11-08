"""Bounded native/independent verification scheduler; no guessed or price-based labels."""

import asyncio
import importlib
from collections import Counter
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

from neraium_poly.contracts import Record
from neraium_poly.research.phase14.relationships import digest
from neraium_poly.research.phase16.checkpoints import pack_checkpoint, unpack_checkpoint
from neraium_poly.research.phase24.archive import latest
from neraium_poly.research.phase24.continuous import at
from neraium_poly.research.phase24.evaluation import acquire_nfl_outcome, replay_nfl_outcome
from pydantic import Field


class DomainOutcomeStudy(Record):
    operation: Literal['index','outcome_check']
    original_study_id: str | None=None
    original_study_sha256: str | None=None
    original_kind: str | None=None
    forecast_id: str | None=None
    adapter: str | None=None
    result: dict=Field(default_factory=dict)
    checkpoint: dict
    checkpoint_sha256: str
    research_only: Literal[True]=True
    trading_authority: Literal[False]=False
    certification_authority: Literal[False]=False


def replay_domain_outcome(row,study,f,*,evidence_root,as_of,modules=None):
    adapter=row['adapter']
    if adapter not in ('weather','economics','finance','sports'):raise ValueError('unsupported domain outcome adapter')
    if digest(study)!=row['original_study_sha256'] or row['forecast_id']!=f['id']:
        raise ValueError('outcome original binding mismatch')
    if row.get('original_study_id',study['id'])!=study['id']:raise ValueError('outcome original record identity mismatch')
    members=[x for x in study.get('forecasts',[]) if x.get('id')==f['id']]
    if len(members)!=1 or digest(members[0])!=digest(f):raise ValueError('unique immutable forecast membership required')
    module=modules[adapter] if modules is not None else importlib.import_module('neraium_poly.research.phase24.'+adapter)
    if row['result'].get('verification_protocol')=='official-sports-v26' and adapter=='sports':
        from neraium_poly.research.phase26.outcomes import replay_sport_outcome
        outcome_replay=replay_sport_outcome
    else:
        if not hasattr(module,'replay_outcome'):raise ValueError('domain outcome replay implementation unavailable')
        outcome_replay=module.replay_outcome
    byid={e['id']:e for e in study.get('evidence',[])}
    if len(byid)!=len(study.get('evidence',[])):raise ValueError('duplicate outcome source evidence identity')
    evidence=[byid[x] for x in f['evidence_ids']]
    replay=module.replay(f,evidence,as_of=as_of)
    if not isinstance(replay,dict) or replay.get('verified') is not True:raise ValueError('original domain model/source replay failed')
    proof=outcome_replay(row['result'],study,f,evidence_root=Path(evidence_root)/adapter,as_of=as_of)
    if (not isinstance(proof,dict) or proof.get('verified') is not True or proof.get('forecast_id')!=f['id']
        or any(proof.get(k)!=f[k] for k in ('event_id','market_id','token_id','rules_sha256'))
        or not at(study['available_at'])<at(proof['resolved_at'])<=at(proof['available_at'])<=at(as_of)):
        raise ValueError('independently replayed exact prospective outcome required')
    return proof


class DomainOutcomes:
    def __init__(self,store,directory,*,clock=None,can_write=None):
        self.store,self.directory=store,Path(directory);self.clock=clock or (lambda:datetime.now(UTC));self.can_write=can_write or (lambda:True)
        self.state={'version':'phase24-outcome-index-v1','last_at':None,'pending':{},'verified':{},'checked':{},'source_heads':{},'checks':0,'last_reasons':{},'sequence':0}
        rows=store.latest('DomainOutcomeStudy',limit=1)
        if rows:
            row=DomainOutcomeStudy.model_validate(rows[0]);s=unpack_checkpoint(row.checkpoint)
            if digest(s)!=row.checkpoint_sha256 or s['last_at']!=row.available_at.isoformat() or len(s['pending'])>8192:
                raise ValueError('domain outcome checkpoint integrity/bounds mismatch')
            self.state=s

    def _commit(self,s,operation,**fields):
        now=at(self.clock())
        if s['last_at'] and now<at(s['last_at']):raise ValueError('outcome clock regression')
        s['last_at']=now.isoformat();s['sequence']+=1
        row=DomainOutcomeStudy(id=f"{s['sequence']:012d}:"+digest([operation,s,fields]),timestamp=now,available_at=now,
            source='neraium-poly/domain-outcome/v24',operation=operation,checkpoint=pack_checkpoint(s),checkpoint_sha256=digest(s),**fields)
        if not self.can_write():raise ValueError('outcome archive backpressure')
        self.store.append(row);self.state=s

    def _module(self,adapter):return importlib.import_module('neraium_poly.research.phase24.'+adapter)

    def _replay(self,*args,**kwargs):return replay_domain_outcome(*args,**kwargs)

    def _due(self,p,now):
        return at(p['end'])+(timedelta(hours=4) if p['adapter'] in ('legacy_nfl','sports') else timedelta())<=now

    async def step(self):
        now=at(self.clock())
        if not self.can_write() or self.state['last_at'] and (now-at(self.state['last_at'])).total_seconds()<300:return False
        from .operations import original
        s=deepcopy(self.state)
        for kind in ('DomainResearchStudy','ChallengerStudy'):
            rows=latest(self.store,kind)
            if s['source_heads'].get(kind) and s['source_heads'][kind] not in {r['id'] for r in rows}:raise ValueError('outcome index gap requires verified readonly backfill')
            for row in rows:
                for f in row.get('forecasts',[]):
                    if f['id'] in s['verified']:continue
                    adapter=f.get('adapter') if kind=='DomainResearchStudy' else 'legacy_nfl' if f.get('sports_mapping') else None
                    if not adapter:continue
                    if len(s['pending'])>=8192 and f['id'] not in s['pending']:raise ValueError('domain pending capacity reached')
                    s['pending'][f['id']]={'study_id':row['id'],'kind':kind,'adapter':adapter,'end':f['event_end_time']}
            if rows:s['source_heads'][kind]=rows[0]['id']
        self._commit(s,'index')
        due=[(fid,p) for fid,p in s['pending'].items() if self._due(p,now)]
        for fid,p in sorted(due,key=lambda x:s['checked'].get(x[0],''))[:2]:
            if not self.can_write():return False
            s=deepcopy(self.state);study=original(self.store,p['study_id']);f=next(x for x in study['forecasts'] if x['id']==fid)
            result={'status':'withheld','forecast_id':fid,'reason':'independent_outcome_adapter_unavailable'}
            try:
                if p['adapter']=='legacy_nfl':
                    result=await acquire_nfl_outcome(study,f,directory=self.directory/'legacy_nfl',clock=self.clock)
                    if result.get('status')=='verified':
                        await asyncio.to_thread(replay_nfl_outcome,result,study,f,evidence_root=self.directory/'legacy_nfl',as_of=at(self.clock()))
                else:
                    mod=self._module(p['adapter'])
                    result=await mod.verify_outcome(f,directory=self.directory/p['adapter'],clock=self.clock)
                    if result.get('forecast_id',fid)!=fid:raise ValueError('outcome forecast identifier mismatch')
                    result['forecast_id']=fid
                    if result.get('status')=='verified' or result.get('verified') is True:
                        probe={'adapter':p['adapter'],'original_study_id':study['id'],'original_study_sha256':digest(study),'forecast_id':fid,'result':result}
                        await asyncio.to_thread(self._replay,probe,study,f,evidence_root=self.directory,as_of=at(self.clock()))
                        result['status']='verified' # only independently replayed proofs become scheduler labels
                    else:result.setdefault('status','withheld')
            except Exception as error: # noqa: BLE001 - failed verification cannot create an outcome
                result={'status':'withheld','forecast_id':fid,'reason':f'{type(error).__name__}:{str(error)[:160]}'}
            s['checks']+=1;s['checked'][fid]=at(self.clock()).isoformat()
            if result.get('status')=='verified':s['verified'][fid]={'model_id':f['model_id'],'event_id':f['event_id']};s['pending'].pop(fid,None)
            else:s['last_reasons'][p['adapter']]=result.get('reason',result.get('status'))
            self._commit(s,'outcome_check',original_study_id=study['id'],original_study_sha256=digest(study),
                original_kind=p['kind'],forecast_id=fid,adapter=p['adapter'],result=result)
        return bool(due)

    def status(self):
        return {'status':'research_only','last_at':self.state['last_at'],'pending_forecasts':len(self.state['pending']),
            'durable_verified_forecasts':len(self.state['verified']),'verified_by_model':dict(Counter(x['model_id'] for x in self.state['verified'].values())),'checks':self.state['checks'],'last_reasons':dict(self.state['last_reasons']),
            'independent_event_count':0,'certification_authority':False,'trading_authority':False}
