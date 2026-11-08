import datetime,json,pathlib,httpx,collections
from neraium_poly.research.phase17.provenance import ReadonlyArchive
from neraium_poly.research.phase25.dependencies import at
from neraium_poly.research.phase32.pairs import scan_pairs
from neraium_poly.research.phase33.economics import annotate_pair_fees
from neraium_poly.research.phase14.relationships import digest
root=pathlib.Path('/home/ubuntu/Neraium-Poly');local=pathlib.Path('data/phase33-economics')
r=httpx.get('http://127.0.0.1:18742/api/market-frame',timeout=15);r.raise_for_status();frame=r.json();now=datetime.datetime.now(datetime.UTC)
(local/'frame.json').write_text(json.dumps(frame)+'\n');pairs=scan_pairs(frame,as_of=now);observations={}
with ReadonlyArchive(root/'data/experimental-paper') as archive:
 for raw in archive.latest('FeeObservation',limit=128):
  token=raw['token_id']
  if token not in observations and at(raw['available_at'])<=now:observations[token]={'evidence_id':raw['id']}
 result=annotate_pair_fees(pairs,frame,observations,archive,as_of=now)
(local/'pair-report.json').write_text(json.dumps(pairs)+'\n');(local/'observations.json').write_text(json.dumps(observations)+'\n');(local/'full-headroom.json').write_text(json.dumps(result,indent=2)+'\n')
summary={'observed_at':now.isoformat(),'source_endpoint':'http://127.0.0.1:18742/api/market-frame','source_frame_id':frame['id'],'source_frame_sha256':digest(frame),
 'markets_considered':pairs['markets_considered'],'fresh_compatible_paired_books':pairs['paired_books_evaluated'],'positive_conditional_gross_pairs':pairs['positive_conditional_gross_pairs'],
 'evaluated_recorded_pairs':result.get('findings_evaluated'),'verified_native_fee_pairs':result['verified_fee_pairs'],'positive_formula_headroom_pairs':result['positive_formula_headroom_pairs'],
 'current_observations_loaded':len(observations),'rejections':result.get('rejections'), 'pair_scan_rejections':pairs['rejections'],
 'findings':[ {k:r.get(k) for k in ['market_id','event_id','token_ids','status','condition_id','reason','gross_frontier','maximum_formula_headroom','capital_scenarios']} for r in result['findings']],
 'conservative_positive_net_opportunities':0,'realized_pnl':None,'independent_forecasts_created':0,
 'scope':'actual current books and source-replayed official protocol fees where available; conditional pricing only, not verified payout, filled execution or all-in profitability',
 'research_only':True,'trading_authority':False,'new_provider_requests':0,'all_in_costs_verified':False}
pathlib.Path('.planning/evidence/phase33-economics/live-economics.json').write_text(json.dumps(summary,indent=2)+'\n');print({k:v for k,v in summary.items() if k not in ['findings','pair_scan_rejections']})
