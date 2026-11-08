"""Verified event summaries sampled off operational HTTP paths, never authority."""
import copy
import json
import time
from datetime import UTC, datetime
from threading import RLock


class EventSummaryCache:
    def __init__(self,*,clock=None,monotonic=None,max_age_seconds=120):
        self.clock=clock or (lambda:datetime.now(UTC));self.monotonic=monotonic or time.monotonic
        self.max_age=max_age_seconds;self.lock=RLock();self.value=None;self.at=None;self.completed=None;self.error=None

    def refresh(self,producer):
        started=self.clock();value=producer()
        if not isinstance(value,dict) or value.get('status')=='unavailable':raise ValueError('full_event_summary_verification_unavailable')
        historical=value.get('historical_qualification')
        if isinstance(historical,dict):
            value={**value,'historical_qualification':{k:historical.get(k) for k in (
                'status','events','chain_corroborated_exact_settlement_groups','qualified_training_events',
                'qualified_heldout_events','qualification_funnel','requirements','missing_fields','blockers') if k in historical}}
        # No raw evidence/history is needed by an operational counter endpoint.
        if len(json.dumps(value,default=str,allow_nan=False).encode())>256*1024:raise ValueError('bounded_verified_operational_summary_required')
        completed=self.clock();now=self.monotonic()
        with self.lock:self.value=copy.deepcopy(value);self.at=now;self.completed=completed;self.started=started;self.error=None

    def failed(self,error):
        with self.lock:self.error=type(error).__name__

    def snapshot(self):
        with self.lock:
            age=self.monotonic()-self.at if self.at is not None else None
            meta={'summary_verified_completed_at':self.completed.isoformat() if self.completed else None,
                'summary_age_seconds':age,'summary_max_age_seconds':self.max_age,'summary_refresh_error':self.error,
                'summary_scope':'background full ledger/source verification; sampled counters, never current execution authority',
                'certification_authority':False,'trading_authority':False}
            if self.error is not None or age is None or age<0 or age>self.max_age:
                return {'status':'pending' if age is None else 'stale','research_status':'verified event summary unavailable or expired',
                    'independent_models_enabled':0,'summary_status':'withheld',**meta}
            return {**copy.deepcopy(self.value),'summary_status':'cached_verified_snapshot',**meta}
