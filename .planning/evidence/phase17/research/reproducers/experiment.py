"""Preregistered authentic archive replay; no live orders and no future model fitting."""
import datetime,hashlib,json,pathlib,time,resource,os
from neraium_poly.research.phase14.relationships import digest
from neraium_poly.research.phase16.history import CausalHistory
from neraium_poly.research.phase17.models import causal_forecasts
from neraium_poly.research.phase17.economics import evaluate_roundtrip
from neraium_poly.research.phase17.statistics import evaluate_experiments
from neraium_poly.research.phase17.provenance import ReadonlyArchive
root=pathlib.Path('/home/ubuntu/Neraium-Poly');base=root/'data/phase17';out=base/'experiment';out.mkdir(exist_ok=True)
protocol=json.loads((base/'protocol.json').read_text());m=json.loads((base/'capture/manifest.json').read_text());assert m['completed'] and datetime.datetime.now(datetime.timezone.utc)>=datetime.datetime.fromisoformat(protocol['cutoff'])
assert hashlib.sha256((base/'protocol.json').read_bytes()).hexdigest()==m['protocol_sha256'];cpu=time.process_time();start=time.monotonic();archive=ReadonlyArchive(root/'data/experimental-paper');history=CausalHistory();points={};sources={};studies={};pairs={};verified={}
fee_proofs = {}
def verify_fee(point):
 raw=point['fee_observation'];key=digest(raw)
 if key in fee_proofs:return True
 item=archive.get(raw['evidence_id']);assert item and item[0]=='FeeObservation';f=json.loads(item[1]);at=lambda v:datetime.datetime.fromisoformat(v)
 assert f['token_id']==point['token_id'] and f['source']=='https://clob.polymarket.com' and 0<=(at(point['observed_at'])-at(f['available_at'])).total_seconds()<=300
 assert f['fee_rate']==raw['fee_rate'] and f['raw_response_ids']==raw['raw_response_ids']
 responses=[]
 for ref in f['raw_response_ids']:
  item2=archive.get(ref);assert item2 and item2[0]=='PublicFeeResponse';v=json.loads(item2[1]);assert v['source']=='https://clob.polymarket.com' and at(v['available_at'])<=at(f['available_at']) and digest(v['payload'])==v['content_sha256'];responses.append(v)
 token=point['token_id'];parent=next(v['payload'] for v in responses if v['url']=='https://clob.polymarket.com/markets-by-token/'+token)
 assert token in {str(parent['primary_token_id']),str(parent['secondary_token_id'])};condition=parent['condition_id']
 details=next(v['payload'] for v in responses if v['url']=='https://clob.polymarket.com/clob-markets/'+condition)
 assert details.get('c',condition)==condition and token in {str(t['t']) for t in details['t']}
 curve=details['fd'];assert curve['to'] is True and float(curve['e'])==1 and abs(float(curve['r'])-f['fee_rate'])<=1e-12
 fee_proofs[key]={'observation_sha256':item[2],'raw_response_ids':f['raw_response_ids']};return True
previous_study = None
for entry in sorted(m['records'],key=lambda r:(r['available_at'],r['id'])):
 raw=(base/'capture'/entry['path']).read_bytes();assert len(raw)==entry['bytes'] and hashlib.sha256(raw).hexdigest()==entry['sha256'];study=json.loads(raw);assert archive.verify_study(study);studies[study['id']]=study
 if previous_study is not None:assert study['parent_id']==previous_study['id'] and datetime.datetime.fromisoformat(study['available_at'])>datetime.datetime.fromisoformat(previous_study['available_at']), 'incomplete source-study chain; first-label proof withheld'
 previous_study=study
 result=history.observe(study['raw_frame'],now=datetime.datetime.fromisoformat(study['available_at']))
 for p in result['accepted']:
  assert archive.verify_point(p,study);assert not p['fee_observation_valid'] or verify_fee(p);points[p['id']]=p;sources[p['id']]=study['id']
 for pair in result['matured']:
  assert archive.verify_pair(pair,studies[sources[pair['decision']['id']]],study);pairs[pair['id']]=pair
assert archive.verify_chain(list(studies.values())), 'complete authenticated source window required'
forecasts={f['point_id']:f for f in causal_forecasts(list(points.values()),cutoff=protocol['cutoff'])};rows=[];economics_rejections={};sensitivity={str(key):[] for key in [(0,0),(1,.01),(1.5,.02),(2,.03)]};micro=[]
for pair in pairs.values():
 decision,label=pair['decision'],pair['label'];forecast=forecasts.get(decision['id'])
 if not forecast:continue
 costs=evaluate_roundtrip(decision,label);supported=bool(costs['depth_supported'] and costs.get('best_limit_full_quantity_supported') and costs.get('standard_notional_eligible'))
 for reason in costs['reasons']:economics_rejections[reason]=economics_rejections.get(reason,0)+1
 # Selection uses only decision fee/depth. Future exit fees are outcomes, never features.
 rate=decision['fee_rate'];entry=decision['ask_vwap'];edges={name:value*(1-rate)-entry*(1+rate)-.02 for name,value in forecast['forecasts'].items()}
 proof={'decision_study':sources[decision['id']],'label_study':sources[label['id']],
        'decision_sha256':digest(decision),'label_sha256':digest(label),'pair_sha256':digest(pair),
        'feature_point_ids':forecast['feature_point_ids'],'feature_sha256':digest([points[k] for k in forecast['feature_point_ids']])}
 row={'id':pair['id'],'event_id':pair['event_id'],'token_id':decision['token_id'],'market_id':decision['market_id'],
      'decision_at':pair['decision_at'],'target_at':pair['target_at'],'label_at':label['source_at'],
      'label_available_at':pair['label_available_at'],'label_observed_at':pair['label_observed_at'],
      'actual_bid':pair['actual_bid'],'baseline':pair['unchanged_bid_baseline'],'forecasts':forecast['forecasts'],
      'estimated_edge_by_candidate':edges,'costs':{**costs,'executable':supported,
         'executable_field_semantics':'displayed-depth, minlot and standard-notional modeled support; entry latency unverified; no fill claim'},
      'independence_reviewed':False,'provenance':proof}
 verified[row['id']]=digest(row);rows.append(row)
 for (fee,slip) in [(0,0),(1,.01),(1.5,.02),(2,.03)]:
  result=evaluate_roundtrip(decision,label,fee_multiplier=fee,slippage_per_leg=slip)
  if result['net_per_share'] is not None:sensitivity[str((fee,slip))].append(result['net_per_share'])
 market=next(x for x in studies[sources[decision['id']]]['raw_frame']['markets'] if x['token_id']==decision['token_id'])
 end=market.get('end_time');seconds=(datetime.datetime.fromisoformat(end)-datetime.datetime.fromisoformat(decision['observed_at'])).total_seconds() if end else None
 micro.append({'decision_id':decision['id'],'event_id':decision['event_id'],'spread':decision['spread'],
      'imbalance':decision['imbalance'],'bid_depth_shares':decision['bid_depth_shares'],'ask_depth_shares':decision['ask_depth_shares'],
      'time_to_expiration_seconds':seconds,'source_age_seconds':(datetime.datetime.fromisoformat(decision['observed_at'])-datetime.datetime.fromisoformat(decision['source_at'])).total_seconds(),
      'adverse_bid_move':decision['bid']-label['bid'],'net_quote_mark':costs['net_per_share']})
verify=lambda row: row.get('id') in verified and digest(row)==verified[row['id']]
result=evaluate_experiments(rows,training_end=protocol['training_end'],validation_end=protocol['validation_end'],cutoff=protocol['cutoff'],verify_row=verify)
result['data_provenance']={'native_fee_observations_verified':len(fee_proofs),'studies':len(studies),'accepted_points':len(points),'matured_pairs':len(pairs),'forecasts':len(forecasts),'raw_source_verified_rows':len(verified),'protocol_sha256':m['protocol_sha256'],'capture_manifest_sha256':hashlib.sha256((base/'capture/manifest.json').read_bytes()).hexdigest(),'first_target_choice':'entireorderednative source-study window replayedthrough unchangedPhase16CausalHistory; endpointsindependentlyrecomputed','created_prospectively':False,'hypotheses_preregistered_before_future_holdout':True}
result['economics_rejections']=economics_rejections
result['sensitivity']={key:{'matched_marks':len(values),'mean_net_per_share':sum(values)/len(values) if values else None,'positive_marks':sum(v>1e-9 for v in values),'semantics':'descriptive matched quote arithmetic; fee/slipzero is sensitivity only, not admission'} for key,values in sensitivity.items()}
result['worker']={'pid':os.getpid(),'cpu_seconds':time.process_time()-cpu,'elapsed_seconds':time.monotonic()-start,'max_rss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}
for name,value in [('rows.json',rows),('microstructure.json',micro),('results.json',result)]:
 body=json.dumps(value,sort_keys=True,indent=2,allow_nan=False);assert len(body.encode())<32*1024**2;(out/name).write_text(body+'\n')
archive.close();print(json.dumps({k:result[k] for k in ['samples','strict_event_disjoint_heldout_samples','data_provenance','sensitivity','inference_status','worker']},indent=2))
