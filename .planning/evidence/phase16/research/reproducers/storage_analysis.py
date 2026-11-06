import concurrent.futures,datetime,hashlib,json,multiprocessing,os,pathlib,resource,time
ROOT=pathlib.Path('/home/ubuntu/Neraium-Poly');OUT=ROOT/'data/phase16'
def stamp():return datetime.datetime.now(datetime.timezone.utc).isoformat()
def job(kind,start):
 time.sleep(max(0,start-time.time()));at=stamp();cpu=time.process_time()
 if kind=='frozen_dataset':
  p=OUT/'prepared/frames.jsonl';m=json.loads((p.parent/'manifest.json').read_text());assert hashlib.sha256(p.read_bytes()).hexdigest()==m['sha256'];frames=[json.loads(v) for v in p.read_text().splitlines()];tokens=set();parents=set();books=set();future=0;old=0
  for row in frames:
   atrow=datetime.datetime.fromisoformat(row['observed_at']);market={r['token_id']:r for r in row['frame']['markets']}
   for b in row['frame']['books']:
    t=datetime.datetime.fromisoformat(b['timestamp']);a=datetime.datetime.fromisoformat(b['available_at']);future+=int(not t<=a<=atrow);old+=int((atrow-t).total_seconds()>15);tokens.add(b['token_id']);parents.add(market[b['token_id']]['event_id']);books.add(b['id'])
  value={'dataset_sha256':m['sha256'],'frames':len(frames),'tokens':len(tokens),'parent_groups':len(parents),'unique_quote_ids':len(books),'source_observations_future_at_cutoff':future,'source_observations_older_than15s':old,'known_missing_context':['producer_health','original_frame_id'],'independent_certification_events':0}
 else:
  first=json.loads((ROOT/'.planning/evidence/phase15/soak.json').read_text())['first'];now={label:json.loads((OUT/(label+'-baseline.json')).read_text()) for label in ['collector','experimental']};value={}
  for label in now:
   a,b=first[label],now[label];seconds=(datetime.datetime.fromisoformat(b['generated_at'])-datetime.datetime.fromisoformat(a['generated_at'])).total_seconds();old,new=a['archive'],b['archive'];delta=new['usage_bytes']-old['usage_bytes'];rate=delta/seconds;remaining=new['budget_bytes']-new['usage_bytes'];components={k:(new.get('tier_usage_bytes',{}).get(k,0)-old.get('tier_usage_bytes',{}).get(k,0))/seconds for k in new.get('tier_usage_bytes',{})}
   value[label]={'started_at':a['generated_at'],'ended_at':b['generated_at'],'seconds':seconds,'retained_growth_bytes_per_second':rate,'component_growth_bytes_per_second':components,'usage_bytes':new['usage_bytes'],'budget_bytes':new['budget_bytes'],'conditional_days_to_budget':remaining/rate/86400 if rate>0 else None,'conditional90d_usage_bytes':new['usage_bytes']+max(0,rate)*90*86400,'free_bytes':new['free_bytes'],'reserve_bytes':new['global_floor_bytes'],'includes_cache_and_operator_backup_changes':True,'representative24h_available':seconds>=86400,'retention_changed':False,'budget_change_authority':False,'removal_authority':False,'proposal':'Keep64/16GiB; protectalloriginals;measure24h/7d; completedraw retirement requiresseparateexactbatchapproval. Gzipalonecannotboundlinearall-historycatalog.'}
 value['worker']={'pid':os.getpid(),'started_at':at,'completed_at':stamp(),'cpu_seconds':time.process_time()-cpu,'max_rss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,'kind':kind};return value
if __name__=='__main__':
 start=time.time()+1
 with concurrent.futures.ProcessPoolExecutor(max_workers=2,mp_context=multiprocessing.get_context('spawn')) as p:
  a=p.submit(job,'frozen_dataset',start);b=p.submit(job,'storage_growth',start);r={'frozen_dataset':a.result(),'storage_growth':b.result()}
 r['concurrency']={'workers':2,'actual_overlap':max(r[k]['worker']['started_at'] for k in ['frozen_dataset','storage_growth'])<min(r[k]['worker']['completed_at'] for k in ['frozen_dataset','storage_growth']),'scope':'two genuine bounded process jobs, not saturatedCPUs'};(OUT/'parallel-analysis.json').write_text(json.dumps(r,indent=2)+'\n');print(json.dumps(r,indent=2))
