"""Strictly read-only live/native evidence audit; no labels or probabilities created."""
import json,sqlite3,urllib.request,statistics
from datetime import UTC,datetime,timedelta
from pathlib import Path
from neraium_poly.research.phase17.provenance import ReadonlyArchive
from neraium_poly.research.phase19.qualification import _original,replay_event_forecast
from neraium_poly.research.phase21.outcomes import reference_condition,replay_crypto_outcome
from neraium_poly.research.phase18.sources import completed_minutes
from neraium_poly.research.phase12.ledger import content_sha256
from neraium_poly.research.phase13.runtime import TernarySportsForecast,SportsResearchRuntime
from neraium_poly.research.phase13.sources import load_sports
from neraium_poly.research.phase13.mapping import map_market
from neraium_poly.research.phase13.models import predict_game
from neraium_poly.research.phase21.discovery import rank_research_markets
from neraium_poly.research.phase18.capacity import capacity_scenarios
from neraium_poly.research.phase14.relationships import digest
from neraium_poly.contracts import MarketSnapshot,OrderBookSnapshot
from neraium_poly.data import assess_book
out=Path('.planning/evidence/phase22-evidence');root=Path('/home/ubuntu/Neraium-Poly/data/experimental-paper');now=datetime.now(UTC)
def save(name,value):
 with (out/name).open('x') as f:json.dump(value,f,indent=2);f.write('\n')
with ReadonlyArchive(root,max_query_bytes=128*1024**2) as archive:
 studies=archive.latest('EventProbabilityStudy',1000);early=archive.latest('EventResolutionStudy',128);pairs=archive.latest('PairedForecastStudy',128)
 total=archive._catalog_rows('SELECT count(*) AS n FROM records WHERE kind=?',('EventProbabilityStudy',))[0]['n']
originals={s['forecast']['id']:s for s in studies if s.get('operation')=='forecast_scan' and s.get('forecast')}
references={}
for row in early:
 for e in row.get('evidence',[]):
  symbol=e.get('payload',{}).get('symbol')
  if symbol and symbol not in references:references[symbol]=(row,e)
crypto=[]
for fid,s in originals.items():
 f,m,b,_=_original(s);assert replay_event_forecast(s)['verified'];c=s['contract'];symbol=c['parameters']['symbol'];ref=references.get(symbol)
 condition=reference_condition(s,ref[1],as_of=now) if ref else {'status':'reference_unavailable','eligible_for_native_check':False}
 assert condition['status']!='withheld',condition
 crypto.append({'forecast_id':fid,'event_id':f.event_id,'market_id':m.market_id,'token_id':f.token_id,'selected_outcome':m.outcome,'question':m.question,'forecast_at':f.timestamp.isoformat(),'probability':f.probability,'model_version':f.model_version,'model_sha256':f.model_sha256,'dataset_sha256':f.dataset_sha256,'rules_sha256':f.rules_sha256,'original_study_id':s['id'],'original_study_sha256':digest(s),'original_model_replayed':True,'period_start':c['parameters']['period_start_utc'],'period_end':c['parameters']['period_end_utc'],'window_completed':datetime.fromisoformat(c['parameters']['period_end_utc'])<=now,'original_book_at':b.timestamp.isoformat(),'market_baseline':(b.bids[0].price+b.asks[0].price)/2,'condition':condition,'reference_study_id':ref[0]['id'] if ref else None,'reference_study_sha256':digest(ref[0]) if ref else None})
labels=[]
for s in studies+early:
 if s.get('operation')=='outcome_check' and s.get('outcome') and s.get('forecast',{}).get('id') in originals:
  replay=replay_crypto_outcome(s,originals[s['forecast']['id']],evidence_root=root/'phase18-resolution-evidence',as_of=now);labels.append(replay)
sportsroot=root/'event-intelligence/sports';db=sqlite3.connect((sportsroot/'prospective.sqlite').as_uri()+'?mode=ro',uri=True);db.row_factory=sqlite3.Row;rows=db.execute('SELECT * FROM records ORDER BY seq').fetchall();db.close();previous=None;sports=[]
for row in rows:
 data=json.loads(row['payload']);assert content_sha256(data)==row['digest'] and row['previous']==previous and row['chain']==content_sha256([previous,row['kind'],row['id'],row['digest']]);previous=row['chain']
 if row['kind']!='forecast':continue
 f=TernarySportsForecast.model_validate(data);source=load_sports(sportsroot/f.snapshot);assert SportsResearchRuntime._dataset_identity(source)==f.source_dataset_sha256
 mapping=map_market(f.market,source['games'],now=f.timestamp);assert mapping==f.mapping
 assert predict_game(source['games'],SportsResearchRuntime._target(source,mapping),mapping.selected_team_id,f.timestamp,method='frequency')==f.prediction
 assert all(a.available_at<=f.timestamp for a in source['artifacts'])
 sports.append({'forecast_id':f.id,'event_id':f.mapping.event_id,'market_id':f.market.market_id,'game_id':mapping.game_id,'forecast_at':f.timestamp.isoformat(),'game_start':mapping.event_start.isoformat(),'started':mapping.event_start<=now,'scheduled_check_after':(mapping.event_start+timedelta(hours=4)).isoformat(),'scheduled_check_due':mapping.event_start+timedelta(hours=4)<=now,'snapshot':f.snapshot,'source_dataset_sha256':f.source_dataset_sha256,'rules_sha256':mapping.rules_sha256,'model_source_replayed':True,'prospective':f.timestamp<mapping.event_start,'probability_semantics':'ternary_win_tie_loss; market price is expected payout, not pure win probability'})
sourcefacts=[]
for symbol,(row,e) in references.items():
 r=completed_minutes(e,cutoff=now,symbol=symbol,require_fresh=False);start=datetime.fromisoformat(next(s['contract']['parameters']['period_start_utc'] for s in originals.values() if s['contract']['parameters']['symbol']==symbol));window=[x for x in r if x['open_ms']>=int(start.timestamp()*1000)]
 sourcefacts.append({'symbol':symbol,'study_id':row['id'],'study_available_at':row['available_at'],'source_timestamp':e['source_timestamp'],'source_available_at':e['available_at'],'evidence_sha256':e['content_sha256'],'reference_minutes':len(window),'observed_daily_low':min(x['low'] for x in window),'age_seconds_at_audit':(now-datetime.fromisoformat(e['available_at'])).total_seconds()})
audit={'at':now.isoformat(),'archive_studies_total':total,'archive_studies_included':len(studies),'bounded_tail':total>len(studies),'crypto':crypto,'sports':sports,'source_facts':sourcefacts,'crypto_source_replayed':len(crypto),'crypto_parent_ids':sorted(set(x['event_id'] for x in crypto)),'crypto_completed_windows':sum(x['window_completed'] for x in crypto),'reference_conditions_met':sum(x['condition']['eligible_for_native_check'] for x in crypto),'replayed_native_outcomes':labels,'verified_outcomes':sum(x['verified'] for x in labels),'sports_outcome_records':sum(r['kind']=='outcome' for r in rows),'sports_journal_records':len(rows),'sports_journal_head_sha256':previous,'sii_records':len(pairs),'sii_latest':pairs[0]['checkpoint'] if pairs else None,'reviewed_independent_event_groups':0,'qualified_training_events':0,'qualified_heldout_events':0,'calibration_metrics':None,'sii_incremental_value':None,'authority':False,'scope':'Existing source-native snapshot only; no original forecast, database, evidence or account record modified. No source condition means no current reason to acquire a native settlement proof; reference hits alone never settle.'}
save('forecast-audit.json',audit)
with urllib.request.urlopen('http://127.0.0.1:18742/api/market-frame',timeout=15) as response:frame=json.load(response)
save('capacity-frame.json',frame);at=datetime.fromisoformat(frame['available_at']);ranking=rank_research_markets(frame['markets'],frame['books'],now=at);bytoken={b['token_id']:b for b in frame['books']};ready={r['market_id'] for r in ranking['markets'] if r['priority_ready']};scenarios=[]
for raw in frame['markets']:
 if raw['market_id'] not in ready:continue
 m=MarketSnapshot.model_validate(raw);b0=bytoken.get(m.token_id)
 if b0 is None:continue
 b=OrderBookSnapshot.model_validate(b0)
 if not assess_book(b,at,max_spread=.05,expected_token=m.token_id).healthy:continue
 op={'evaluated_at':at.isoformat(),'market_id':m.market_id,'token_id':m.token_id,'book_id':b.id,'book_sha256':digest(b.model_dump(mode='json')),'research_qualified':False,'min_order_size':m.min_order_size,'end_time':m.end_time.isoformat(),'lower_probability':None,'fee_rate':None}
 scenarios.append({'market_id':m.market_id,'event_id':m.event_id,'token_id':m.token_id,'outcome':m.outcome,'book_id':b.id,'book_at':b.timestamp.isoformat(),'bid':b.bids[0].model_dump(),'ask':b.asks[0].model_dump(),'capacity':capacity_scenarios(op,b)})
summary=[]
for i,capital in enumerate([500,1000,10000,100000,1000000]):
 values=[s['capacity']['scenarios'][i]['modeled_entry_notional'] for s in scenarios if s['capacity']['scenarios']]
 summary.append({'hypothetical_capital':capital,'books':len(values),'minimum':min(values) if values else None,'median':statistics.median(values) if values else None,'maximum':max(values) if values else None,'edge_qualified_capacity':None})
capacity={'retrieved_at':datetime.now(UTC).isoformat(),'frame_id':frame['id'],'frame_available_at':frame['available_at'],'frame_sha256':digest(frame),'ranking_summary':{k:v for k,v in ranking.items() if k!='markets'},'native_scenarios':scenarios,'capacity_summary':summary,'scope':'Current native book liquidity only,10% displayed participation and existing hypothetical exposure constraints. No qualified independent estimate, verified fees, fill or profitable EV. Correlated tokens/events cannot be summed.'}
save('capacity.json',capacity)
report={'observed_at':now.isoformat(),'crypto_forecasts':len(crypto),'sports_forecasts':len(sports),'crypto_parent_ids':audit['crypto_parent_ids'],'crypto_completed_windows':audit['crypto_completed_windows'],'reference_conditions_met':audit['reference_conditions_met'],'verified_outcomes':audit['verified_outcomes'],'sports_games_started':sum(x['started'] for x in sports),'sports_outcomes':audit['sports_outcome_records'],'crypto_period_ends':sorted(set(x['period_end'] for x in crypto)),'sports_game_starts':[{'game_id':x['game_id'],'at':x['game_start']} for x in sports],'source_facts':sourcefacts,'qualified_train_heldout':[0,0],'calibration':None,'sii_incremental_value':None,'capacity':summary,'priority_ready_markets':len(ready),'priority_ready_parent_ids':sorted(set(s['event_id'] for s in scenarios)),'native_book_scenarios':len(scenarios),'market_count':ranking['market_count'],'domain_distribution':ranking['domain_distribution']}
save('summary.json',report);print(json.dumps(report,indent=2))
