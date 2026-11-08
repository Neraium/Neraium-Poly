"""Stream immutable original studies into volume research; never trading authority."""
import json
from collections import defaultdict
from pathlib import Path
from typing import Literal

from pydantic import Field, field_serializer, field_validator

from neraium_poly.contracts import Record
from neraium_poly.data.connectivity import _payload_bytes
from neraium_poly.research.phase14.relationships import digest
from neraium_poly.research.phase16.checkpoints import unpack_checkpoint
from neraium_poly.research.phase24.archive import latest
from neraium_poly.research.phase25.dependencies import at
from neraium_poly.research.phase27.payout import PayoutForecastStudy, propose_spx
from neraium_poly.research.phase33.storage import decode_report, encode_report, pack_dense_checkpoint


class VolumeEnrollment(Record):
    policy: dict
    research_only: Literal[True] = True
    trading_authority: Literal[False] = False


class ForecastWindow(Record):
    parent_enrollment_id: str
    window: int
    original_source_id: str | None = None
    original_source_sha256: str | None = None
    research_only: Literal[True] = True
    trading_authority: Literal[False] = False


class VolumeForecastStudy(PayoutForecastStudy):
    parent_enrollment_id: str


class VolumeStudy(Record):
    enrollment_id: str
    evaluation_bucket: int
    source_anchor: dict
    decision_frame: dict
    decision_frame_sha256: str
    report: dict
    totals: dict = Field(default_factory=dict)
    research_only: Literal[True] = True
    trading_authority: Literal[False] = False
    certification_authority: Literal[False] = False


    @field_validator("report",mode="before")
    @classmethod
    def report_from_wire(cls,value):return decode_report(value)

    @field_serializer("report")
    def report_to_wire(self,value):return encode_report(value)


class ForecastStore:
    def __init__(self, store, parent):self.store,self.parent=store,parent
    def get(self, identity):
        value=self.store.get(identity)
        if value is None:return None
        body=value if isinstance(value,dict) else json.loads(value[1])
        if 'parent_enrollment_id' in body:
            if body['parent_enrollment_id']!=self.parent:raise ValueError('forecast parent enrollment mismatch')
            body={k:v for k,v in body.items() if k!='parent_enrollment_id'}
        return body
    def append(self, record):
        if not isinstance(record,PayoutForecastStudy):raise TypeError('payout research namespace only')
        value=record.model_dump();value['parent_enrollment_id']=self.parent;value['source']='neraium-poly/payout-research/v28'
        return self.store.append(VolumeForecastStudy.model_validate(value))


class VolumeResearch:
    def __init__(self,store,index,*,clock,can_write,builder=None,combiner=None,shadow=None,on_report=None):
        self.store,self.index,self.clock,self.can_write=store,index,clock,can_write
        self.builder,self.combiner,self.shadow=builder,combiner,shadow;self.on_report=on_report;self.report_callback_error=None
        self.forecast_tokens=();self.error=None;self.report=None;self.last_bucket=None;self.totals={'evaluations':0,'finding_rows':0}
        root=Path(__file__).parent
        policy={'version':'phase33-lossless-volume-storage-v1','implementation_sha256':digest([p.read_text() for p in sorted(root.glob('*.py'))]),
            'event_research_code_sha256':digest([p.read_text() for p in sorted(root.with_name('phase30').glob('*.py'))]),
            'diagnostic_code_sha256':digest([p.read_text() for p in sorted(root.with_name('phase29').glob('*.py'))]),
            'publication_namespace_sha256':digest(str(getattr(store,'directory',getattr(store,'path','controlled')))),
            'cadence_seconds':60,'forecast_refresh_seconds':300,'forecast_count_scope':'300s window plus verified source SHA; source refreshes are not independent outcomes',
            'original_forecast_budget':120,'original_selection':'future events with current metadata first, then newest immutable forecast','maximum_study_decoded_bytes':32*1024**2,'raw_study_cache_bytes':0,
            'research_minimum_per_share_edge':None,'certified_threshold_unchanged':.03,'actual_account_routing':False,
            'shadow_authority':'independent source replay required; existing accounts untouched','frame_evidence':'lossless level6 packed full current frame','report_evidence':'lossless bounded canonical report envelope, legacy plaintext supported',
            'storage_codec_sha256':digest(Path(encode_report.__code__.co_filename).read_text())}
        self.enrollment_id=digest(['volume-research-enrollment',policy])
        if store.get(self.enrollment_id) is None:
            if not can_write():raise ValueError('volume enrollment archive unavailable')
            now=at(clock());store.append(VolumeEnrollment(id=self.enrollment_id,timestamp=now,available_at=now,source='neraium-poly/volume-research/v28',policy=policy))
        else:
            value=store.get(self.enrollment_id);body=value if isinstance(value,dict) else json.loads(value[1])
            if body.get('policy')!=policy:raise ValueError('volume enrollment policy mismatch')
        records=latest(store,'VolumeStudy',limit=1)
        if records and records[0]['enrollment_id']==self.enrollment_id:self._adopt(records[0])

    def _adopt(self,value):
        row=VolumeStudy.model_validate(value)
        if row.enrollment_id!=self.enrollment_id:raise ValueError('volume checkpoint enrollment mismatch')
        frame=unpack_checkpoint(row.decision_frame)
        if digest(frame)!=row.decision_frame_sha256:raise ValueError('volume frame integrity mismatch')
        if any(r.get('frame_sha256')!=row.decision_frame_sha256 for r in row.report.get('findings',[]) if r.get('frame_sha256') is not None):raise ValueError('volume finding frame binding mismatch')
        if row.report.get('trading_authority') is not False:raise ValueError('volume authority boundary')
        self.last_bucket=row.evaluation_bucket;self.totals=row.totals;self.report=self._summary(row.report,row.timestamp.isoformat(),row.id)

    def _original(self,identity,sha):
        raw=self.store.get(identity)
        if raw is None:raise ValueError('volume original source unavailable')
        value=raw if isinstance(raw,dict) else json.loads(raw[1])
        if digest(value)!=sha:raise ValueError('volume original source hash mismatch')
        if _payload_bytes(value,32*1024**2)>32*1024**2:raise ValueError('volume original decoded byte budget exceeded')
        return value

    @staticmethod
    def _summary(report,as_of,identity):
        rows=report.get('findings',[])
        return {'status':'research_only','as_of':as_of,'record_id':identity,'counts':report.get('counts',{}),'pipeline_counts':report.get('pipeline_counts',{}),'alignment':report.get('alignment',{}),'source_maturity':report.get('source_maturity',{}),
            'rankings':report.get('rankings',[]),'scenario_rankings':report.get('scenario_rankings',[]),
            'rejections':report.get('rejections',{}),'source_deferred':report.get('source_deferred',{}),
            'forecast_refresh_rejections':report.get('forecast_refresh_rejections',{}),
            'window_forecast_records_available':report.get('window_forecast_records_available',0),
            'latest_findings':rows[:5],'portfolio':report.get('portfolio',{}),'sii':report.get('sii',{}),
            'research_only':True,'trading_authority':False,'certification_authority':False,'raw_study_cache_bytes':0}

    def step(self,frame,*,native_fee_observations=None):
        now=at(self.clock());bucket=int(now.timestamp())//60
        if bucket==self.last_bucket or not self.can_write():return False
        identity=digest(['volume-study',self.enrollment_id,bucket]);existing=self.store.get(identity)
        if existing is not None:
            self._adopt(existing if isinstance(existing,dict) else json.loads(existing[1]));return False
        if self.index.report(as_of=now).get('projection',{}).get('status')!='caught_up':return False
        entries,anchor=self.index.snapshot()
        if anchor is None or at(anchor['available_at'])>now:raise ValueError('current anchored volume source required')
        refs={}
        for row in entries:
            if row.get('type')=='forecast' and row.get('replay_verified'):
                fid=row['forecast_id']
                if fid in refs and refs[fid]['forecast_sha256']!=row['forecast_sha256']:raise ValueError('conflicting volume original identity')
                refs.setdefault(fid,row)
        current_tokens={m.token_id for m in frame.markets} if hasattr(frame,'markets') else set()
        selected=sorted(refs.values(),key=lambda r:(bool(r['forecast'].get('event_end_time') and at(r['forecast']['event_end_time'])>now),r['forecast'].get('token_id') in current_tokens,at(r['forecast']['timestamp']),r['forecast_id']),reverse=True)[:120]
        self.forecast_tokens=tuple(dict.fromkeys(r['forecast']['token_id'] for r in selected if r['forecast'].get('token_id')))
        groups=defaultdict(list)
        for row in selected:groups[row['source_id']].append(row)
        verified={r['forecast_id'] for r in selected};deferred={'outside_original_budget':len(refs)-len(selected),'decoded_source_budget':0};refresh_rejections={};extra=[]
        if self.builder is None:
            generation_ids={}
            for row in selected:
                f=row['forecast']
                if f.get('model_id','').startswith('spx-'):
                    generation_ids.setdefault((f['event_id'],f['market_id'],f['token_id']),row['forecast_id'])
            derive_ids=set(generation_ids.values())
            # Frozen independent model recomputation at NEW cutoff and current book,
            # under a declared sampling window; never redate an old prediction.
            window=int(now.timestamp())//300;window_id=digest(['volume-forecast-window',self.enrollment_id,window])
            if self.store.get(window_id) is None:
                self.store.append(ForecastWindow(id=window_id,timestamp=now,available_at=now,source='neraium-poly/forecast-window/v28',parent_enrollment_id=self.enrollment_id,window=window))
            for source_id,rows in groups.items():
                if not any(r['forecast_id'] in derive_ids for r in rows):continue
                study=self._original(source_id,rows[0]['source_study_sha256'])
                source_window=digest(['volume-source-window',window_id,source_id,rows[0]['source_study_sha256']])
                if self.store.get(source_window) is None:
                    self.store.append(ForecastWindow(id=source_window,timestamp=now,available_at=now,source='neraium-poly/forecast-window/v28',parent_enrollment_id=self.enrollment_id,window=window,original_source_id=source_id,original_source_sha256=rows[0]['source_study_sha256']))
                derived,reasons=propose_spx([study],frame,store=ForecastStore(self.store,self.enrollment_id),enrollment_id=source_window,as_of=now,verified_forecast_ids=derive_ids,clock=self.clock)
                for logical in derived:
                    physical=self.store.get(logical['id'])
                    body=physical if isinstance(physical,dict) else json.loads(physical[1])
                    typed=VolumeForecastStudy.model_validate(body)
                    if typed.parent_enrollment_id!=self.enrollment_id or typed.forecasts!=logical['forecasts']:
                        raise ValueError('physical prospective forecast publication mismatch')
                    extra.append(typed.model_dump(mode='json'))
                for k,v in reasons.items():refresh_rejections[k]=refresh_rejections.get(k,0)+v
                del study
        if self.builder is None:
            from .findings import build_economic_findings as builder
            from .findings import combine_economic_reports as combiner
        else:builder,combiner=self.builder,self.combiner
        decision=at(self.clock());reports=[]
        for source_id,rows in groups.items():
            try:study=self._original(source_id,rows[0]['source_study_sha256'])
            except ValueError as error:
                if 'decoded byte budget' not in str(error):raise
                deferred['decoded_source_budget']+=len(rows);continue
            for row in rows:
                f=next(f for f in study['forecasts'] if f['id']==row['forecast_id'])
                if digest(f)!=row['forecast_sha256']:raise ValueError('volume forecast source binding mismatch')
            reports.append(builder([study],frame,as_of=decision,verified_forecast_ids=verified,**({'included_forecast_ids':[r['forecast_id'] for r in rows]} if self.builder is None else {}),**({'native_fee_observations':native_fee_observations} if native_fee_observations is not None else {})))
            del study
        for study in extra:
            reports.append(builder([study],frame,as_of=decision,verified_forecast_ids={f['id'] for f in study['forecasts']},**({'native_fee_observations':native_fee_observations} if native_fee_observations is not None else {})))
        report=combiner(reports,as_of=decision)
        if self.builder is None:
            from neraium_poly.research.phase29.alignment import classify_alignment
            report['alignment']=classify_alignment(report['findings'],frame,as_of=decision,
                subscribed_tokens=frame.connectivity.get('research_subscribed_token_ids',()))
            from neraium_poly.research.phase29.outcomes import maturity_report
            report['source_maturity']=maturity_report(entries,as_of=decision)

        if report.get('trading_authority') is not False or report.get('research_only') is not True:raise ValueError('volume authority boundary rejected')
        report['source_deferred']=deferred;report['forecast_refresh_rejections']=refresh_rejections
        report['source_projection_forecast_count']=len(refs);report['window_forecast_records_available']=len(extra)
        raw=frame.model_dump(mode='json') if hasattr(frame,'model_dump') else frame;packed=pack_dense_checkpoint(raw);sha=digest(raw)
        if any(r.get('frame_sha256')!=sha for r in report.get('findings',[]) if r.get('frame_sha256') is not None):raise ValueError('volume finding frame binding mismatch')
        if digest(unpack_checkpoint(packed))!=sha:raise ValueError('volume frame lossless roundtrip failed')
        if len(json.dumps(report,separators=(',',':')).encode())>8*1024**2:raise ValueError('bounded volume report required')
        if not self.can_write():raise ValueError('volume publication archive backpressure')
        totals={'evaluations':self.totals['evaluations']+1,'finding_rows':self.totals['finding_rows']+len(report.get('findings',[]))}
        row=VolumeStudy(id=identity,timestamp=decision,available_at=at(self.clock()),source='neraium-poly/volume-research/v28',enrollment_id=self.enrollment_id,evaluation_bucket=bucket,source_anchor=anchor,decision_frame=packed,decision_frame_sha256=sha,report=report,totals=totals)
        self.store.append(row);self.last_bucket=bucket;self.totals=totals;self.report=self._summary(report,row.timestamp.isoformat(),identity);self.error=None
        if self.shadow is not None:self.shadow.step(report,frame)
        if self.on_report is not None:
            try:
                self.on_report(row,frame,entries);self.report_callback_error=None
            except Exception as error:  # noqa: BLE001 - optional research observer cannot invalidate a committed economic record
                self.report_callback_error=f"{type(error).__name__}:{str(error)[:160]}"
        return True

    def status(self):
        return {**(self.report or {'status':'pending'}),'runtime_error':self.error,'report_callback_error':self.report_callback_error,'totals':dict(self.totals),'shadow':self.shadow.status() if self.shadow else {'status':'disabled'},'research_only':True,'trading_authority':False,'raw_study_cache_bytes':0,'counter_scope':'current versioned research enrollment evaluation rows; prior records retained; parent-event independence reported separately'}
