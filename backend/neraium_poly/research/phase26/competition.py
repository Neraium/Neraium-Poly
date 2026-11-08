"""Compact anchored projections: stable counts without old raw-source rereads."""
from collections import Counter, defaultdict

from neraium_poly.research.phase14.relationships import digest
from neraium_poly.research.phase25.dependencies import AUTHORITY, at


def projection_report(entries,*,as_of):
    now=at(as_of);forecasts={};conflicts=set();rejections=Counter();declarations={};outcomes=defaultdict(list)
    for row in entries:
        if row['type']=='declaration':declarations[row['definition']['model_id']]=row['definition']
        elif row['type']=='forecast':
            identity=row['forecast_id']
            if identity in forecasts and forecasts[identity]['forecast_sha256']!=row['forecast_sha256']:conflicts.add(identity)
            forecasts.setdefault(identity,row)
            if row['rejection']:rejections[row['rejection']]+=1
        elif row['type']=='outcome':outcomes[row.get('forecast_id')].append(row)
        elif row['type']=='rejection':rejections[row['reason']]+=row['count']
    for identity in conflicts:forecasts.pop(identity,None)
    if conflicts:rejections['conflicting_original_forecast_identity']+=len(conflicts)
    source_games=defaultdict(set)
    for row in forecasts.values():
        r=row.get('review') or {};d=r.get('descriptor',{})
        if d.get('source_game_id'):source_games[(d['source_id_namespace'],d['source_game_id'])].add(r['canonical_group_id'])
    conflicting_games={k for k,v in source_games.items() if len(v)>1}
    reviewed={}
    for identity,row in forecasts.items():
        r=row.get('review');d=(r or {}).get('descriptor',{})
        if r and (d.get('source_id_namespace'),d.get('source_game_id')) not in conflicting_games and row['replay_verified']:reviewed[identity]=row
    if conflicting_games:rejections['conflicting_source_game_identity']+=len(conflicting_games)
    groups={row['review']['canonical_group_id'] for row in reviewed.values()};parents={g:g for g in groups};tags=defaultdict(set)
    def root(group):
        while parents[group]!=group:group=parents[group]
        return group
    for row in reviewed.values():
        for tag in row['review']['dependency_tags']:tags[tag].add(row['review']['canonical_group_id'])
    for values in tags.values():
        values=sorted(values)
        for group in values[1:]:
            a,b=root(values[0]),root(group)
            if a!=b:parents[max(a,b)]=min(a,b)
    cohorts=defaultdict(list)
    for row in reviewed.values():cohorts[row['cohort_id']].append(row)
    disagreements=[]
    for key,rows in sorted(cohorts.items()):
        models=[r['forecast'].get('model_id',r['forecast'].get('model_version')) for r in rows]
        if len(set(models))!=len(models):rejections['duplicate_model_in_comparison_cohort']+=1;continue
        if len(rows)>1:disagreements.append({'cohort_id':key,'forecast_ids':sorted(r['forecast_id'] for r in rows),'model_ids':sorted(models),
            'probability_range':max(r['forecast']['probability'] for r in rows)-min(r['forecast']['probability'] for r in rows),
            'independent_confirmation_count':None,'ensemble_probability':None})
    verified={}
    for identity,rows in outcomes.items():
        if identity not in reviewed:continue
        if any(r.get('status') in ('disputed','corrected','revoked') for r in rows):rejections['outcome_disputed_or_corrected_unscored']+=1;continue
        proofs={digest(r['proof']):r['proof'] for r in rows if r['verified'] and r['proof'] and at(r['proof']['available_at'])<=now}
        if len(proofs)>1:rejections['conflicting_verified_result']+=1
        elif proofs:verified[identity]=next(iter(proofs.values()))
        for row in rows:
            if row.get('rejection'):rejections[row['rejection']]+=1
    bymodel=defaultdict(list)
    for row in forecasts.values():bymodel[row['forecast'].get('model_id',row['forecast'].get('model_version'))].append(row)
    leaderboard=[]
    for model in sorted(set(declarations)|set(bymodel)):
        rows=bymodel[model];scores=[verified[r['forecast_id']] for r in rows if r['forecast_id'] in verified]
        leaderboard.append({'model_id':model,'forecasts':len(rows),'verified_forecast_outcomes':len(scores),'pending_forecasts':len(rows)-len(scores),
            'native_parent_ids':len({r['forecast']['event_id'] for r in rows}),'model_sha256s':sorted({r['forecast'].get('model_sha256') for r in rows}),
            'descriptive_verified_scores':scores,'calibration':None,'metrics':None,'confidence_intervals':None,'profitability_rank':None,
            'independent_event_count':0,'net_executable_edge':None,'simulated_pnl':None,'reason':'independent calibrated event-disjoint cohorts remain required',**AUTHORITY})
    counts={'forecasts':len(forecasts),'individually_verified_forecasts':len(verified),'pending_forecasts':len(forecasts)-len(verified),'reviewed_independent_groups':0}
    eventcounts={'forecasts_examined':len(forecasts),'source_identity_reviewed_forecasts':len(reviewed),'native_parent_ids':len({r['forecast']['event_id'] for r in forecasts.values()}),
        'reviewed_canonical_groups':len(groups),'conservative_dependency_clusters':len({root(g) for g in groups}),'statistically_independent_events':0,'certification_independent_events':0}
    research={'event_review':{'counts':eventcounts,'reviews':[{**r['review'],'forecast_id':r['forecast_id'],'original_study_id':r['source_id'],
                'original_study_sha256':r['source_study_sha256'],'original_forecast_sha256':r['forecast_sha256']} for r in reviewed.values()],**AUTHORITY},
        'same_cohort_disagreements':disagreements,'sii':{'qualified_pairs':0,'resolved_pairs':[],'incremental_predictive_value':None,
            'reason':'independent causal feature and outcome pair replay required; flags never qualify'},
        'ensemble':{'weights':None,'probabilities':None,'reason':'event-disjoint calibration not established'},**AUTHORITY}
    return {'schema_version':'phase26-indexed-competition-v1','as_of':now.isoformat(),'counts':counts,'leaderboard':leaderboard,'research_competition':research,
        'domains':dict(Counter(r['forecast'].get('domain','unknown') for r in forecasts.values())),'rejections':dict(rejections),
        'certification_requirements':{'training_independent_events':100,'heldout_independent_events':100},'sii_incremental_value':None,
        'view_scope':'complete anchored indexed P23/P24/P25 registries; bootstrap/progress explicit; legacy Phase18/13 separately reconciled',**AUTHORITY}
