"""Bounded live profile comparison; does not activate or modify any service.

python -m neraium_poly.research.phase41.experiment NEW_DIRECTORY --seconds180
Resume the same portfolios with --resume; source forecasts and positions persist.
"""
import argparse
import asyncio
import json
import os
import shutil
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx

from neraium_poly.data import EventStore
from neraium_poly.experimental.fees import AuditedFeeAdapter
from neraium_poly.research.phase25.dependencies import bound_forecasts
from neraium_poly.research.phase29.costs import ResearchFeeCache
from neraium_poly.research.phase40.campaign import FEED, adapters, replay_model
from neraium_poly.research.phase40.campaign import run as acquire
from neraium_poly.research.phase41.simulation import ProfileExperiment


async def run(output,*,seconds=180,source_seconds=120,resume=False):
    if not 10<=seconds<=900 or not 30<=source_seconds<=180:raise ValueError('bounded source/observation duration required')
    if os.getenv('LIVE_TRADING_ENABLED','false').lower()!='false' or os.getenv('PAPER_TRADING','true').lower()!='true':raise ValueError('paper-only environment required')
    output=Path(output).resolve()
    if resume:
        if not (output/'profiles.sqlite').is_file():raise ValueError('existing profile experiment required')
    else:output.mkdir(parents=True,exist_ok=False)
    def can_write():
        return shutil.disk_usage(output).free>100*1024**3+16*1024**2 and sum(p.stat().st_size for p in output.rglob('*') if p.is_file())<112*1024**2
    if not can_write():raise ValueError('profile evidence capacity unavailable')
    clock=lambda:datetime.now(UTC)
    risk=json.loads((Path(__file__).resolve().parents[4]/'config/experimental-paper.example.json').read_text())['risk_limits']
    store=EventStore(output/'profiles.sqlite');engine=ProfileExperiment(store,clock=clock,risk_limits=risk,can_write=can_write)
    source=output/'sources';model_modules=adapters();source_report=None
    try:
        if not resume:
            async with asyncio.timeout(source_seconds+30):source_report=await acquire(source,seconds=source_seconds)
        else:
            if not (source/'campaign.sqlite').is_file():raise ValueError('source evidence missing; no portfolio reset')
            async with asyncio.timeout(source_seconds+30):source_report=await acquire(source,seconds=source_seconds,resume=True)
        original_store=EventStore(source/'campaign.sqlite')
        try:
            studies=original_store.latest('DomainResearchStudy',100)+original_store.latest('ChallengerStudy',100)
            bound,invalid=bound_forecasts(studies,as_of=clock())
            def verify(f):replay_model(bound[f['id']]['study'],f,model_modules,now=clock())
            engine.enroll([v['forecast'] for v in bound.values()],verifier=verify)
            fees=AuditedFeeAdapter(original_store,can_write,clock=clock)
            cache=ResearchFeeCache(original_store,fees,clock=clock,can_write=can_write)
            # Reuse authenticated, recent source fee observations from acquisition.
            from neraium_poly.research.phase29.costs import replay_fee
            for observation in original_store.latest('FeeObservation',100):
                token=observation['token_id'];quote={'evidence_id':observation['id'],'observed_at':observation['available_at']}
                if token not in cache.observations and replay_fee(quote,original_store,token_id=token,as_of=clock()).get('status')=='verified_current_protocol_curve':
                    cache.observations[token]=quote
            started=time.monotonic();cycles=0;feed_errors=[]
            try:
                async with httpx.AsyncClient(timeout=5,trust_env=False) as client:
                    while time.monotonic()-started<seconds:
                        began=time.monotonic()
                        try:
                            from neraium_poly.experimental.contracts import SharedMarketFrame
                            response=await client.get(FEED);response.raise_for_status();frame=SharedMarketFrame.model_validate(response.json())
                            await cache.refresh(frame,forecast_tokens=[f['token_id'] for f in engine.state['cohort'].values()])
                            engine.step(frame,cache.proofs(as_of=clock()));cycles+=1
                        except (ValueError,OSError,httpx.HTTPError) as error:
                            feed_errors.append({'at':clock().isoformat(),'reason':f'{type(error).__name__}:{str(error)[:160]}'})
                            if len(feed_errors)>=10:break
                        await asyncio.sleep(max(0.,2-(time.monotonic()-began)))
            finally:await fees.close()
            outcome_error=None
            try:
                async with asyncio.timeout(35):await acquire(source,seconds=30,resume=True,settle_only=True)
            except (ValueError,OSError,TimeoutError) as error:outcome_error=f'{type(error).__name__}:{str(error)[:160]}'
            # The strict native verifier is the only settlement authority. Official
            # game results alone cannot settle a native-token shadow position.
            native_rows=original_store.latest('ChallengerOutcomeStudy',256)
            def native(f,now):
                if f['id'] in generic_native:return generic_native[f['id']]
                row=next((r for r in native_rows if r.get('forecast_id')==f['id'] and r.get('outcome')),None)
                if row is None:return None
                from neraium_poly.research.phase23.outcomes import verify_outcome
                proof=verify_outcome(row,bound[f['id']]['study'],f,evidence_root=source/'crypto-outcomes',as_of=now)
                return {**proof,'native_payout_verified':True}
            from neraium_poly.research.phase41.native import collect
            generic_native={}
            try:
                async with asyncio.timeout(35):generic_native=await collect(bound,original_store,source/'native-payouts',clock=clock,can_write=can_write)
            except (ValueError,OSError,httpx.HTTPError,TimeoutError) as error:
                outcome_error=f'{type(error).__name__}:{str(error)[:160]}'
            engine.settle(native)
            report={**engine.report(),'as_of':clock().isoformat(),'cycles':cycles,'elapsed_observation_seconds':time.monotonic()-started,
                'source_phase':{k:source_report[k] for k in ('markets_evaluated','supported_tokens','prospective_forecasts','forecast_parent_events')} if source_report else {'scope':'resumed original forecasts; no historical reconstruction'},
                'invalid_source_forecasts':dict(invalid),'feed_errors':feed_errors,
                'outcome_verification_error':outcome_error,
                'limits':risk,'policy':engine.policy,
                'interpretation':'modeled entry EV and marked hypothetical P/L are unvalidated estimates; native-settled simulated P/L is separate',
                'live_services_changed':False,'emergency_stop_cleared':False,'live_orders_possible':False}
            report_path=output/f'report-{int(time.time())}.json';report_path.write_text(json.dumps(report,indent=2)+'\n')
            lines=['# Prospective shadow profile comparison','Alternative $500 research scenarios, NOT additive capital or real accounts.','',
                '| Profile | Orders | Fill events | Positions | Settled P/L | Marked P/L | Max drawdown |',
                '|---|---:|---:|---:|---:|---:|---:|']
            for name,s in report['profiles'].items():lines.append(f"| {name} | {s['orders']} | {s['fill_events']} | {s['open_positions']} | {s['realized_simulated_pnl']} | {s['unrealized_simulated_pnl']} | {s['maximum_drawdown']} |")
            lines+=['','No proven profitability or promotion from open marks. Same source cohort and chronological book observations for all profiles. Uncertainty and conditional reference assumptions are retained in order evidence.']
            report_path.with_suffix('.md').write_text('\n'.join(lines)+'\n');return report
        finally:original_store.close()
    finally:store.close()


async def repeat(output,*,cycles=1,seconds=180,source_seconds=120,resume=False):
    if not 1<=cycles<=12:raise ValueError('1–12bounded research cycles required')
    result=None
    for index in range(cycles):result=await run(output,seconds=seconds,source_seconds=source_seconds,resume=resume or index>0)
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('output',type=Path);p.add_argument('--seconds',type=int,default=180)
    p.add_argument('--source-seconds',type=int,default=120);p.add_argument('--resume',action='store_true');p.add_argument('--cycles',type=int,default=1);a=p.parse_args()
    result=asyncio.run(repeat(a.output,seconds=a.seconds,source_seconds=a.source_seconds,resume=a.resume,cycles=a.cycles))
    print(json.dumps({k:result[k] for k in ('profiles','cohort_forecasts','parent_events','cycles','feed_errors')}))


if __name__=='__main__':main()
