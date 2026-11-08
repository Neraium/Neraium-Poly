import json,pathlib,datetime
from neraium_poly.research.phase17.provenance import ReadonlyArchive
from neraium_poly.research.phase14.relationships import digest
from neraium_poly.research.phase32.scoring import replay_event
now=datetime.datetime.now(datetime.UTC);rows=[]
with ReadonlyArchive(pathlib.Path('data/experimental-paper')) as archive:
 snapshot=archive.latest('EventScoreSnapshot',limit=1)[0];eid=snapshot['enrollment_id']
 for row in archive.latest('OfficialEventLabelStudy',limit=64):
  if row['enrollment_id']!=eid:continue
  s=archive.get(row['original_study_id']);s=s if isinstance(s,dict) else json.loads(s[1]);assert digest(s)==row['original_study_sha256']
  f=next(f for f in s['forecasts'] if f['id']==row['forecast_id']);assert digest(f)==row['original_forecast_sha256']
  proof=replay_event(row['result'],s,f,evidence_root=pathlib.Path('data/experimental-paper/phase30-official-event-evidence'),as_of=now)
  assert digest(proof)==digest(row['replay']) and proof['event_result_verified'] and not proof['native_payout_verified']
  rows.append({'label_id':row['id'],'forecast_id':f['id'],'domain':f['domain'],'event_group_id':proof['event_group_id'],'outcome':proof['outcome'],'official_evidence_sha256':proof['official_evidence_sha256']})
assert len(rows)==18
r={'at':now.isoformat(),'scope':'all18 current-enrollment canonical labels independently replayed from production originals and saved raw sources; no writes','labels':rows,'verified':len(rows),'enrollment_id':eid}
pathlib.Path('.planning/evidence/phase32/production-replay.json').write_text(json.dumps(r,indent=2)+'\n');print('canonical_labels_replayed',len(rows))
