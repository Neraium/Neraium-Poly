"""Read-only, bounded reconciliation of distinct append-only forecast scopes."""

import hashlib
import json
import sqlite3
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from neraium_poly.research.phase12.ledger import content_sha256
from neraium_poly.research.phase14.relationships import digest
from neraium_poly.research.phase17.provenance import ReadonlyArchive

KINDS=('EventProbabilityStudy','ChallengerStudy','DomainResearchStudy')
PHASE23_REPORTED_AT=datetime(2026,11,7,22,21,27,646946,tzinfo=UTC)


def _at(value):
    value=value if isinstance(value,datetime) else datetime.fromisoformat(value)
    if value.tzinfo is None or value.utcoffset() is None:raise ValueError('aware_reconciliation_cutoff_required')
    return value.astimezone(UTC)


def _entry(f,scope,study_id,study_sha):
    if scope=='phase13_nfl':
        mapping=f['mapping'];event=mapping['event_id'];model=f['prediction']['model_version']
        market=mapping['market_id'];token=mapping['token_id']
    else:
        event=f['event_id'];market=f['market_id'];token=f['token_id'];model=f.get('model_id',f.get('model_version'))
    return {'forecast_id':f['id'],'scope':scope,'timestamp':_at(f['timestamp']).isoformat(),
        'event_id':event,'market_id':market,'token_id':token,'model_version':model,
        'forecast_sha256':digest(f),'original_record_id':study_id,'original_record_sha256':study_sha}


def _replay_archive(study,f,scope,root,now):
    if scope=='phase18_crypto':
        from neraium_poly.research.phase19.qualification import replay_event_forecast
        if replay_event_forecast(study).get('verified') is not True:raise ValueError('original_phase18_model_replay_failed')
    elif scope=='phase23_challengers':
        if f.get('domain')=='crypto':
            from neraium_poly.research.phase23.outcomes import replay_forecast
            replay_forecast(study,f,as_of=now)
        elif f.get('domain')=='sports':
            from neraium_poly.research.phase13.sources import load_sports
            from neraium_poly.research.phase23.models import forecast_nfl
            source=Path(f['source_reference']['snapshot']).resolve()
            if not source.is_relative_to(root.resolve()):raise ValueError('sports_source_outside_reconciled_archive')
            data=load_sports(source)
            if data['manifest_sha256']!=f['source_reference']['manifest_sha256']:raise ValueError('sports_manifest_mismatch')
            result=next(x for x in forecast_nfl(f['market'],data,cutoff=_at(f['evidence_cutoff'])) if x['model_id']==f['model_id'])
            if any(f.get(k)!=v for k,v in result.items()):raise ValueError('original_nfl_challenger_replay_failed')
        else:raise ValueError('unknown_phase23_model_domain')
    # New domain adapters independently replay their own frozen evidence through
    # the coordinator. Inventorying them never silently asserts validation.


def _sports_journal(root,now):
    path=root/'event-intelligence/sports/prospective.sqlite'
    if not path.exists():return [],{'status':'absent','records':0,'head_sha256':None}
    if path.is_symlink():raise ValueError('symlinked_sports_journal')
    c=sqlite3.connect(path.absolute().as_uri()+'?mode=ro',uri=True,timeout=3);c.row_factory=sqlite3.Row
    c.execute('PRAGMA query_only=ON');c.execute('BEGIN')
    result=[];previous=None;count=0;prefixes={}
    try:
        for row in c.execute('SELECT * FROM records ORDER BY seq'):
            count+=1
            if count>100000 or len(row['payload'].encode())>1024**2:raise ValueError('bounded_sports_journal_required')
            f=json.loads(row['payload']);sha=content_sha256(f)
            if (sha!=row['digest'] or row['previous']!=previous
                or row['chain']!=content_sha256([previous,row['kind'],row['id'],sha])):
                raise ValueError('sports_journal_chain_integrity_failure')
            previous=row['chain']
            if count==3:prefixes['3']=previous
            if row['kind']=='forecast' and _at(f['timestamp'])<=now:
                from neraium_poly.research.phase13.mapping import map_market
                from neraium_poly.research.phase13.models import predict_game
                from neraium_poly.research.phase13.runtime import SportsResearchRuntime, TernarySportsForecast
                from neraium_poly.research.phase13.sources import load_sports
                forecast=TernarySportsForecast.model_validate(f)
                source=(path.parent/forecast.snapshot).resolve()
                if not source.is_relative_to(root.resolve()):raise ValueError('original_sports_snapshot_path_escape')
                data=load_sports(source)
                if SportsResearchRuntime._dataset_identity(data)!=forecast.source_dataset_sha256:raise ValueError('original_sports_dataset_mismatch')
                mapping=map_market(forecast.market,data['games'],now=forecast.timestamp)
                prediction=predict_game(data['games'],SportsResearchRuntime._target(data,mapping),mapping.selected_team_id,forecast.timestamp,method='frequency')
                if mapping!=forecast.mapping or prediction!=forecast.prediction:raise ValueError('original_ternary_model_replay_failed')
                result.append(_entry(f,'phase13_nfl',row['id'],sha))
    finally:c.close()
    return result,{'status':'verified','records':count,'head_sha256':previous,'source_path':str(path),'prefix_heads':prefixes}


def reconcile(data_dir,*,as_of,reference_directory=None):
    """Full bounded inventory, not a latest-record tail or a reconstructed history.

    The 27 and18 reported counts identify different original-model namespaces.
    Additional forecasts are counted only when their original immutable rows
    exist and predate the supplied cutoff. Repeated tokens/models are not events.
    """
    now=_at(as_of);root=Path(data_dir).absolute();entries=[];identities={};payloads={};duplicates=[];used=0;totals={}
    with ReadonlyArchive(root,max_query_bytes=128*1024**2) as archive:
        for kind in KINDS:
            rows=archive._catalog_rows('SELECT * FROM records WHERE kind=? AND available_at<=? ORDER BY available_at,id LIMIT 2001',(kind,now.isoformat()))
            if len(rows)>2000:raise ValueError('forecast_inventory_requires_explicit_bounded_backfill')
            totals[kind]=len(rows)
            for row in rows:
                raw=archive._fetch(row);used+=len(raw[1].encode())
                if used>128*1024**2:raise ValueError('forecast_inventory_byte_budget')
                study=json.loads(raw[1])
                if _at(study['available_at'])>now:continue
                scope={'EventProbabilityStudy':'phase18_crypto','ChallengerStudy':'phase23_challengers','DomainResearchStudy':'phase24_domains'}[kind]
                forecasts=([study['forecast']] if kind=='EventProbabilityStudy' and study.get('operation')=='forecast_scan' and study.get('forecast') else study.get('forecasts',[]) if kind!='EventProbabilityStudy' else [])
                for f in forecasts:
                    if not _at(f['timestamp'])<=_at(study['available_at'])<=now:raise ValueError('forecast_timestamp_not_in_original_record')
                    _replay_archive(study,f,scope,root,now)
                    e=_entry(f,scope,study['id'],digest(study));key=(scope,f['id'])
                    if key in identities:
                        if identities[key]['forecast_sha256']!=e['forecast_sha256']:raise ValueError('conflicting_duplicate_original_forecast')
                        duplicates.append({'scope':scope,'forecast_id':f['id'],'record_id':study['id']});continue
                    identities[key]=e;payloads[key]=f;entries.append(e)
    sports,journal=_sports_journal(root,now);entries+=sports
    refs=Path(reference_directory) if reference_directory else root.parent.parent/'.planning/evidence'
    preserved={};witnesses=[]
    p22=refs/'phase22-evidence/forecast-audit.json'
    if p22.exists():
        original=p22.read_bytes();reference=json.loads(original);old={e['forecast_id']:e for e in entries if e['scope'] in {'phase18_crypto','phase13_nfl'}}
        if journal.get('prefix_heads',{}).get(str(reference['sports_journal_records']))!=reference['sports_journal_head_sha256']:
            raise ValueError('original_sports_journal_prefix_changed')
        expected={f['forecast_id'] for f in reference['crypto']+reference['sports']}
        missing=sorted(expected-set(old))
        if missing:raise ValueError('missing_preserved_phase22_forecasts:'+','.join(missing))
        for f in reference['crypto']:
            if old[f['forecast_id']]['original_record_sha256']!=f['original_study_sha256']:raise ValueError('phase22_original_forecast_changed')
        preserved['phase22_reported_27']={'expected':len(expected),'preserved':len(expected),'missing':[],'ids':sorted(expected)}
        witnesses.append({'path':str(p22),'sha256':hashlib.sha256(original).hexdigest()})
    p23=refs/'phase23/forecasts-final.json'
    if p23.exists():
        original=p23.read_bytes();reference=json.loads(original);new={e['forecast_id']:e for e in entries if e['scope']=='phase23_challengers'}
        expected={f['id'] for f in reference['forecast_rows'] if _at(f['timestamp'])<=now}
        missing=sorted(expected-set(new))
        if missing:raise ValueError('missing_preserved_phase23_forecasts:'+','.join(missing))
        for original_forecast in reference['forecast_rows']:
            if original_forecast['id'] not in expected:continue
            actual=payloads[('phase23_challengers',original_forecast['id'])]
            if any(actual.get(k)!=v for k,v in original_forecast.items()):raise ValueError('phase23_original_prediction_changed')
        preserved['phase23_reported_18']={'expected':len(expected),'preserved':len(expected),'missing':[],'ids':sorted(expected)}
        witnesses.append({'path':str(p23),'sha256':hashlib.sha256(original).hexdigest()})
    counts=dict(Counter(e['scope'] for e in entries));scopes={}
    for name in ('phase18_crypto','phase13_nfl','phase23_challengers','phase24_domains'):
        rows=[e for e in entries if e['scope']==name]
        scopes[name]={'forecasts':len(rows),'native_parent_ids':sorted({e['event_id'] for e in rows}),'models':dict(Counter(e['model_version'] for e in rows)),
            'content_set_sha256':digest(sorted((e['forecast_id'],e['forecast_sha256']) for e in rows)),
            'source_model_replayed':name!='phase24_domains','scope':'original immutable records, never reconstructed predictions'}
    return {'schema_version':'phase24-forecast-reconciliation-v1','as_of':now.isoformat(),'archive_records_examined':totals,'bytes_examined':used,
        'scopes':scopes,'scope_counts':counts,'total_original_forecasts':len(entries),'additional_legacy_nfl_since_reported_three':max(0,counts.get('phase13_nfl',0)-3),'native_parent_ids':len({e['event_id'] for e in entries}),
        'reviewed_independent_event_groups':0,'qualified_training_events':0,'qualified_heldout_events':0,'preservation_witnesses':preserved,
        'reference_artifacts':witnesses,'sports_journal':journal,'duplicates':duplicates,'forecasts':sorted(entries,key=lambda e:(e['timestamp'],e['scope'],e['forecast_id'])),
        'explanation':'27=24original crypto+3original NFL;18=additional Phase23 challenger forecasts. Different model/journal scopes, not a replacement or deletion. Repeated parent/model/token observations never increase independent events.',
        'calibration_status':'independently_verified_event_disjoint_outcomes_required','trading_authority':False,'certification_authority':False}
