"""Reuse the existing finalized native/CTF proof collector for every binary token.

Official event scoring is separate. A missing/disputed/fractional/unsupported
native proof leaves positions unresolved; price marks never become settlements.
"""
from pathlib import Path
from typing import Literal

from neraium_poly.contracts import MarketSnapshot, Record
from neraium_poly.research.phase12.contracts import SettlementProofReference, VerifiedEventOutcome
from neraium_poly.research.phase12.outcome_collector import acquire_verified_outcome, verify_collected_outcome
from neraium_poly.research.phase14.relationships import digest
from neraium_poly.research.phase24.continuous import at


class ProfilePayoutStudy(Record):
    forecast_id:str
    forecast_sha256:str
    original_study_sha256:str
    reference:dict
    outcome:dict|None=None
    verified:bool=False
    reason:str
    research_only:Literal[True]=True
    trading_authority:Literal[False]=False


async def collect(bound,store,directory,*,clock,can_write,max_requests=2):
    if not 0<=max_requests<=2:raise ValueError('bounded native requests required')
    directory=Path(directory);found={};last={};now=at(clock())
    rows=store.latest('ProfilePayoutStudy',256)
    def reference(f):return SettlementProofReference(id=f['id'],event_id=f['event_id'],market_id=f['market_id'],token_id=f['token_id'],
        timestamp=at(f['timestamp']),evidence_cutoff=at(f['evidence_cutoff']),resolution_rules_sha256=f['rules_sha256'],original_record_sha256=digest(f))
    def replay(row):
        item=bound.get(row['forecast_id'])
        if item is None or digest(item['forecast'])!=row['forecast_sha256'] or digest(item['study'])!=row['original_study_sha256']:return None
        f=item['forecast'];ref=reference(f);m=MarketSnapshot.model_validate(f['market'])
        if ref.model_dump(mode='json')!=row['reference'] or row['outcome'] is None:return None
        outcome=VerifiedEventOutcome.model_validate(row['outcome'])
        if not verify_collected_outcome(outcome,m,ref,directory):return None
        return {'forecast_id':f['id'],'event_id':f['event_id'],'market_id':f['market_id'],'token_id':f['token_id'],
            'rules_sha256':f['rules_sha256'],'payout':outcome.payout,'resolved_at':outcome.settled_at.isoformat(),
            'available_at':outcome.available_at.isoformat(),'verified':True,'native_payout_verified':True,
            'proof_sha256':outcome.proof_sha256,'verification_source':outcome.verification_source,'independence_reviewed':False,
            'scope':'verified native token payout; separate official event-model truth/calibration not inferred'}
    for row in rows:
        last.setdefault(row['forecast_id'],row['available_at'])
        if row['verified'] and row['forecast_id'] not in found:
            verified=replay(row)
            if verified is not None:found[row['forecast_id']]=verified
    due=[fid for fid,item in bound.items() if at(item['forecast']['event_end_time'])<=now and fid not in found]
    for fid in sorted(due,key=lambda v:(last.get(v,''),v))[:max_requests]:
        if not can_write():break
        f=bound[fid]['forecast'];ref=reference(f);m=MarketSnapshot.model_validate(f['market'])
        outcome=await acquire_verified_outcome(ref,m,directory/digest([fid,now.isoformat()]),clock=clock)
        value={'forecast_id':fid,'forecast_sha256':digest(f),'original_study_sha256':digest(bound[fid]['study']),
            'reference':ref.model_dump(mode='json'),'outcome':outcome.model_dump(mode='json') if outcome else None}
        verified=replay(value);ended=at(clock())
        row=ProfilePayoutStudy(id=digest(['profile-native-payout',value,ended.isoformat()]),timestamp=ended,available_at=ended,
            source='neraium-poly/profile-native-payout/v41',**value,verified=verified is not None,
            reason='independently_replayed_native_payout' if verified else 'native_finality_or_supported_binary_protocol_unavailable')
        if not can_write():raise ValueError('native proof publication capacity unavailable')
        store.append(row)
        if verified is not None:found[fid]=verified
    return found
