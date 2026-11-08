"""Official domain-event observations remain separate from native payouts."""
from datetime import timedelta
from pathlib import Path

from neraium_poly.research.phase14.relationships import digest
from neraium_poly.research.phase25.dependencies import at
from neraium_poly.research.phase30.scoring import OfficialEventScoring, _thread
from neraium_poly.research.phase31.scoring import evaluate_domains


async def verify_event(f,*,directory,clock):
    if f.get('domain')=='crypto':
        from .crypto_finance import qualify_reference
        reference=qualify_reference(f,as_of=clock())
        if not reference['forecast_reference_admissible']:
            return {**reference,'reason':'contract_reference_ambiguous_before_provider_access'}
    if f.get('domain')=='weather':
        from .weather import verify_weather_event
        return await verify_weather_event(f,directory=directory,clock=clock)
    if f.get('domain')=='economics':
        from .macro import verify_macro_event
        return await verify_macro_event(f,directory=directory,clock=clock)
    from neraium_poly.research.phase31.scoring import verify_event as legacy
    return await legacy(f,directory=directory,clock=clock)


def replay_event(result,study,f,*,evidence_root,as_of):
    if f.get('domain')=='weather':
        from .weather import replay_weather_event
        return replay_weather_event(result,study,f,evidence_root=evidence_root,as_of=as_of)
    if f.get('domain')=='economics':
        from .macro import replay_macro_event
        return replay_macro_event(result,study,f,evidence_root=evidence_root,as_of=as_of)
    from neraium_poly.research.phase31.scoring import replay_event as legacy
    return legacy(result,study,f,evidence_root=evidence_root,as_of=as_of)


class DomainEventScoring(OfficialEventScoring):
    def __init__(self,*args,**kwargs):
        root=Path(__file__).parent
        policy={'version':'phase32-official-domain-event-v1','implementation_sha256':digest([(root/n).read_text() for n in ['scoring.py','weather.py','macro.py','crypto_finance.py']]+[(root.parent/'phase31'/n).read_text() for n in ['scoring.py','crypto.py']]),
            'target_scope':'exact official reference-event only; no native payout/certification/trading authority',
            'finite_unattempted_backlog_catchup_seconds':10,'attempted_retry_seconds':300,'maximum_source_checks_per_cycle':16,
            'crypto_access':'existing license gate closed; reference ambiguity unresolved'}
        super().__init__(*args,verify=verify_event,replay=replay_event,policy_extension=policy,**kwargs)

    def supports(self,ref):
        f=ref['forecast']
        if f.get('domain') in ('crypto','weather','economics'):return True
        review=ref.get('review') or {}
        return f.get('domain')=='sports' and (review.get('descriptor') or {}).get('league')=='NHL'

    def evaluate_labels(self,labels):return evaluate_domains(labels)

    def _unattempted_matured(self):
        now=at(self.clock());entries,_anchor=self.index.snapshot();count=0
        for ref in entries:
            if ref.get('type')!='forecast' or not ref.get('replay_verified') or not self.supports(ref):continue
            f=ref['forecast'];end=at(f['event_end_time'])
            if end>now or f['id'] in self.attempts or f['domain']=='sports' and now<end+timedelta(hours=1):continue
            identity=digest(['official-event-label-v30',self.enrollment_id,f['id'],ref['forecast_sha256'],ref['source_study_sha256']])
            if self.store.get(identity) is None:count+=1
        return count

    async def step(self):
        changed=await super().step()
        if changed:
            self.catchup_pending=await _thread(self._unattempted_matured)
            if self.catchup_pending:self.next_check=at(self.clock())+timedelta(seconds=10)
        return changed

    def status(self):
        return {**super().status(),'collection_schedule':{'unattempted_matured_backlog':getattr(self,'catchup_pending',None),
            'next_check_at':self.next_check.isoformat() if self.next_check else None,
            'scope':'finite deferred source checks catch up in10s batches; attempted failures retain300s retry guard; maximum16checks/cycle'}}
