import json
from datetime import datetime,UTC,timedelta
from pathlib import Path
from neraium_poly.research.phase17.provenance import ReadonlyArchive
from neraium_poly.research.phase16.checkpoints import unpack_checkpoint
from neraium_poly.research.phase27.forecasting import replay_spx_payout
from neraium_poly.research.phase28.findings import build_economic_findings
root=Path('/home/ubuntu/Neraium-Poly/data/experimental-paper')
with ReadonlyArchive(root,max_query_bytes=128*1024**2) as store:
 studies=store.latest('PayoutForecastStudy',8);study=min(studies,key=lambda s:s['timestamp']);f=study['forecasts'][0]
 original=json.loads(store.get(study['original_study_id'])[1]);old=next(x for x in original['forecasts'] if x['id']==f['original_forecast_id'])
 assert replay_spx_payout(f,original,old,as_of=datetime.now(UTC))['verified']
 start=datetime.fromisoformat(study['available_at']).replace(tzinfo=UTC);end=start+timedelta(seconds=20)
 records=store._catalog_rows("SELECT * FROM records WHERE kind=? AND available_at>=? AND available_at<=? ORDER BY available_at LIMIT 4",('EconomicFindingStudy',start.isoformat(),end.isoformat()))
 for record in records:
  source=json.loads(store._fetch(record)[1]);frame=unpack_checkpoint(source['decision_frame'])
  if any(b['token_id']==f['token_id'] for b in frame['books']):break
 else:raise RuntimeError('actual contemporaneous archived frame unavailable')
 report=build_economic_findings([study],frame,as_of=source['timestamp'],verified_forecast_ids=[f['id']]);row=report['findings'][0]
 output={'observed_at':datetime.now(UTC).isoformat(),'scope':'new Phase28 valuation replay of authentic append-only prospective Phase27 forecast and its original actual decision frame; not a new live forecast, fill or profit','source_record_id':source['id'],'forecast_study_id':study['id'],'independent_model_replay':True,'report':report}
 Path('.planning/evidence/phase28-findings/authentic-replay.json').write_text(json.dumps(output,indent=2)+'\n')
 print(json.dumps({k:row.get(k) for k in ['market_id','expected_payout','scenario_expected_gross_profit','scenario_expected_net_profit','conservative_expected_net_profit','maximum_supported_quantity','break_even_entry_fee_rate_before_other_costs','status','reasons']}))
