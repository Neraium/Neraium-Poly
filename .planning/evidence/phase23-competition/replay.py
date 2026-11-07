"""Read-only bounded reconstruction, not prospective evidence or certified fills."""
import hashlib,json,pathlib,statistics,urllib.request
from datetime import UTC,datetime,timedelta
from neraium_poly.research.phase23.relationships import evaluate_relationships
ROOT=pathlib.Path('/home/ubuntu/Neraium-Poly');out=pathlib.Path('.planning/evidence/phase23-competition')
folder=ROOT/'data/phase8-public-l2-sample';manifest=json.loads((folder/'manifest.json').read_text());filename='btc-single-market.json';raw=(folder/filename).read_bytes();sha=hashlib.sha256(raw).hexdigest();entries=[f for f in manifest['files'] if f['file']==filename];assert len(entries)==1 and entries[0]['sha256']==sha
sample=json.loads(raw);evaluated=[];rejected=0
for side,rows in sample['data'].items():
 by_time={datetime.fromisoformat(r['t'].replace('Z','+00:00')):r for r in rows}
 for t,row in sorted(by_time.items()):
  if t.second%15:continue
  later=by_time.get(t+timedelta(seconds=5))
  if not later or not row['bids'] or not row['asks'] or not later['bids'] or not later['asks']:rejected+=1;continue
  bid,ask=row['bids'][0][0],row['asks'][0][0];ebid,eask=later['bids'][0][0],later['asks'][0][0]
  if not 0<bid<ask<1 or not 0<ebid<eask<1:rejected+=1;continue
  bs=sum(v[1] for v in row['bids'][:3]);aas=sum(v[1] for v in row['asks'][:3]);imbalance=(bs-aas)/(bs+aas)
  evaluated.append({'publisher_capture_at':t.isoformat(),'side':side,'imbalance':imbalance,
   'five_second_midpoint_change':(ebid+eask-bid-ask)/2,'hypothetical_buy_ask_sell_bid_change_per_share':ebid-ask,
   'entry_depth_at_ask':row['asks'][0][1],'exit_depth_at_bid':later['bids'][0][1]})
selected=[r for r in evaluated if r['imbalance']>.2]
def summary(rows):
 return {'quote_episodes':len(rows),'mean_gross_bid_ask_change_per_share':statistics.mean(r['hypothetical_buy_ask_sell_bid_change_per_share'] for r in rows) if rows else None,'after_fee_expected_value':None,'actual_fills':0}
report={'observed_at':datetime.now(UTC).isoformat(),'classification':'historical_exploratory_reconstruction',
 'source_file':str(folder/filename),'source_sha256':sha,'publisher_url':entries[0]['final_url'],
 'verified_retrieval_at':entries[0]['retrieved_at'],'publisher_market_id':sample['metadata']['market_id'],
 'publisher_start':sample['metadata']['start_ts'],'publisher_end':sample['metadata']['end_ts'],
 'publisher_rows':sum(len(x) for x in sample['data'].values()),'eligible_nonoverlapping_five_second_episodes':len(evaluated),
 'episodes_rejected':rejected,'raw_parent_events':1,'reviewed_independent_groups':0,
 'baseline_all_eligible':summary(evaluated),'exploratory_positive_imbalance_over_point2':summary(selected),
 'calibration_metrics':None,'verified_outcomes':0,'qualified_training_events':0,'qualified_heldout_events':0,
 'historical_availability_verified':False,'historical_execution_certified':False,'trading_authority':False,
 'limitations':['Publisher capture times are not original exchange source or receipt timestamps',
 'Originally retrieved after the historical event; no historical availability proof',
 'One market/two complementary tokens are one dependent event, not independent samples',
 'Threshold selected for exploratory diagnostic; no held-out evaluation or inference',
 'Displayed prices are not fills; fees, queue survival and latency unavailable',
 'Publisher winner field excluded entirely; no verified settlement outcome created']}
(out/'historical-replay.json').write_text(json.dumps(report,indent=2)+'\n')
with urllib.request.urlopen('http://127.0.0.1:18742/api/market-frame',timeout=12) as r:frame=json.load(r)
now=datetime.now(UTC);relationships=evaluate_relationships(frame,[],cutoff=now)
live={'observed_at':now.isoformat(),'source_frame_id':frame['id'],'source_frame_sha256':hashlib.sha256(json.dumps(frame,sort_keys=True,separators=(',',':')).encode()).hexdigest(),
 'native_market_rows':len(frame['markets']),'native_book_rows':len(frame['books']),
 'healthy_microstructure_observations':len(relationships['microstructure_observations']),
 'same_contract_binary_consistency_observations':len(relationships['binary_consistency_observations']),
 'persistent_sii_findings':len(relationships['persistent_relationship_findings']),
 'rejections':relationships['rejections'],'historical_frames_used':0,
 'source_projection_sha256':relationships['projection']['projection_sha256'],
 'independent_forecasts_created':0,'trading_authority':False}
(out/'live-observations.json').write_text(json.dumps(live,indent=2)+'\n')
print(json.dumps({'historical':report,'live':live},indent=2))
