"""Bounded prospective refresh of EXISTING models, not new probability formulas.

Epochs enroll new point-in-time observations, never independent event groups.
Separate record kinds protect the original collectors' checkpoints and histories.
"""
import asyncio
import json
import time
from datetime import datetime

import httpx

from neraium_poly.experimental.contracts import SharedMarketFrame
from neraium_poly.experimental.feed_trace import TRACE_HEADER
from neraium_poly.research.phase14.relationships import digest
from neraium_poly.research.phase23.continuous import ChallengerStudy
from neraium_poly.research.phase24.continuous import DomainResearch, DomainResearchStudy
from neraium_poly.research.phase40.campaign import adapters
from neraium_poly.research.phase46.selection import InformationChallenger as ChallengerResearch


class RefreshDomainStudy(DomainResearchStudy):
    pass


class RefreshCryptoStudy(ChallengerStudy):
    pass


class Scope:
    def __init__(self,store,can_write,stop):self.base,self.admit,self.stop=store,can_write,stop;self.written=0
    def latest(self,kind,limit=1):return []  # Deliberately separate sampling enrollment, NOT trading-state recovery.
    def get(self,key):return self.base.get(key)
    def can_write(self):return not self.stop.is_set() and self.written<8*1024**2 and self.admit()
    def append(self,record):
        value=record.model_dump(mode='json');kind=RefreshDomainStudy if isinstance(record,DomainResearchStudy) else RefreshCryptoStudy
        item=kind.model_validate(value);size=len(item.model_dump_json().encode())
        if not self.can_write() or size+self.written>8*1024**2:raise ValueError('8MiB source-wave evidence bound reached; no truncation')
        self.base.append(item);self.written+=size


def read_reference(url, *, timing=None):
    began = time.monotonic()
    raw = bytearray()
    request = {}
    if timing is not None:
        request = {
            "headers": {TRACE_HEADER.decode("ascii"): timing.request_id},
            "extensions": {"trace": timing.http_event},
        }
    with httpx.Client(timeout=3, trust_env=False) as client, client.stream("GET", url, **request) as response:
        response.raise_for_status()
        for chunk in response.iter_bytes():
            if timing is not None:
                timing.mark("first_body_chunk")
            if time.monotonic()-began > 4 or len(raw)+len(chunk) > 8*1024**2:
                raise ValueError("bounded reference source frame exceeded")
            raw.extend(chunk)
    if timing is not None:
        timing.mark("body_complete")
    frame = SharedMarketFrame.model_validate_json(raw)
    if timing is not None:
        timing.mark("decoded")
    return frame


async def refresh(store,frame,*,clock,can_write,stop,frame_provider=None):
    began=time.monotonic();slot=int(clock().timestamp())//300
    # Persisted enrollment prevents duplicate collection on service restart in the same epoch.
    for kind in ('RefreshDomainStudy','RefreshCryptoStudy'):
        rows=store.latest(kind,1)
        if rows and int(datetime.fromisoformat(rows[0]['timestamp']).timestamp())//300==slot:
            return {'status':'already_recorded_epoch','epoch':slot,'bytes_written':0}
    scope=Scope(store,can_write,stop);errors=[]
    from neraium_poly.research.phase46.selection import VERSION, select
    async def run():
        domain_models=adapters()
        engines= [('domains',DomainResearch(scope,clock=clock,can_write=scope.can_write,adapters=domain_models)),('crypto',ChallengerResearch(scope,clock=clock,can_write=scope.can_write))]
        for label,engine in (engines if slot%2==0 else list(reversed(engines))):
            engine.enrollment_id=digest(['phase42-point-in-time-refresh-v1',label,engine.enrollment_id,slot,VERSION])
            engine.state['enrollment_id']=engine.enrollment_id
            if stop.is_set() or not scope.can_write():return
            try:
                observed=await frame_provider() if frame_provider else frame
                if label=='domains':observed=select(observed,clock(),models=domain_models)
                await engine.step(observed)
            except (ValueError,OSError) as error:errors.append(f'{label}:{type(error).__name__}:{str(error)[:120]}')
    job=asyncio.create_task(run())
    try:
        async with asyncio.timeout(90):
            while not job.done():
                if stop.is_set():job.cancel();break
                await asyncio.sleep(.25)
            await job
    finally:
        if not job.done():job.cancel()
        await asyncio.gather(job,return_exceptions=True)
    return {'status':'completed','epoch':slot,'bytes_written':scope.written,'elapsed_seconds':time.monotonic()-began,'errors':errors,
        'model_formulas_changed':False,'observations_are_not_independent_events':True}


def forecast_studies(store):
    """Look past empty scan rows without materializing full-history payloads."""
    output=[];size=2;scanned=0;deferred=0
    for kind in ('RefreshDomainStudy','RefreshCryptoStudy','DomainResearchStudy','ChallengerStudy'):
        connection=getattr(store,'catalog',None)
        table='records' if connection is not None else 'events'
        if connection is None:connection=store.connection
        with store._lock:
            ids=connection.execute(f'SELECT id FROM {table} WHERE kind=? ORDER BY available_at DESC,id DESC LIMIT 16',(kind,)).fetchall()
        for row in ids:
            original=store.get(row[0]);scanned+=1
            if not original or len(original[1].encode())>8*1024**2:continue
            payload=json.loads(original[1])
            if not payload.get('forecasts'):continue
            # Match the controller representation exactly, including whitespace,
            # Unicode escaping, array brackets and separators. Original bytes
            # and the independent8MiB per-record guard remain unchanged.
            needed=len(json.dumps(payload).encode())+(2 if output else 0)
            if size+needed>16*1024**2:deferred+=1;continue
            size+=needed;output.append(payload)
    return output,{'rows_scanned':scanned,'retained_studies':len(output),'retained_bytes':size,'source_guard_bytes':16*1024**2,'deferred_for_serialized_budget':deferred}
