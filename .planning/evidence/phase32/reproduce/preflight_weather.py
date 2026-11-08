import json,pathlib,datetime
from neraium_poly.research.phase32.weather import replay_weather_event
from neraium_poly.research.phase31.scoring import evaluate_domains
root=pathlib.Path('/home/ubuntu/.local/share/neraium-citadel/worktrees/3e041d43987e0512/poly-p32-weather-20261108/data/phase32-weather');labels=[]
for row in json.load(open(root/'results-full-local.json')):
 r=row['result']
 if r.get('event_result_verified') is not True:continue
 original=json.load(open(root/(row['forecast_id']+'.json')));study,f=original['study'],original['forecast']
 proof=replay_weather_event(r,study,f,evidence_root=root/'official',as_of=datetime.datetime.now(datetime.UTC))
 labels.append({'label_id':'READONLY-PREFLIGHT-'+f['id'],'forecast':f,'forecast_available_at':study['available_at'],'proof':proof})
r=evaluate_domains(labels);r['scope']='root independent read-only replay of authentic worker evidence; not canonical labels until service publishes';pathlib.Path('.planning/evidence/phase32/weather-preflight.json').write_text(json.dumps(r,indent=2)+'\n')
print({k:r[k] for k in ['verified_forecast_labels','event_groups_by_domain','rejections']});print([(m['model_id'],m['event_disjoint_groups'],m['descriptive_brier']) for m in r['models']])
