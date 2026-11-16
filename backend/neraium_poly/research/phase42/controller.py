"""One bounded worker owns research state; no broker/account objects accepted."""
import asyncio
from collections import Counter
from datetime import timedelta
from pathlib import Path

from neraium_poly.contracts import Record
from neraium_poly.research.phase14.relationships import digest
from neraium_poly.research.phase24.continuous import at
from neraium_poly.research.phase25.dependencies import bound_forecasts
from neraium_poly.research.phase40.campaign import adapters, replay_model
from neraium_poly.research.phase41.native import collect
from neraium_poly.research.phase41.simulation import ProfileExperiment
from neraium_poly.research.phase42.engine import StrategyEngine


class ShadowSourceBinding(Record):
    forecast_id:str
    forecast_sha256:str
    study_id:str
    study_sha256:str


class Controller:
    def __init__(self,store,*,risk_limits,clock,can_write,directory):
        self.store,self.clock,self.can_write=store,clock,can_write
        self.engine=StrategyEngine(store,risk_limits=risk_limits,clock=clock,can_write=can_write)
        self.profiles=ProfileExperiment(store,risk_limits=risk_limits,clock=clock,can_write=can_write)
        self.models=adapters();self.directory=Path(directory);self.next_sources=None;self.next_outcomes=None;self.errors=Counter()
        self.bindings={r['forecast_id']:r for r in store.latest('ShadowSourceBinding',512)}
        self.report=None
    def tick(self,frame,fees):
        now=at(self.clock())
        if self.next_sources is None or now>=self.next_sources:
            studies=self.store.latest('DomainResearchStudy',2)+self.store.latest('ChallengerStudy',2)
            if len(__import__('json').dumps(studies).encode())>16*1024**2:raise ValueError('bounded source snapshot exceeds16MiB; no guard increase')
            bound,invalid=bound_forecasts(studies,as_of=now);self.errors.update(invalid)
            verified={}
            for fid,item in bound.items():
                try:
                    replay_model(item['study'],item['forecast'],self.models,now=now);verified[fid]=item
                except (ValueError,KeyError,TypeError,OSError) as error:self.errors['source_replay:'+type(error).__name__]+=1
            for fid,item in verified.items():
                if fid in self.bindings:continue
                binding=ShadowSourceBinding(id=digest(['source-binding42',fid]),timestamp=now,available_at=now,source='neraium-poly/replayed-source/v42',
                    forecast_id=fid,forecast_sha256=digest(item['forecast']),study_id=item['study']['id'],study_sha256=digest(item['study']))
                if not self.can_write():raise ValueError('source binding capacity withheld')
                self.store.append(binding);self.bindings[fid]=binding.model_dump(mode='json')
            if len(self.bindings)>512:raise ValueError('bounded settlement inventory exhausted')
            def checked(f):
                if f['id'] not in verified or digest(verified[f['id']]['forecast'])!=digest(f):raise ValueError('exact replayed original forecast required')
            self.engine.enroll([v['forecast'] for v in verified.values()],verifier=checked)
            declared=at(__import__('json').loads(self.store.get(self.profiles.identity)[1])['available_at'])
            self.profiles.enroll([v['forecast'] for v in verified.values() if at(v['forecast']['timestamp'])>=declared and at(v['forecast']['event_end_time'])>now],verifier=checked)
            self.next_sources=now+timedelta(seconds=60)
        self.engine.step(frame,fees);self.profiles.step(frame,fees)
        if self.next_outcomes is None or now>=self.next_outcomes:
            # Resolve only a bounded matured inventory. Original study IDs survive restart.
            attempts={}
            for row in self.store.latest('ProfilePayoutStudy',256):attempts.setdefault(row['forecast_id'],row['available_at'])
            due=sorted((fid for fid,f in self.engine.state['forecasts'].items() if at(f['event_end_time'])<=now and fid not in self.engine.state['labels']),
                key=lambda fid:(attempts.get(fid,''),fid))[:2]
            native_bound={}
            for fid in due:
                binding=self.bindings.get(fid)
                if not binding:continue
                original=self.store.get(binding['study_id'])
                if not original:raise ValueError('original settlement study missing')
                if len(original[1].encode())>16*1024**2:raise ValueError('native source study budget withheld')
                study=__import__('json').loads(original[1]);f=self.engine.state['forecasts'][fid]
                if digest(study)!=binding['study_sha256'] or digest(f)!=binding['forecast_sha256']:raise ValueError('settlement original identity/hash mismatch')
                native_bound[fid]={'study':study,'forecast':f}
            async def outcomes():
                async with asyncio.timeout(20):return await collect(native_bound,self.store,self.directory,clock=self.clock,can_write=lambda:self.can_write() and sum(p.stat().st_size for p in self.directory.rglob('*') if p.is_file())<64*1024**2,max_requests=2)
            try:
                proofs=asyncio.run(outcomes());self.engine.settle(proofs);self.profiles.settle(lambda f,t:proofs.get(f['id']))
            except (ValueError,KeyError,OSError,TimeoutError) as error:self.errors['native_payout:'+type(error).__name__]+=1
            self.next_outcomes=now+timedelta(seconds=300)
        self.report={**self.engine.report(),'phase41_profiles':self.profiles.report(),'source_withholding':dict(self.errors),
            'execution':'isolated shadow only; no account/order-admission access','maximum_cycle_seconds':30,'native_proof_requests_per_5min':2}
        from neraium_poly.research.phase42.desk import publish
        self.report=publish(self.store,self.engine,self.report,now)
        return self.report


async def service_loop(runtime,should_exit):
    """Opt-in, serial bounded scheduling inside the existing experimental cgroup."""
    import os
    if os.environ.get('NERAIUM_SHADOW_RESEARCH')!='true':return
    controller=None
    while not runtime.stopping and not should_exit():
        try:
            if not await runtime._async_budget_ok():raise ValueError('archive budget admission withheld')
            frame=runtime.last_frame
            if frame is not None:
                def work(frame=frame):
                    nonlocal controller
                    if controller is None:controller=Controller(runtime.events,risk_limits=runtime.config.risk_limits.model_dump(),clock=runtime.clock,can_write=runtime._budget_ok,directory=runtime.config.data_dir/'phase42-native')
                    cache=getattr(runtime,'research_fees',None)
                    fees=cache.proofs(as_of=runtime.clock()) if cache else {}
                    return controller.tick(frame,fees)
                async def isolated_work():
                    from neraium_poly.experimental.research_worker import _drain
                    return await _drain(asyncio.create_task(asyncio.to_thread(work)))
                report=await runtime._research_io(isolated_work)
                runtime.shadow_research_snapshot=report
                runtime.shadow_research_error=None
        except Exception as error:  # noqa: BLE001 - research failure withholds only shadow work; never authorizes accounts
            runtime.shadow_research_error=f'{type(error).__name__}:{str(error)[:180]}'
        for _ in range(5):
            if runtime.stopping or should_exit():return
            await asyncio.sleep(1)
