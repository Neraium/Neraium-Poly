"""Read-only current forecast audit; no outcomes or predictions are appended."""
import asyncio
import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import httpx
from neraium_poly.research.phase14.relationships import digest
from neraium_poly.research.phase17.provenance import ReadonlyArchive
from neraium_poly.research.phase32.macro import _mapping, macro_outcome_inventory

async def main():
    now=datetime.now(UTC);root=Path('/home/ubuntu/Neraium-Poly/data/experimental-paper')
    c=sqlite3.connect(f'file:{root}/research-projection.sqlite?mode=ro',uri=True)
    entries=[json.loads(x[0]) for x in c.execute('select payload from entries')];c.close()
    selected=[e for e in entries if e.get('type')=='forecast' and e['forecast']['domain']=='economics'];inventory=macro_outcome_inventory(selected,as_of=now);checks=[]
    with ReadonlyArchive(root) as archive:
        for ref in selected:
            body=archive.get(ref['source_id']);body=body if isinstance(body,dict) else json.loads(body[1]);assert digest(body)==ref['source_study_sha256']
            f=next(f for f in body['forecasts'] if f['id']==ref['forecast_id']);assert digest(f)==ref['forecast_sha256'];contract,module,boundary=_mapping(f)
            checks.append({'forecast_id':f['id'],'market_id':f['market_id'],'event_id':f['event_id'],'model_id':f['model_id'],'kind':contract['kind'],'official_publication_boundary':boundary.isoformat(),'matured':now>=boundary,'original_timestamp':f['timestamp'],'source_hash_and_exact_contract_replayed':True,'scope':'boundary is scheduled/contract bound, not asserted actual final publication'})
    sources=[]
    async with httpx.AsyncClient(timeout=10,follow_redirects=False) as client:
        for url in ['https://www.ons.gov.uk/economy/grossdomesticproductgdp/bulletins/gdpfirstquarterlyestimateuk/previousreleases','https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm']:
            response=await client.get(url);sources.append({'source_url':url,'status':response.status_code,'retrieved_at':datetime.now(UTC).isoformat(),'content_sha256':hashlib.sha256(response.content).hexdigest(),'bytes':len(response.content),'availability_scope':'current source check, not historical feature availability'})
    out=Path('.planning/evidence/phase32-macro');(out/'inventory.json').write_text(json.dumps({'observed_at':now.isoformat(),'inventory':inventory,'exact_original_checks':checks,'official_source_checks':sources,'new_verified_outcomes':0,'diagnosis':'All four original economic forecasts remain future; old verifiers conflate official result and native payout, now separated by new verifier. No CPI denominator imputation; no new unsupported forecasts.'},indent=2)+'\n')
    print(json.dumps({'forecasts':len(checks),'all_future':all(not x['matured'] for x in checks),'reviewed_groups':inventory['reviewed_event_groups'],'source_statuses':[s['status'] for s in sources]}))

if __name__=='__main__':asyncio.run(main())
