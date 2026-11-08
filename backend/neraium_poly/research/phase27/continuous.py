"""Bounded prospective economic findings beside the unchanged trading engine."""
import json
from collections import OrderedDict
from pathlib import Path
from typing import Literal

from pydantic import Field

from neraium_poly.contracts import Record
from neraium_poly.research.phase14.relationships import digest
from neraium_poly.research.phase16.checkpoints import pack_checkpoint, unpack_checkpoint
from neraium_poly.research.phase24.archive import latest
from neraium_poly.research.phase25.dependencies import at


class FindingsEnrollment(Record):
    policy: dict
    research_only: Literal[True] = True
    trading_authority: Literal[False] = False


class EconomicFindingStudy(Record):
    enrollment_id: str
    source_anchor: dict
    findings: dict
    decision_frame: dict
    decision_frame_sha256: str
    totals: dict = Field(default_factory=dict)
    evaluation_bucket: int
    research_only: Literal[True] = True
    trading_authority: Literal[False] = False
    certification_authority: Literal[False] = False


class FindingsResearch:
    def __init__(self, store, index, *, clock, can_write, builder=None):
        self.store, self.index, self.clock, self.can_write = store, index, clock, can_write
        self.builder = builder
        self.cache = OrderedDict()
        self.cache_bytes = 0
        self.error = None
        self.report = None
        self.last_bucket = None
        self.totals = {'evaluations': 0, 'findings': 0}
        root = Path(__file__).parent
        try:
            from .forecasting import definitions
            model_definitions = definitions()
        except ImportError:
            model_definitions = []
        policy = {'version': 'phase27-prospective-findings-v1', 'code_sha256': digest([p.read_text() for p in [Path(__file__), root/'findings.py', root/'forecasting.py', root/'payout.py'] if p.is_file()]),
                  'publication_namespace_sha256': digest(str(getattr(store, 'directory', getattr(store, 'path', 'controlled-event-store')))), 'decision_evidence': 'complete losslessly packed SharedMarketFrame, SHA verified before publication/recovery', 'cadence_seconds': 60, 'maximum_forecasts': 128, 'raw_cache_bytes': 32*1024**2,
                  'scope': 'source-replayed original forecasts and current public books; repeated evaluations are not independent events',
                  'model_promotion': False, 'paper_account_routing': False, 'payout_models': model_definitions, 'payout_selection': 'global baseline only; weekday feature rejected by heldout evaluation', 'payout_horizons_hours': [48,24,6,1]}
        self.enrollment_id = digest(['phase27-findings-enrollment', policy])
        previous = self.store.get(self.enrollment_id)
        if previous is None:
            if not self.can_write():
                raise ValueError('findings enrollment blocked by archive admission')
            now = at(clock())
            self.store.append(FindingsEnrollment(id=self.enrollment_id, timestamp=now, available_at=now,
                                                source='neraium-poly/findings/v27', policy=policy))
        else:
            body = previous if isinstance(previous, dict) else json.loads(previous[1])
            if body.get('policy') != policy:
                raise ValueError('findings enrollment policy mismatch')
        records = latest(store, 'EconomicFindingStudy', limit=1)
        if records and records[0]['enrollment_id'] == self.enrollment_id:
            self._adopt(records[0])

    def _adopt(self, value):
        record = EconomicFindingStudy.model_validate(value)
        if record.enrollment_id != self.enrollment_id:
            raise ValueError('findings recovery enrollment mismatch')
        frame = unpack_checkpoint(record.decision_frame)
        if digest(frame) != record.decision_frame_sha256:
            raise ValueError('findings decision frame integrity mismatch')
        if any(row.get('frame_sha256') != record.decision_frame_sha256 for row in record.findings.get('findings', []) if row.get('frame_sha256') is not None):
            raise ValueError('finding decision frame hash binding mismatch')
        self.last_bucket = record.evaluation_bucket
        self.totals = record.totals
        self.report = self._summary(record.findings, record.timestamp.isoformat(), record.id)

    def _load(self, identity, expected):
        if identity in self.cache:
            value, size, sha = self.cache.pop(identity)
            self.cache[identity] = (value, size, sha)
            if sha != expected:
                raise ValueError('cached original study binding changed')
            return value
        original = self.store.get(identity)
        if original is None:
            raise ValueError('original findings source missing')
        value = original if isinstance(original, dict) else json.loads(original[1])
        size = len(json.dumps(value, separators=(',', ':')).encode())
        sha = digest(value)
        if sha != expected or size > 16*1024**2:
            raise ValueError('bounded exact original findings source required')
        while self.cache and self.cache_bytes+size > 32*1024**2:
            _key, (_old, old_size, _sha) = self.cache.popitem(last=False)
            self.cache_bytes -= old_size
        self.cache[identity] = (value, size, sha)
        self.cache_bytes += size
        return value

    @staticmethod
    def _summary(report, timestamp, identity):
        rows = report.get('findings', [])
        return {'status': 'research_only', 'as_of': timestamp, 'record_id': identity,
                'counts': report.get('counts', {}), 'rejections': report.get('rejections', {}),
                'payout_generation_rejections': report.get('payout_generation_rejections', {}),
                'payout_status': report.get('payout_status'),
                'rankings': report.get('rankings', []), 'sii': report.get('sii', {}),
                'latest_findings': [{k: v for k, v in row.items() if k not in ('book', 'current_book', 'evidence')} for row in rows[:5]],
                'shadow_realized_pnl': None, 'shadow_orders': 0,
                'shadow_status': 'no validated execution-authorized strategy; no hypothetical fills invented',
                'research_only': True, 'trading_authority': False, 'certification_authority': False}

    def step(self, frame):
        now = at(self.clock())
        bucket = int(now.timestamp())//60
        if bucket == self.last_bucket or not self.can_write():
            return False
        identity = digest(['economic-findings', self.enrollment_id, bucket])
        existing = self.store.get(identity)
        if existing is not None:
            self._adopt(existing if isinstance(existing, dict) else json.loads(existing[1]))
            return False
        projection = self.index.report(as_of=now)
        if projection.get('projection', {}).get('status') != 'caught_up':
            return False
        entries, anchor = self.index.snapshot()
        if anchor is None or at(anchor['available_at']) > now:
            raise ValueError('anchored source projection required for findings')
        selected = {}; studies = {}; verified = set()
        for entry in entries:
            if entry.get('type') != 'forecast' or not entry.get('replay_verified'):
                continue
            fid = entry['forecast_id']
            if fid in selected:
                if selected[fid] != entry['forecast_sha256']:
                    raise ValueError('conflicting findings forecast identity')
                continue
            if len(selected) >= 128:
                raise ValueError('findings forecast budget exceeded; no silent registry truncation')
            study = self._load(entry['source_id'], entry['source_study_sha256'])
            f = next(x for x in study['forecasts'] if x['id'] == fid)
            if digest(f) != entry['forecast_sha256']:
                raise ValueError('original findings forecast hash mismatch')
            studies[study['id']] = study
            selected[fid] = entry['forecast_sha256']
            verified.add(fid)
        payout_rejections = {}
        if self.builder is None:
            from .payout import propose_spx
            extra, payout_rejections = propose_spx(list(studies.values()), frame, store=self.store, enrollment_id=self.enrollment_id, as_of=now, verified_forecast_ids=verified, clock=self.clock)
            for study in extra:
                studies[study['id']] = study
                verified.update(f['id'] for f in study['forecasts'])
            from .findings import build_findings
            builder = build_findings
        else:
            builder = self.builder
        decision = at(self.clock())
        report = builder(list(studies.values()), frame, as_of=decision, verified_forecast_ids=verified)
        report['payout_generation_rejections'] = payout_rejections
        report['payout_status'] = 'global baseline only; weekday feature failed heldout comparison; no trading authority'
        if report.get('trading_authority') is not False or report.get('research_only') is not True:
            raise ValueError('findings authority boundary rejected')
        if len(json.dumps(report, separators=(',', ':')).encode()) > 8*1024**2:
            raise ValueError('findings result byte budget exceeded')
        if not self.can_write():
            raise ValueError('findings publication blocked by archive admission')
        totals = {'evaluations': self.totals['evaluations']+1,
                  'findings': self.totals['findings']+len(report.get('findings', []))}
        raw_frame = frame.model_dump(mode='json') if hasattr(frame, 'model_dump') else frame
        packed = pack_checkpoint(raw_frame)
        frame_sha = digest(raw_frame)
        if digest(unpack_checkpoint(packed)) != frame_sha:
            raise ValueError('decision frame lossless roundtrip failed')
        if any(row.get('frame_sha256') != frame_sha for row in report.get('findings', []) if row.get('frame_sha256') is not None):
            raise ValueError('findings decision/frame mismatch')
        record = EconomicFindingStudy(id=identity, timestamp=decision, available_at=at(self.clock()),
            source='neraium-poly/findings/v27', enrollment_id=self.enrollment_id, source_anchor=anchor,
            findings=report, decision_frame=packed, decision_frame_sha256=frame_sha, totals=totals, evaluation_bucket=bucket)
        self.store.append(record)
        self.last_bucket, self.totals = bucket, totals
        self.report = self._summary(report, record.timestamp.isoformat(), identity)
        self.error = None
        return True

    def status(self):
        return {**(self.report or {'status': 'pending', 'trading_authority': False}),
                'runtime_error': self.error, 'totals': dict(self.totals), 'raw_cache_bytes': self.cache_bytes,
                'counter_scope': 'enrollment cumulative evaluation rows, not independent events',
                'cadence_seconds': 60, 'research_only': True, 'trading_authority': False}
