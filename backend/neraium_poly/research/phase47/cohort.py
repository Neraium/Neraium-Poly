"""Reconcile the frozen14, without changing original probabilities or policy."""
import json
from pathlib import Path

from neraium_poly.research.phase25.dependencies import at

FROZEN=json.loads(Path(__file__).with_name('cohort.json').read_bytes())['original_trial_ids']


def watch(program,now):
    # Outcome-blind near-term monitoring can discover barrier resolution BEFORE
    # scheduled end. Pending Gamma metadata never becomes a payout.
    return {r['source_forecast']['id']:{'forecast':r['source_forecast'],'study_id':r['source_binding']['study_id'],'study_sha256':r['source_binding']['study_sha256'],'monitor_native':True}
            for key,r in program.rows.items() if key in FROZEN and key not in program.results and (at(r['source_forecast']['event_end_time'])-at(now)).total_seconds()<=86400}


def report(program,attempts,now):
    latest={}
    for row in attempts:latest.setdefault(row['forecast_id'],row)
    rows=[]
    for key in FROZEN:
        r=program.rows.get(key)
        if r is None:rows.append({'trial_id':key,'status':'original_trial_missing_fail_closed'});continue
        f=r['source_forecast'];result=program.results.get(key);attempt=latest.get(f['id']);reason=attempt.get('reason') if attempt else None
        retry=at(attempt['available_at']).timestamp()+(1800 if 'pending_or_disputed' in (reason or '') else 3600) if attempt and not attempt['verified'] else None
        rows.append({'trial_id':key,'forecast_id':f['id'],'forecast_timestamp':f['timestamp'],'decision_timestamp':r['timestamp'],'market_id':f['market_id'],'token_id':f['token_id'],'question':f['market']['question'],
                     'canonical_event':r['canonical_event'],'dependency_block':r['dependency_block'],'probabilities':r['probabilities'],'source_binding':r['source_binding'],'event_end_time':f['event_end_time'],
                     'status':'native_verified' if result else 'awaiting_native_evidence' if at(f['event_end_time'])<=at(now) else 'scheduled_end_not_reached_native_monitor_eligible' if f['id'] in watch(program,now) else 'scheduled_end_not_reached',
                     'native_proof':result['proof'] if result else None,'last_attempt_reason':reason,'last_attempt_at':attempt['available_at'] if attempt else None,'retry_eligible_unix':retry})
    return {'original_trials':14,'canonical_events':len({r['canonical_event'] for r in rows if 'canonical_event' in r}),'dependency_blocks':len({r['dependency_block'] for r in rows if 'dependency_block' in r}),'verified_trials':sum(r['status']=='native_verified' for r in rows),
            'rows':rows,'reviewed_independent_samples':0,'limitation':'native parents and operational dependency blocks are not statistical independence; unchanged original programme scores and certification gates'}
