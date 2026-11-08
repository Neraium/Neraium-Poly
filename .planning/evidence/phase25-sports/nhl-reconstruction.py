"""Exploratory current-vintage NHL comparison; never historical PIT/live performance."""
import collections,datetime,hashlib,json,math,pathlib,random,statistics
from neraium_poly.research.phase14.contracts import DomainEvidence
from neraium_poly.research.phase14.relationships import digest
from neraium_poly.research.phase25 import sports

ROOT=pathlib.Path('.planning/evidence/phase25-sports');RAW=pathlib.Path('data/phase25/nhl-evidence.json')
NOW=datetime.datetime.now(datetime.timezone.utc)
evidence=DomainEvidence.model_validate_json(RAW.read_text());_e,events=sports._parse(evidence,NOW)
finals=[g for g in events if g['final']];assert len(finals)>=160
training0,targets=finals[:-60],finals[-60:]
assert len(training0)>=100
protocol={'created_at':NOW.isoformat(),'classification':'EXPLORATORY_CURRENT_VINTAGE_RECONSTRUCTION',
 'prospective':False,'point_in_time_certified':False,'untouched_holdout':False,'trading_authority':False,
 'source_path':str(RAW.absolute()),'source_file_sha256':hashlib.sha256(RAW.read_bytes()).hexdigest(),
 'dataset_sha256':digest(finals),'publisher_is_official':False,'first_observed_at':evidence.available_at.isoformat(),
 'model_definitions':sports.definitions(),'models':['nhl-causal-elo-v25.1','nhl-beta-frequency-v25.1','causal_home_frequency_beta22','constant_half'],
 'test_target_ids':[g['id'] for g in targets],'initial_training_ids':[g['id'] for g in training0],
 'split':'last60 chronological unique publisher-finalgame IDs, prequential expanding prior-data training; not a frozen untouched holdout',
 'cutoff_proxy':'only current-vintage finals whose start is at least24hours before target start; source has no historical final-availability timestamps',
 'eligibility':'100 priorfinals and5results per participant, same eligible target cohort for allmodels',
 'bootstrap':{'unit':'UTC target-start calendar day','replicates':1000,'seed':20261108,'cpu_workers':1,'interval':'descriptive unadjusted95percentile'},
 'costs_fills_pnl':None,'historical_execution_books':False,'independent_event_count':None,
 'limitations':['Models already developed with this dataset; post-selection/overfit risk','All source data first retrieved now; no verified historical availability',
  '24hour embargo avoids ordinary overlaps but cannot prove old finality or account for postponement/revisions','Calendar-day blocks do not eliminate cross-day shared-team dependence',
  'Publisher is not official result authority','No contemporaneous historical market baseline or executable books; no trading return or superiority claim']}
manifest=ROOT/'reconstruction-protocol.json'
if manifest.exists():raise RuntimeError('refuse protocol overwrite; preserved experiment requires separate version')
manifest.write_text(json.dumps(protocol,indent=2)+'\n') # predeclare before scoring


def predictions(training,target):
 counts=collections.Counter(t for g in training for t in [g['home_id'],g['away_id']]);h,a=target['home_id'],target['away_id']
 if len(training)<100 or min(counts[h],counts[a])<5:return None
 ratings={};wins=collections.Counter();hw=0
 for i,g in enumerate(training):
  hh,aa=g['home_id'],g['away_id'];actual=int(g['home_score']>g['away_score']);prior=(hw+2)/(i+4)
  adv=400*math.log10(prior/(1-prior));p=1/(1+10**((ratings.get(aa,1500)-ratings.get(hh,1500)-adv)/400))
  delta=20*(actual-p);ratings[hh]=ratings.get(hh,1500)+delta;ratings[aa]=ratings.get(aa,1500)-delta
  wins[hh if actual else aa]+=1;hw+=actual
 prior=(hw+2)/(len(training)+4);adv=400*math.log10(prior/(1-prior))
 elo=1/(1+10**((ratings.get(a,1500)-ratings.get(h,1500)-adv)/400))
 ph=(wins[h]+2)/(counts[h]+4);pa=(wins[a]+2)/(counts[a]+4);odds=ph/(1-ph)/(pa/(1-pa))*prior/(1-prior)
 return dict(zip(protocol['models'],[elo,odds/(1+odds),prior,.5]))


rows=[];rejected=[]
for target in targets:
 start=sports._at(target['start']);cutoff=start-datetime.timedelta(hours=24)
 training=[g for g in finals if sports._at(g['start'])<=cutoff]
 assert target['id'] not in {g['id'] for g in training}
 ps=predictions(training,target)
 if ps is None:rejected.append({'game_id':target['id'],'reason':'100priorfinals_or5perparticipant_insufficient','training_games':len(training)});continue
 y=int(target['home_score']>target['away_score']);metrics={}
 for model,p in ps.items():metrics[model]={'probability':p,'brier':(p-y)**2,'log_loss':-math.log(p if y else 1-p)}
 rows.append({'game_id':target['id'],'target_start':target['start'],'start_embargo_cutoff':cutoff.isoformat(),
  'home_id':target['home_id'],'away_id':target['away_id'],'home':target['home'],'away':target['away'],
  'actual_home_win':y,'training_games':len(training),'training_sha256':digest(training),'metrics':metrics})
assert rows
blocks=collections.defaultdict(list)
for r in rows:blocks[r['target_start'][:10]].append(r)
keys=sorted(blocks);rng=random.Random(protocol['bootstrap']['seed']);replicates=[]
for _ in range(1000):replicates.append([r for _j in keys for r in blocks[rng.choice(keys)]])
def interval(values):
 xs=sorted(values)
 def q(p):
  i=(len(xs)-1)*p;lo=int(i);return xs[lo]+(xs[min(lo+1,len(xs)-1)]-xs[lo])*(i-lo)
 return [q(.025),q(.975)]
models={}
for model in protocol['models']:
 models[model]={'brier':statistics.mean(r['metrics'][model]['brier'] for r in rows),
 'log_loss':statistics.mean(r['metrics'][model]['log_loss'] for r in rows),
 'brier_95pct_dayblock':interval([statistics.mean(r['metrics'][model]['brier'] for r in b) for b in replicates]),
 'log_loss_95pct_dayblock':interval([statistics.mean(r['metrics'][model]['log_loss'] for r in b) for b in replicates]),
 'calibration_in_large':{'mean_probability':statistics.mean(r['metrics'][model]['probability'] for r in rows),'actual_home_win_rate':statistics.mean(r['actual_home_win'] for r in rows)},
 'paired_difference_vs_baselines':{}}
 for base in ['constant_half','causal_home_frequency_beta22']:
  models[model]['paired_difference_vs_baselines'][base]={metric:{'mean':statistics.mean(r['metrics'][model][metric]-r['metrics'][base][metric] for r in rows),
  'descriptive_95pct_dayblock':interval([statistics.mean(r['metrics'][model][metric]-r['metrics'][base][metric] for r in b) for b in replicates])} for metric in ['brier','log_loss']}
result={'evaluated_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'classification':protocol['classification'],'protocol_sha256':digest(protocol),
 'script_sha256':hashlib.sha256(pathlib.Path(__file__).read_bytes()).hexdigest(),'source_sha256':protocol['source_file_sha256'],'dataset_sha256':protocol['dataset_sha256'],
 'publisher_final_games':len(finals),'initial_training_games':len(training0),'heldback_targets':60,'eligible_targets':len(rows),'rejections':rejected,
 'native_game_ids':len({r['game_id'] for r in rows}),'calendar_day_blocks':len(keys),'effective_independent_event_count':None,
 'models':models,'exploratory_brier_order':sorted(models,key=lambda m:models[m]['brier']),
 'forecasting_superiority_supported':False,'certification_eligible':False,'profitability_rank':None,'execution_pnl':None,
 'calibration_status':'descriptive only; models already developed from current-vintage dataset','limitations':protocol['limitations'],'rows':rows}
(ROOT/'reconstruction-results.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps({k:result[k] for k in ['publisher_final_games','heldback_targets','eligible_targets','calendar_day_blocks','exploratory_brier_order']}))
print(json.dumps({k:{m:v[m] for m in ['brier','log_loss']} for k,v in models.items()},indent=2))
