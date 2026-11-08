"""Persist derived native-fee diagnostics without new accounts or evidence fetches."""
import json
from typing import Literal

from neraium_poly.contracts import Record
from neraium_poly.research.phase14.relationships import digest
from neraium_poly.research.phase25.dependencies import at

from .economics import annotate_pair_fees


class PairFeeStudy(Record):
    source_pair_study_id:str
    source_pair_study_sha256:str
    source_volume_study_id:str
    report:dict
    research_only:Literal[True]=True
    trading_authority:Literal[False]=False
    certification_authority:Literal[False]=False


class FeeHeadroomResearch:
    def __init__(self,store,*,clock,can_write,observations):
        self.store,self.clock,self.can_write,self.observations=store,clock,can_write,observations
        self.report=None;self.error=None

    def observe(self,volume,frame,pair_report):
        try:
            now=at(self.clock());decision=at(volume.timestamp)
            if now<decision or not pair_report or pair_report['frame_sha256']!=volume.decision_frame_sha256:raise ValueError('exact_causal_volume_frame_required')
            identity=digest(['pair-study-v32',volume.id,pair_report]);source=self.store.get(identity)
            if source is None:raise ValueError('committed_pair_study_required')
            body=source if isinstance(source,dict) else json.loads(source[1])
            if (body.get('id')!=identity or body.get('volume_study_id')!=volume.id
                or digest(body['report'])!=digest(pair_report)
                or body['volume_sha256']!=digest(volume.model_dump(mode='json'))
                or not decision<=at(body['timestamp'])<=at(body['available_at'])<=now):raise ValueError('pair_source_integrity_required')
            report=annotate_pair_fees(pair_report,frame,self.observations(decision),self.store,as_of=decision)
            if len(json.dumps(report,allow_nan=False).encode())>512*1024:raise ValueError('bounded_pair_fee_report_required')
            if not self.can_write():raise ValueError('pair_fee_archive_backpressure')
            rid=digest(['pair-fee-study-v33',identity,report]);existing=self.store.get(rid)
            if existing is None:self.store.append(PairFeeStudy(id=rid,timestamp=now,available_at=now,source='neraium-poly/native-fee-headroom/v33',
                source_pair_study_id=identity,source_pair_study_sha256=digest(body),source_volume_study_id=volume.id,report=report))
            else:
                old=existing if isinstance(existing,dict) else json.loads(existing[1])
                if old['source_pair_study_sha256']!=digest(body) or digest(old['report'])!=digest(report):raise ValueError('pair_fee_restart_binding_mismatch')
            self.report=report;self.error=None
        except (ValueError,KeyError,TypeError,OSError) as error:self.error=f'{type(error).__name__}:{str(error)[:160]}'

    def status(self):
        if self.error or self.report is None:return {'status':'withheld','reason':self.error,'research_only':True,'trading_authority':False}
        age=(at(self.clock())-at(self.report['as_of'])).total_seconds()
        if not 0<=age<=120:return {'status':'stale','last_at':self.report['as_of'],'research_only':True,'trading_authority':False}
        return {**self.report,'age_seconds':age}
