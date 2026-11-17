"""Read-only, bounded verification of actual registered prospective records."""
import json
from pathlib import Path

from neraium_poly.research.phase14.relationships import digest
from neraium_poly.research.phase17.provenance import ReadonlyArchive
from neraium_poly.research.phase25.dependencies import at
from neraium_poly.research.phase46.program import POLICY

store=ReadonlyArchive('/home/ubuntu/Neraium-Poly/data/experimental-paper')
declarations=store.latest('ProgramDeclaration46',1);assert declarations and declarations[0]['policy']==POLICY
rows=store.latest('ProspectiveEvent46',16);assert rows
studies={};verified=[]
for row in rows:
    f=row['source_forecast'];ref=row['source_binding'];sid=ref['study_id']
    if sid not in studies:
        raw=store.get(sid);assert raw and len(raw[1].encode())<=8*1024**2
        studies[sid]=json.loads(raw[1]);assert digest(studies[sid])==ref['study_sha256']
    assert ref['forecast_sha256']==digest(f)
    assert any(digest(original)==digest(f) for original in studies[sid]['forecasts'])
    assert at(declarations[0]['timestamp'])<=at(f['timestamp'])<=at(row['timestamp'])<at(f['event_end_time'])
    assert 0<=(at(row['timestamp'])-at(row['book']['timestamp'])).total_seconds()<=15
    assert at(f['timestamp'])<=at(studies[sid]['available_at'])<=at(row['timestamp'])
    assert row['trading_authority'] is False and row['certification_authority'] is False
    verified.append({'trial_id':row['id'],'forecast_id':f['id'],'source_study_id':sid,'source_study_sha256':ref['study_sha256'],'registered_at':row['timestamp'],'forecast_at':f['timestamp'],'event_end':f['event_end_time'],'domain':f['domain'],'model':f['model_id'],'canonical_event':row['canonical_event'],'dependency_block':row['dependency_block'],'probabilities':row['probabilities'],'book_sha256':digest(row['book'])})
result={'declaration':declarations[0],'verified_sample_count':len(verified),'canonical_events':len({r['canonical_event'] for r in verified}),'records':verified,'scope':'actual durable prospective enrollments; no label creation, source mutation or certification'}
(__import__('pathlib').Path(__import__('sys').argv[1]) if len(__import__('sys').argv)>1 else Path(__file__).with_name('enrollments.json')).write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({k:result[k] for k in ('verified_sample_count','canonical_events')}))
