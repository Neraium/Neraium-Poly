import json,sqlite3,datetime,pathlib
from neraium_poly.research.phase17.provenance import ReadonlyArchive
from neraium_poly.research.phase16.checkpoints import unpack_checkpoint
from neraium_poly.research.phase31.scorecard import build_scorecard
from neraium_poly.research.phase14.relationships import digest
with ReadonlyArchive(pathlib.Path('data/experimental-paper')) as archive:r=archive.latest('VolumeStudy',limit=1)[0]
f=unpack_checkpoint(r['decision_frame']);assert digest(f)==r['decision_frame_sha256']
c=sqlite3.connect('file:data/experimental-paper/research-projection.sqlite?mode=ro',uri=True);entries=[json.loads(v[0]) for v in c.execute('SELECT payload FROM entries')];c.close()
v=build_scorecard(entries,f,r['report'],{}, {},as_of=datetime.datetime.fromisoformat(r['timestamp']))
out={'scope':'as-recorded genuine economic frame replay, no canonical append, no forecast or fill created','source_volume_study_id':r['id'],'frame_sha256':r['decision_frame_sha256'],'as_of':v['as_of'],'frame_age_seconds':v['frame_age_seconds'],'fresh_executable_tokens_at_evaluation':sum(d['fresh_executable_tokens_at_evaluation'] for d in v['domains'].values()),'frame_fresh_at_evaluation':v['frame_fresh_at_evaluation']}
pathlib.Path('.planning/evidence/phase31/scorecard-replay.json').write_text(json.dumps(out,indent=2)+'\n');print(json.dumps(out))
