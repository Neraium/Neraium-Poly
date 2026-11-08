import asyncio,datetime,json,pathlib,time,subprocess,sqlite3,collections
import httpx
async def main():
 async with httpx.AsyncClient(timeout=15) as c:
  samples=[];v=None
  for _ in range(3):
   t=time.monotonic();r=await c.get('http://127.0.0.1:18743/api/operations-state');r.raise_for_status();v=r.json();samples.append(time.monotonic()-t)
  for port in [18742,18743]:
   h=(await c.get(f'http://127.0.0.1:{port}/api/health')).json();assert h['paper_trading'] and not h['live_trading_enabled']
 score=v['official_event_research'];assert score.get('event_groups_by_domain',{}).get('weather')==3,score.get('collection_rejections');assert score['verified_forecast_labels']>=10
 pairs=v['cross_market_research'];assert pairs['status']=='conditional_research_only' and not pairs['trading_authority']
 assert all(v['archive'][k]==n for k,n in [('budget_bytes',150*1024**3),('global_floor_bytes',100*1024**3)])
 assert v['archive']['health']=='ok' and v['archive']['free_bytes']>=100*1024**3
 r=v['operations_research']['phase28'];models=score.get('models',[])
 conn=sqlite3.connect('file:data/experimental-paper/research-projection.sqlite?mode=ro',uri=True);entries=[json.loads(x[0]) for x in conn.execute('SELECT payload FROM entries')];conn.close();entries=[e for e in entries if e.get('type')=='forecast'];counts=collections.Counter(e['forecast']['domain'] for e in entries)
 out={'observed_at':datetime.datetime.now(datetime.UTC).isoformat(),'latency_seconds':samples,'forecasts_by_domain':dict(counts),'official_event_research':score,'pairs':pairs,
 'economics':{k:r.get(k) for k in ['as_of','counts','pipeline_counts','rejections','runtime_error','report_callback_error','shadow']},
 'domain_scorecard':v['domain_scorecard'],'archive':v['archive'],'cash':v['cash'],'simulated_pnl':v['simulated_pnl'],'orders_submitted':v['orders_submitted'],'fills':v['fills'],'open_positions':v['open_positions'],'kill_switch':v['kill_switch'],
 'memory':v.get('memory'),'services':subprocess.check_output(['systemctl','show','neraium-poly-paper','neraium-poly-experimental','-p','MainPID','-p','ActiveState','-p','NRestarts','-p','MemoryMax','-p','CPUQuotaPerSecUSec'],text=True),
 'experimental_memory_events':pathlib.Path('/sys/fs/cgroup/system.slice/neraium-poly-experimental.service/memory.events').read_text()}
 pathlib.Path('.planning/evidence/phase32/final.json').write_text(json.dumps(out,indent=2)+'\n')
 print(json.dumps({'counts':dict(counts),'verified_labels':score['verified_forecast_labels'],'official_events':score['event_groups_by_domain'],'pairs_evaluated':pairs['paired_books_evaluated'],'pair_gross_positive':pairs['positive_conditional_gross_pairs'],'latency':samples,'scorer_rejections':score['collection_rejections']}))
 subprocess.run(['uv','run','python','data/phase32/accounts.py','after'],check=True,stdout=subprocess.DEVNULL)
asyncio.run(main())
