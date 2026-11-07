"""Bounded native read-only strategy evidence; no database owners or mutations."""
import collections,datetime,hashlib,json,pathlib,sqlite3,time
from neraium_poly.contracts import OrderBookSnapshot
from neraium_poly.research.archive import BookDelta,BookReceipt,apply_observation
root=pathlib.Path('/home/ubuntu/Neraium-Poly');base=root/'data/experimental-paper';out=pathlib.Path('data/phase17');started=time.monotonic();sources=[]
def at(s):return datetime.datetime.fromisoformat(s)
def sha(s):return hashlib.sha256(s.encode()).hexdigest()
def db(p):
 c=sqlite3.connect(f'file:{p}?mode=ro',uri=True,timeout=10);c.row_factory=sqlite3.Row;c.execute('PRAGMA query_only=ON');return c
risk=db(base/'risk.sqlite');risk.execute('BEGIN');signals=[dict(r) for r in risk.execute('SELECT * FROM experimental_signals')];signals=sorted([{'signal':json.loads(r['payload']),'result':json.loads(r['result']),'native_payload_sha256':sha(r['payload']),'native_result_sha256':sha(r['result'])} for r in signals],key=lambda r:r['signal']['available_at']);account=dict(risk.execute('SELECT * FROM account WHERE id=1').fetchone());positions=[dict(r) for r in risk.execute('SELECT * FROM positions')];exits=[dict(r) for r in risk.execute('SELECT * FROM experimental_exits')];risk.close()
broker=db(base/'broker.sqlite');orders=[dict(r) for r in broker.execute('SELECT * FROM orders')];broker_audit=[dict(r) for r in broker.execute('SELECT * FROM audit')];broker.close()
cat=db(base/'events-archive.sqlite');cache=collections.OrderedDict();source_counts=collections.Counter()
def fetch(identity):
 if identity in cache:return cache[identity]
 r=cat.execute('SELECT * FROM records WHERE id=?',(identity,)).fetchone()
 if r is None:return None
 name=r['segment'];p=base/'events.sqlite' if name=='legacy' else base/'events-segments'/name
 c=db(p);row=c.execute('SELECT kind,payload,digest FROM events WHERE id=?',(identity,)).fetchone();c.close()
 assert row and row['kind']==r['kind'] and row['digest']==r['digest'] and sha(row['payload'])==row['digest']
 raw=json.loads(row['payload']);value=(row['kind'],raw,row['digest']);cache[identity]=value
 source_counts[row['kind']]+=1;sources.append({'id':identity,'kind':row['kind'],'sha256':row['digest'],'segment':name})
 if len(cache)>2048:cache.popitem(last=False)
 return value
def book(identity):
 item=fetch(identity) or fetch(sha('book-observation:'+identity))
 if item is None:return None
 kind,raw,proof=item
 if kind=='OrderBookSnapshot':return raw,{'kind':kind,'id':raw['id'],'sha256':proof}
 if kind not in ['BookReceipt','BookDelta']:return None
 record=(BookDelta if kind=='BookDelta' else BookReceipt).model_validate(raw);baseitem=fetch(record.full_book_id)
 assert baseitem and baseitem[0]=='OrderBookSnapshot';basebook=OrderBookSnapshot.model_validate(baseitem[1]);assert basebook.available_at<=record.available_at
 observed=apply_observation(basebook,record)
 return observed.model_dump(mode='json'),{'kind':kind,'id':raw['id'],'sha256':proof,'canonical_full_book_id':record.full_book_id,'canonical_full_sha256':baseitem[2]}
new=[r for r in signals if datetime.datetime(2026,11,6,23,30,tzinfo=datetime.timezone.utc)<=at(r['signal']['available_at'])<datetime.datetime(2026,11,6,23,34,30,tzinfo=datetime.timezone.utc)]
assert len(signals)<=100 and len(new)==11
cycles=cat.execute("SELECT id FROM records WHERE kind='ExperimentalCycle' AND available_at>=? AND available_at<? ORDER BY available_at,id LIMIT 100",('2026-11-06T23:31:00','2026-11-06T23:34:30')).fetchall();observed={};token=new[0]['signal']['token_id']
for r in cycles:
 item=fetch(r['id']);cycle=item[1]
 assert len(cycle['observed_book_ids'])<=128
 for identity in cycle['observed_book_ids']:
  value=book(identity)
  if value is None:continue
  b,proof=value
  if b['token_id']!=token:continue
  if not b['complete'] or not b['bids'] or not b['asks']:continue
  assert at(b['timestamp'])<=at(b['available_at'])<=at(cycle['available_at'])
  if (at(cycle['available_at'])-at(b['timestamp'])).total_seconds()>15:continue
  observed[b['id']]={'book':b,'proof':proof,'cycle_id':cycle['id'],'cycle_available_at':cycle['available_at']}
labels=sorted(observed.values(),key=lambda r:(at(r['book']['timestamp']),at(r['book']['available_at']),r['book']['id']))
rows=[]
for record in new:
 signal=record['signal'];native=fetch(signal['id']);assert native and native[0]=='ExperimentalSignal' and native[1]==signal
 entry=book(signal['evidence_ids'][0]);assert entry is not None;b,proof=entry;decision=at(signal['available_at']);assert b['token_id']==signal['token_id'] and b['market_id']==signal['market_id'];assert at(b['timestamp'])<=at(b['available_at'])<=decision and (decision-at(b['timestamp'])).total_seconds()<=15
 assert b['bids'][0]['price']==signal['diagnostics']['current_bid'] and b['asks'][0]['price']==signal['diagnostics']['entry_ask']
 target=decision+datetime.timedelta(seconds=signal['horizon_seconds']);ready=target+datetime.timedelta(seconds=.1)
 candidates=[r for r in labels if ready<=at(r['book']['timestamp'])<=target+datetime.timedelta(seconds=30)]
 row={'signal_id':signal['id'],'decision_at':signal['available_at'],'parent_event':signal['event_id'],'market_id':signal['market_id'],'token_id':signal['token_id'],'forecast':signal['forecast_value'],'lower':signal['lower_value'],'upper':signal['upper_value'],'estimated_net_edge_at_decision':signal['estimated_net_edge'],'native_payload_sha256':record['native_payload_sha256'],'signal_archive_sha256':native[2],'result':record['result'],'decision_book_proof':proof,'decision_bid':b['bids'][0]['price'],'decision_ask':b['asks'][0]['price'],'decision_source_at':b['timestamp'],'decision_receipt_at':b['available_at'],'future_label_status':'unavailable','counterfactual_net_pnl':None,'counterfactual_fill':None}
 if candidates:
  label=candidates[0];bid=label['book']['bids'][0]['price'];row.update(future_label_status='native_observed_quote_mark',target_at=target.isoformat(),label_book_proof=label['proof'],label_book_id=label['book']['id'],label_source_at=label['book']['timestamp'],label_receipt_at=label['book']['available_at'],label_collection_cycle_id=label['cycle_id'],label_collection_cutoff=label['cycle_available_at'],actual_bid=bid,horizon_seconds=(at(label['book']['timestamp'])-decision).total_seconds(),forecast_absolute_error=abs(signal['forecast_value']-bid),baseline_absolute_error=abs(b['bids'][0]['price']-bid),within_unvalidated_forecast_band=signal['lower_value']<=bid<=signal['upper_value'],bid_change=bid-b['bids'][0]['price'],gross_crossed_quote_mark_per_share=bid-b['asks'][0]['price'])
 rows.append(row)
cat.close();matched=[r for r in rows if r['future_label_status']=='native_observed_quote_mark'];counts=collections.Counter(reason for r in signals for reason in r['result'].get('reasons',[]) if r['result'].get('status')!='submitted');new_counts=collections.Counter(reason for r in new for reason in r['result'].get('reasons',[]) if r['result'].get('status')!='submitted')
ends={};episodes=0
for r in sorted(matched,key=lambda r:at(r['label_source_at'])):
 if r['parent_event'] not in ends or at(r['decision_at'])>=ends[r['parent_event']]:
  episodes+=1;ends[r['parent_event']]=at(r['label_source_at'])
audit=json.loads((root/'data/phase16/live-trade-audit.json').read_text());trade={'entry_fill':audit['fill_report'],'exit':audit['exit'],'actual_entry_fill_latency_seconds':audit['actual_fill_latency_seconds'],'configured_minimum_latency_seconds':audit['simulated_configured_latency_seconds'],'entry_bid_at_decision':audit['entry_quote']['best_bid']['price'],'entry_ask_at_decision':audit['entry_quote']['best_ask']['price'],'exit_bid':audit['exit_quote']['best_bid']['price'],'entry_fee':audit['fill_report']['fees'],'exit_fee':audit['exit']['fees'],'realized_simulated_pnl':audit['realized_simulated_pnl_this_trade'],'original_checks':audit['checks'],'source_audit_sha256':hashlib.sha256((root/'data/phase16/live-trade-audit.json').read_bytes()).hexdigest()}
result={'created_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'research_only':True,'trading_authority':False,'certification_authority':False,'native_counts':{'lifetime_signal_records':len(signals),'phase16_signal_records':len(new),'lifetime_rejection_reasons':dict(counts),'phase16_rejection_reasons':dict(new_counts),'lifetime_broker_orders':len(orders),'lifetime_broker_audit_rows':len(broker_audit),'lifetime_exit_orders':len(exits),'current_open_positions':len(positions),'current_cash':account['cash'],'current_realized_simulated_pnl':account['realized']},'original_phase17_baseline':{'cash':498.73125,'realized_simulated_pnl':-1.26875,'orders':1,'fills':2,'positions':0},'signal_followup':rows,'followup_summary':{'matched_quote_marks':len(matched),'unmatched':len(rows)-len(matched),'single_parent_event_groups':len({r['parent_event'] for r in rows}),'independent_reviewed_event_groups':0,'effective_nonoverlapping_60s_episodes':episodes,'model_mark_mae':sum(r['forecast_absolute_error'] for r in matched)/len(matched) if matched else None,'unchanged_bid_baseline_mae':sum(r['baseline_absolute_error'] for r in matched)/len(matched) if matched else None,'band_coverage_count':sum(r['within_unvalidated_forecast_band'] for r in matched),'band_sample_count':len(matched),'positive_gross_crossed_marks':sum(r['gross_crossed_quote_mark_per_share']>1e-9 for r in matched),'negative_gross_crossed_marks':sum(r['gross_crossed_quote_mark_per_share']<-1e-9 for r in matched),'maximum_gross_crossed_quote_mark_per_share':max((r['gross_crossed_quote_mark_per_share'] for r in matched),default=None),'positive_after_default_slippage_before_fees_quote_marks':sum(r['gross_crossed_quote_mark_per_share']-.02>1e-9 for r in matched),'roundtrip_slippage_assumption_per_share':.02,'net_after_actual_execution_costs':None,'p_value':None,'confidence_interval':None,'brier':None,'log_loss':None},'verified_trade':trade,'native_source_records':sources,'native_source_counts':dict(source_counts),'read_seconds':time.monotonic()-started,'limitations':['All eleven qualified signals concern one already-owned token in one event, with overlapping horizons; they are not eleven independent trades.','The source quote followups are monetary bid marks, not independent event resolution outcomes.','Counterfactual rejected orders lack independently preserved producer health, per-candidate execution-ready order evidence and post-latency entry survival. Their hypothetical fill and net P/L remain null.','Matched raw quote changes cannot establish that an ownership rejection prevented a loss or that relaxing it would help.','No extrapolation from this selected episode to all market conditions or rejected strategies is justified.','The unchanged-bid baseline and forecasts are compared at the same original decision cutoff; future labels were used solely for retrospective scoring.','No production model, risk threshold, account, original archive record or service was changed.']}
(out/'strategy-native-analysis.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({'native_counts':result['native_counts'],'followup_summary':result['followup_summary'],'source_counts':dict(source_counts),'seconds':result['read_seconds']},indent=2))
