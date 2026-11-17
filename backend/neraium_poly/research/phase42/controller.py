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
from neraium_poly.research.phase41.simulation import ProfileExperiment
from neraium_poly.research.phase44.cohort import LegacyCohort
from neraium_poly.research.phase44.outcomes import collect
from neraium_poly.research.phase45.cohort import Explorer
from neraium_poly.research.phase45.diagnostics import breakdown
from neraium_poly.research.phase45.panel import Panel
from neraium_poly.research.phase45.replay_cache import ReplayCache
from neraium_poly.research.phase45.retire import ClosedPhase44
from neraium_poly.research.phase46.program import Program, inventory


class ShadowSourceBinding(Record):
    forecast_id:str
    forecast_sha256:str
    study_id:str
    study_sha256:str


class Controller:
    def __init__(self,store,*,risk_limits,clock,can_write,directory):
        self.store,self.clock,self.can_write=store,clock,can_write
        self.engine=LegacyCohort(store,risk_limits=risk_limits,clock=clock,can_write=can_write)
        self.challenger=ClosedPhase44(store,risk_limits=risk_limits,clock=clock,can_write=can_write)
        self.challenger.close_enrollment()
        self.explorer=Explorer(store,risk_limits=risk_limits,clock=clock,can_write=can_write)
        self.profiles=ProfileExperiment(store,risk_limits=risk_limits,clock=clock,can_write=can_write)
        self.models=adapters();self.directory=Path(directory);self.next_sources=None;self.next_outcomes=None;self.errors=Counter()
        self.bindings={r['forecast_id']:r for r in store.latest('ShadowSourceBinding',512)}
        self.program=Program(store,clock,can_write)
        self.verified_refs={}
        self.replay_cache=ReplayCache()
        self.panel=Panel(store,clock,can_write)
        self.report=None;self.current_forecasts={}
    def tick(self,frame,fees,*,proofs=None,frame_provider=None):
        now=at(self.clock())
        if self.next_sources is None or now>=self.next_sources:
            from neraium_poly.research.phase42.sources import forecast_studies
            studies,self.inventory=forecast_studies(self.store)
            if len(__import__('json').dumps(studies).encode())>16*1024**2:raise ValueError('bounded source snapshot exceeds16MiB; no guard increase')
            bound,invalid=bound_forecasts(studies,as_of=now);self.errors.update(invalid)
            verified={};study_hashes={}
            for fid,item in bound.items():
                try:
                    identity=id(item['study'])
                    if identity not in study_hashes:study_hashes[identity]=digest(item['study'])
                    self.replay_cache.verify(item,self.models,now=now,replay=replay_model,study_sha256=study_hashes[identity]);verified[fid]=item
                except (ValueError,KeyError,TypeError,OSError) as error:self.errors['source_replay:'+type(error).__name__]+=1
            cohort_keys={(f['model_id'],f['event_id'],f['market_id'],f['token_id']) for f in self.engine.state['forecasts'].values()}
            cohort={}
            for fid,item in sorted(verified.items(),key=lambda v:v[1]['forecast']['timestamp']):
                f=item['forecast'];key=(f['model_id'],f['event_id'],f['market_id'],f['token_id'])
                if key not in cohort_keys and at(f['event_end_time'])>now:cohort[fid]=item;cohort_keys.add(key)
            self.current_forecasts={fid:v['forecast'] for fid,v in verified.items()}
            self.verified_refs={fid:{'study_id':v['study']['id'],'study_sha256':study_hashes[id(v['study'])],'forecast_sha256':digest(v['forecast'])} for fid,v in verified.items()}
            for fid,item in verified.items():
                if fid not in cohort and fid not in self.engine.state['forecasts']:continue
                if fid in self.bindings:continue
                binding=ShadowSourceBinding(id=digest(['source-binding42',fid]),timestamp=now,available_at=now,source='neraium-poly/replayed-source/v42',
                    forecast_id=fid,forecast_sha256=digest(item['forecast']),study_id=item['study']['id'],study_sha256=digest(item['study']))
                if not self.can_write():raise ValueError('source binding capacity withheld')
                self.store.append(binding);self.bindings[fid]=binding.model_dump(mode='json')
            if len(self.bindings)>512:raise ValueError('bounded settlement inventory exhausted')
            def checked(f):
                if f['id'] not in verified or digest(verified[f['id']]['forecast'])!=digest(f):raise ValueError('exact replayed original forecast required')
            self.engine.enroll([v['forecast'] for v in cohort.values()],verifier=checked)
            def existing_original(f):
                binding=self.bindings.get(f['id'])
                if binding is None or binding['forecast_sha256']!=digest(f):raise ValueError('new cohort requires existing immutable source binding')
            self.explorer.enroll(list(self.engine.state['forecasts'].values()),verifier=existing_original)
            declared=at(__import__('json').loads(self.store.get(self.profiles.identity)[1])['available_at'])
            self.profiles.enroll([v['forecast'] for v in cohort.values() if at(v['forecast']['timestamp'])>=declared and at(v['forecast']['event_end_time'])>now],verifier=checked)
            self.next_sources=now+timedelta(seconds=60)
        if frame_provider is not None:frame=frame_provider()
        self.admitted_frame_available_at=frame.available_at.isoformat()
        self.engine.step(frame,fees,source_forecasts=self.current_forecasts);self.profiles.step(frame,fees)
        if self.challenger.needs_quotes():self.challenger.step(frame,fees,source_forecasts=self.current_forecasts)
        exploratory_frame=frame_provider() if frame_provider is not None else frame
        self.explorer.step(exploratory_frame,fees,source_forecasts=self.current_forecasts)
        self.panel.register(self.current_forecasts,exploratory_frame)
        self.program.register(self.current_forecasts,self.verified_refs,exploratory_frame,self.engine.state['forecasts'],self.engine.state['labels'])
        if self.next_outcomes is None or now>=self.next_outcomes:
            # Resolve only a bounded matured inventory. Original study IDs survive restart.
            attempts={}
            for row in self.store.latest('ProfilePayoutStudy',256):attempts.setdefault(row['forecast_id'],row['available_at'])
            due=sorted((fid for fid,f in self.engine.state['forecasts'].items() if at(f['event_end_time'])<=now and fid not in self.engine.state['labels']),
                key=lambda fid:(attempts.get(fid,''),fid))
            native_bound={};verified_studies=set()
            for fid in due:
                binding=self.bindings.get(fid)
                if not binding:continue
                if binding['study_id'] not in verified_studies:
                    original=self.store.get(binding['study_id'])
                    if not original:raise ValueError('original settlement study missing')
                    if len(original[1].encode())>16*1024**2:raise ValueError('native source study budget withheld')
                    if digest(__import__('json').loads(original[1]))!=binding['study_sha256']:raise ValueError('settlement original study hash mismatch')
                    verified_studies.add(binding['study_id'])
                f=self.engine.state['forecasts'][fid]
                if digest(f)!=binding['forecast_sha256']:raise ValueError('settlement original forecast hash mismatch')
                native_bound[fid]={'study_sha256':binding['study_sha256'],'study_id':binding['study_id'],'forecast':f}
            from neraium_poly.research.phase45.native_positions import due
            native_bound.update(due(self.explorer,now))
            native_bound.update(self.program.due())
            self.native_bound=native_bound
            self.next_outcomes=now+timedelta(seconds=300)
        if proofs:
            self.engine.settle(proofs);self.challenger.settle(proofs);self.explorer.settle(proofs);self.profiles.settle(lambda f,t:proofs.get(f['id']))
        if proofs:self.program.settle(proofs)
        self.report={**self.engine.report(),'outcome_program':self.program.report(),'native_outcome_inventory':inventory(self.engine.state['forecasts'],self.engine.state['labels']),'phase44_cohort':self.challenger.report(),'phase45_explorer':self.explorer.report(),'exploratory_frame_available_at':exploratory_frame.available_at.isoformat(),'source_replay_cache':self.replay_cache.status(),'probability_panel':self.panel.report(self.engine.state['labels']),'phase41_profiles':self.profiles.report(),'source_withholding':dict(self.errors),
            'execution':'isolated shadow only; no account/order-admission access','current_source_forecasts':len(self.current_forecasts),'calibration_cohort':'first available forecast per native market/token/model; repeated refreshes are not independent events','source_inventory':getattr(self,'inventory',{}),'native_verification_timeout_seconds':45,'native_proof_requests_per_5min':2}
        self.report['held_fee_tokens']=sorted({p['token_id'] for engine in (self.engine,self.challenger,self.explorer) for state in engine.state['profiles'].values() for p in [*state['orders'].values(),*state['positions'].values()]})
        self.report['current_fee_coverage']={'verified_tokens':sum(p.get('status')=='verified_current_protocol_curve' for p in fees.values()),'open_positions':[{ 'profile':name,'strategy':p['strategy'],'token_id':p['token_id'],'outcome':p['market']['outcome'],'entry_fee_verified':p['fee_verified'],'current_curve':fees.get(p['token_id'],{}),'limitation':'current evidence cannot authenticate or rewrite earlier entry fees'} for name,state in self.explorer.state['profiles'].items() for p in state['positions'].values()]}
        from neraium_poly.research.phase42.desk import publish
        self.report['phase44_rejection_breakdown']={n:breakdown(p['rejections']) for n,p in self.report['phase44_cohort']['profiles'].items()}
        explorer_view=publish(self.store,self.explorer,self.report['phase45_explorer'],now,cohort='phase45')
        challenger_view=publish(self.store,self.challenger,self.report['phase44_cohort'],now,cohort='phase44')
        self.report=publish(self.store,self.engine,self.report,now)
        self.report['positions']+=challenger_view['positions']+explorer_view['positions'];self.report['unfilled_orders']+=challenger_view['unfilled_orders']+explorer_view['unfilled_orders']
        return self.report


async def service_loop(runtime,should_exit):
    """Opt-in, serial bounded scheduling inside the existing experimental cgroup."""
    import os
    if os.environ.get('NERAIUM_SHADOW_RESEARCH')!='true':return
    from concurrent.futures import ThreadPoolExecutor

    from neraium_poly.experimental.research_worker import _drain
    from neraium_poly.research.phase44.reference import ReferenceSampler, merge_supplemental
    # Long external-model jobs already occupy the shared research worker. One
    # independent shadow-only lane prevents starvation; store append locks still
    # serialize immutable writes. Existing cgroup/thread/CPU/memory caps remain.
    executor=ThreadPoolExecutor(max_workers=1,thread_name_prefix='shadow-only')
    from threading import Event
    source_executor=ThreadPoolExecutor(max_workers=1,thread_name_prefix='shadow-sources')
    source_stop=Event();source_future=None;source_due=0.
    native_executor=ThreadPoolExecutor(max_workers=1,thread_name_prefix='native-reconcile')
    native_future=None;native_due=0.;native_proofs={};native_status={'status':'initializing'}
    controller=None
    sampler=ReferenceSampler(runtime.config.source_url,clock=runtime.clock)
    runtime.research_reference=sampler
    sampler_task=asyncio.create_task(sampler.run(lambda:runtime.stopping or should_exit()))
    try:
        while not runtime.stopping and not should_exit():
            import time
            if source_future is not None and source_future.done():
                try:runtime.shadow_source_status=source_future.result()
                except Exception as error:runtime.shadow_source_status={'status':'withheld','error':str(error)[:180]}  # noqa: BLE001
                source_future=None;source_due=time.monotonic()+300
            if native_future is not None and native_future.done():
                try:
                    verified,reasons,capacity=native_future.result();native_proofs.update(verified);native_status={'status':'completed','proofs':len(native_proofs),'recent_attempt_reasons':reasons,'capacity':capacity}
                except Exception as error:native_status={'status':'withheld','reason':type(error).__name__+':'+str(error)[:180]}  # noqa: BLE001
                native_future=None;native_due=time.monotonic()+300
            try:
                frame=sampler.latest()
                inputs=getattr(runtime,'phase26_inputs',None)
                extra_markets=();extra_books=()
                if inputs is not None:
                    # Snapshot transport-owned caches only on their owner loop.
                    extra_markets=tuple(inputs.watcher._markets.values());extra_books=tuple(inputs.watcher.snapshot())
                    frame=merge_supplemental(frame,extra_markets,extra_books,runtime.clock())
                if frame is not None:
                    def work(frame=frame,native_status=native_status,extra_markets=extra_markets,extra_books=extra_books):
                        nonlocal controller
                        import time
                        began=time.monotonic();origin='combined_experimental_frame'
                        if not runtime._budget_ok():raise ValueError('archive budget admission withheld')
                        origin='shared_bounded_reference_reader'
                        if not 0<=(runtime.clock()-frame.available_at).total_seconds()<=15:raise ValueError('research frame expired before worker admission')
                        if controller is None:controller=Controller(runtime.events,risk_limits=runtime.config.risk_limits.model_dump(),clock=runtime.clock,can_write=runtime._budget_ok,directory=runtime.config.data_dir/'phase42-native')
                        cache=getattr(runtime,'research_fees',None)
                        fees=cache.proofs(as_of=runtime.clock()) if cache else {}
                        def current_frame():
                            base=sampler.latest()
                            return merge_supplemental(base,extra_markets,extra_books,runtime.clock()) if extra_markets else base
                        report=controller.tick(frame,fees,proofs=native_proofs,frame_provider=current_frame)
                        return {**report,'native_reconciliation':native_status,'reference_feed':sampler.status(),'input_frame_available_at':getattr(controller,'admitted_frame_available_at',frame.available_at.isoformat()),'shadow_worker':{'maximum_workers':1,'queued_jobs':0,'cycle_seconds':time.monotonic()-began,'frame_origin':origin}}
                    if os.environ.get('NERAIUM_SHADOW_SOURCE_REFRESH','true')=='true' and source_future is None and time.monotonic()>=source_due:
                        def acquire_source():
                            from neraium_poly.research.phase42.sources import refresh
                            observed=sampler.latest()
                            return asyncio.run(refresh(runtime.events,observed,clock=runtime.clock,can_write=runtime._budget_ok,stop=source_stop,
                                frame_provider=lambda:asyncio.to_thread(sampler.latest)))
                        source_future=asyncio.get_running_loop().run_in_executor(source_executor,acquire_source)
                        runtime.shadow_source_status={'status':'acquiring','maximum_source_jobs':1,'maximum_http_workers':2,'deadline_seconds':90}
                    worker=asyncio.get_running_loop().run_in_executor(executor,work)
                    report=await _drain(worker)
                    if native_future is None and time.monotonic()>=native_due and getattr(controller,'native_bound',None):
                        pending=dict(controller.native_bound)
                        def reconcile(pending=pending):
                            async def work_native():
                                async with asyncio.timeout(45):return await collect(pending,runtime.events,runtime.config.data_dir/'phase42-native',clock=runtime.clock,can_write=runtime._budget_ok,max_requests=2)
                            verified=asyncio.run(work_native())
                            reasons=dict(Counter(row['reason'] for row in runtime.events.latest('NativePayout44',16)))
                            cycles=runtime.events.latest('NativeCycle46',1)
                            return verified,reasons,cycles[0] if cycles else None
                        native_future=asyncio.get_running_loop().run_in_executor(native_executor,reconcile);native_status={'status':'acquiring','maximum_workers':1,'queued_jobs':0}
                    runtime.research_fee_targets=frozenset(report.get('held_fee_tokens',()))
                    runtime.shadow_research_snapshot={**report,'source_refresh':getattr(runtime,'shadow_source_status',{})}
                    runtime.shadow_research_error=None
            except Exception as error:  # noqa: BLE001 - withhold shadow only; never financial authority
                runtime.shadow_research_error=f'{type(error).__name__}:{str(error)[:180]}'
            for _ in range(5):
                if runtime.stopping or should_exit():return
                await asyncio.sleep(1)
    finally:
        # _drain above ensures an active SQLite write finishes before shutdown.
        sampler.stop()
        await _drain(sampler_task)
        source_stop.set()
        if source_future is not None:
            try:await _drain(source_future)
            except asyncio.CancelledError:runtime.shadow_source_status={'status':'cancelled_and_drained'}
            except Exception as error:runtime.shadow_source_status={'status':'withheld_on_close','error':str(error)[:180]}  # noqa: BLE001
        if native_future is not None:
            try:await _drain(native_future)
            except asyncio.CancelledError:pass
            except Exception as error:runtime.shadow_native_error=type(error).__name__+':'+str(error)[:180]  # noqa: BLE001 - preserve failure diagnostics
        native_executor.shutdown(wait=True,cancel_futures=True)
        source_executor.shutdown(wait=True,cancel_futures=True)
        executor.shutdown(wait=True,cancel_futures=True)
