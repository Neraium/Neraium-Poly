"""Bounded official-status inventory; metadata is NEVER a native payout proof."""
import hashlib,json
from datetime import UTC,datetime
from pathlib import Path

import httpx
from neraium_poly.research.phase14.relationships import digest
from neraium_poly.research.phase17.provenance import ReadonlyArchive
from neraium_poly.research.phase47.cohort import FROZEN

store=ReadonlyArchive('/home/ubuntu/Neraium-Poly/data/experimental-paper');cached={};used=0;rows=[]
with httpx.Client(timeout=3,trust_env=False) as client:
 for trial_id in FROZEN:
  original=store.get(trial_id);assert original;trial=json.loads(original[1]);f=trial['source_forecast'];binding=trial['source_binding'];assert digest(f)==binding['forecast_sha256'];market=f['market_id'];url='https://gamma-api.polymarket.com/markets/'+market
  if market not in cached:
   try:
    with client.stream('GET',url) as response:
     raw=bytearray()
     for part in response.iter_bytes():
      used+=len(part)
      if used>2*1024**2:raise ValueError('diagnostic2MiB response bound')
      raw.extend(part)
     response.raise_for_status()
    g=json.loads(raw);cached[market]={'observed_at':datetime.now(UTC).isoformat(),'response_sha256':hashlib.sha256(raw).hexdigest(),'g':g}
   except (ValueError,httpx.HTTPError) as e:cached[market]={'error':str(e)[:120]}
  observed=cached[market];g=observed.get('g');identity=False
  if g:
   tokens=g['clobTokenIds'];tokens=json.loads(tokens) if isinstance(tokens,str) else tokens
   identity=str(g['id'])==market and f['token_id'] in tokens and hashlib.sha256(g['description'].encode()).hexdigest()==f['rules_sha256'] and g['question']==f['market']['question'] and g.get('resolutionSource')==f['market']['resolution_source']
  rows.append({'trial_id':trial_id,'forecast_id':f['id'],'forecast_timestamp':f['timestamp'],'decision_timestamp':trial['timestamp'],'canonical_event':trial['canonical_event'],'dependency_block':trial['dependency_block'],'market_id':market,'token_id':f['token_id'],'question':f['market']['question'],'probabilities':trial['probabilities'],'binding':binding,'event_end':f['event_end_time'],'source_url':url,'observed_at':observed.get('observed_at'),'raw_status_sha256':observed.get('response_sha256'),'exact_identity_matches':identity,'metadata_closed':g.get('closed') if g else None,'metadata_uma_status':g.get('umaResolutionStatus') if g else None,'condition_id':g.get('conditionId') if g else None,'native_payout':None,'status':'metadata_resolved_native_proof_required' if identity and g.get('closed') and g.get('umaResolutionStatus')=='resolved' else 'metadata_pending_or_disputed' if identity else 'identity_or_source_unverified','error':observed.get('error')})
r={'at':datetime.now(UTC).isoformat(),'trials':len(rows),'canonical_events':len({r['canonical_event'] for r in rows}),'dependency_blocks':len({r['dependency_block'] for r in rows}),'response_bytes':used,'unique_official_status_reads':len(cached),'native_proofs_created':0,'rows':rows,'limitation':'official status and hashes only; no price labels or native payouts inferred; frozen original trial IDs, source probabilities and timestamps unchanged'}
Path(__file__).with_name('cohort-before.json').write_text(json.dumps(r,indent=2)+'\n');print(json.dumps({'trials':len(rows),'status_counts':{s:sum(r['status']==s for r in rows) for s in {r['status'] for r in rows}},'bytes':used}))
